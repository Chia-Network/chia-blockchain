from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional, Tuple, Type, Union

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.mark.structures import ParameterSet
from typing_extensions import final

from chia.util.ints import (
    Int8Enum,
    Int16Enum,
    Int32Enum,
    SizedIntEnum,
    UInt8Enum,
    UInt16Enum,
    UInt32Enum,
    int8,
    int16,
    int32,
    int64,
    int512,
    uint8,
    uint16,
    uint32,
    uint64,
    uint128,
)
from chia.util.struct_stream import StructStream, parse_metadata_from_name


def dataclass_parameter(instance: object) -> ParameterSet:
    return pytest.param(instance, id=repr(instance)[len(type(instance).__name__) + 1 : -1])


def dataclass_parameters(instances: Iterable[object]) -> List[ParameterSet]:
    return [dataclass_parameter(instance) for instance in instances]


@dataclass(frozen=True)
class BadName:
    name: str
    error: str


@final
@dataclass(frozen=True)
class Good:
    name: str
    cls: Type[StructStream]
    size: int
    bits: int
    signed: bool
    maximum_exclusive: int
    minimum: int

    @classmethod
    def create(
        cls,
        name: str,
        size: int,
        signed: bool,
        maximum_exclusive: int,
        minimum: int,
    ) -> Good:
        raw_class: Type[StructStream] = type(name, (StructStream,), {})
        parsed_cls = parse_metadata_from_name(raw_class)
        return cls(
            name=name,
            cls=parsed_cls,
            size=size,
            bits=size * 8,
            signed=signed,
            maximum_exclusive=maximum_exclusive,
            minimum=minimum,
        )


good_classes = [
    Good.create(name="uint8", size=1, signed=False, maximum_exclusive=0xFF + 1, minimum=0),
    Good.create(name="int8", size=1, signed=True, maximum_exclusive=0x80, minimum=-0x80),
    Good.create(name="uint16", size=2, signed=False, maximum_exclusive=0xFFFF + 1, minimum=0),
    Good.create(name="int16", size=2, signed=True, maximum_exclusive=0x8000, minimum=-0x8000),
    Good.create(name="uint24", size=3, signed=False, maximum_exclusive=0xFFFFFF + 1, minimum=0),
    Good.create(name="int24", size=3, signed=True, maximum_exclusive=0x800000, minimum=-0x800000),
    Good.create(
        name="uint128",
        size=16,
        signed=False,
        maximum_exclusive=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF + 1,
        minimum=0,
    ),
    Good.create(
        name="int128",
        size=16,
        signed=True,
        maximum_exclusive=0x80000000000000000000000000000000,
        minimum=-0x80000000000000000000000000000000,
    ),
]


@pytest.fixture(
    name="good",
    params=dataclass_parameters(good_classes),
)
def good_fixture(request: SubRequest) -> Good:
    return request.param  # type: ignore[no-any-return]


class TestStructStream:
    def _test_impl(
        self,
        cls: Type[StructStream],
        upper_boundary: int,
        lower_boundary: int,
        length: int,
        struct_format: Optional[str],
    ) -> None:
        with pytest.raises(ValueError):
            t = cls(upper_boundary + 1)

        with pytest.raises(ValueError):
            t = cls(lower_boundary - 1)

        t = cls(upper_boundary)
        assert t == upper_boundary

        t = cls(lower_boundary)
        assert t == lower_boundary

        t = cls(0)
        assert t == 0

        with pytest.raises(ValueError):
            cls.parse(io.BytesIO(b"\0" * (length - 1)))

        with pytest.raises(ValueError):
            cls.from_bytes(b"\0" * (length - 1))

        with pytest.raises(ValueError):
            cls.from_bytes(b"\0" * (length + 1))

        if struct_format is not None:
            bytes_io = io.BytesIO()
            cls(lower_boundary).stream(bytes_io)
            assert bytes_io.getvalue() == struct.pack(struct_format, lower_boundary)

            bytes_io = io.BytesIO()
            cls(upper_boundary).stream(bytes_io)
            assert bytes_io.getvalue() == struct.pack(struct_format, upper_boundary)

            with pytest.raises(struct.error):
                struct.pack(struct_format, lower_boundary - 1)
            with pytest.raises(struct.error):
                struct.pack(struct_format, upper_boundary + 1)

    def test_int512(self) -> None:
        # int512 is special. it uses 65 bytes to allow positive and negative
        # "uint512"
        self._test_impl(
            int512,
            0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,  # noqa: E501
            -0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,  # noqa: E501
            length=65,
            struct_format=None,
        )

    def test_uint128(self) -> None:
        self._test_impl(uint128, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF, 0, length=16, struct_format=None)

    def test_uint64(self) -> None:
        self._test_impl(uint64, 0xFFFFFFFFFFFFFFFF, 0, length=8, struct_format="!Q")

    def test_int64(self) -> None:
        self._test_impl(int64, 0x7FFFFFFFFFFFFFFF, -0x8000000000000000, length=8, struct_format="!q")

    def test_uint32(self) -> None:
        self._test_impl(uint32, 0xFFFFFFFF, 0, length=4, struct_format="!L")

    def test_int32(self) -> None:
        self._test_impl(int32, 0x7FFFFFFF, -0x80000000, length=4, struct_format="!l")

    def test_uint16(self) -> None:
        self._test_impl(uint16, 0xFFFF, 0, length=2, struct_format="!H")

    def test_int16(self) -> None:
        self._test_impl(int16, 0x7FFF, -0x8000, length=2, struct_format="!h")

    def test_uint8(self) -> None:
        self._test_impl(uint8, 0xFF, 0, length=1, struct_format="!B")

    def test_int8(self) -> None:
        self._test_impl(int8, 0x7F, -0x80, length=1, struct_format="!b")

    def test_roundtrip(self) -> None:
        def roundtrip(v: StructStream) -> None:
            s = io.BytesIO()
            v.stream(s)
            s.seek(0)
            cls = type(v)
            v2 = cls.parse(s)
            assert v2 == v

        # int512 is special. it uses 65 bytes to allow positive and negative
        # "uint512"
        roundtrip(
            int512(
                0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  # noqa: E501
            )
        )
        roundtrip(
            int512(
                -0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  # noqa: E501
            )
        )

        roundtrip(uint128(0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF))
        roundtrip(uint128(0))

        roundtrip(uint64(0xFFFFFFFFFFFFFFFF))
        roundtrip(uint64(0))

        roundtrip(int64(0x7FFFFFFFFFFFFFFF))
        roundtrip(int64(-0x8000000000000000))

        roundtrip(uint32(0xFFFFFFFF))
        roundtrip(uint32(0))

        roundtrip(int32(0x7FFFFFFF))
        roundtrip(int32(-0x80000000))

        roundtrip(uint16(0xFFFF))
        roundtrip(uint16(0))

        roundtrip(int16(0x7FFF))
        roundtrip(int16(-0x8000))

        roundtrip(uint8(0xFF))
        roundtrip(uint8(0))

        roundtrip(int8(0x7F))
        roundtrip(int8(-0x80))

    def test_uint32_from_decimal(self) -> None:
        assert uint32(Decimal("137")) == 137

    def test_uint32_from_float(self) -> None:
        assert uint32(4.0) == 4

    def test_uint32_from_str(self) -> None:
        assert uint32("43") == 43

    def test_uint32_from_bytes(self) -> None:
        assert uint32(b"273") == 273

    def test_struct_stream_cannot_be_instantiated_directly(self) -> None:
        with pytest.raises(ValueError, match="does not fit"):
            StructStream(0)

    @pytest.mark.parametrize(
        argnames="bad_name",
        argvalues=dataclass_parameters(
            instances=[
                BadName(name="uint", error="expected integer suffix but got: ''"),
                BadName(name="blue", error="expected integer suffix but got"),
                BadName(name="blue8", error="expected integer suffix but got: ''"),
                BadName(name="sint8", error="expected class name"),
                BadName(name="redint8", error="expected class name"),
                BadName(name="int7", error="must be a multiple of 8"),
                BadName(name="int9", error="must be a multiple of 8"),
                BadName(name="int31", error="must be a multiple of 8"),
                BadName(name="int0", error="bit size must greater than zero"),
                # below could not happen in a hard coded class name, but testing for good measure
                BadName(name="int-1", error="bit size must greater than zero"),
            ],
        ),
    )
    def test_parse_metadata_from_name_raises(self, bad_name: BadName) -> None:
        cls = type(bad_name.name, (StructStream,), {})
        with pytest.raises(ValueError, match=bad_name.error):
            parse_metadata_from_name(cls)

    def test_parse_metadata_from_name_correct_size(self, good: Good) -> None:
        assert good.cls.SIZE == good.size

    def test_parse_metadata_from_name_correct_bits(self, good: Good) -> None:
        assert good.cls.BITS == good.bits

    def test_parse_metadata_from_name_correct_signedness(self, good: Good) -> None:
        assert good.cls.SIGNED == good.signed

    def test_parse_metadata_from_name_correct_maximum(self, good: Good) -> None:
        assert good.cls.MAXIMUM_EXCLUSIVE == good.maximum_exclusive

    def test_parse_metadata_from_name_correct_minimum(self, good: Good) -> None:
        assert good.cls.MINIMUM == good.minimum


@pytest.mark.parametrize(
    "enum_type, int_type",
    [
        (Int8Enum, int8),
        (Int16Enum, int16),
        (Int32Enum, int32),
        (UInt8Enum, uint8),
        (UInt16Enum, uint16),
        (UInt32Enum, uint32),
    ],
)
def test_int_enum(enum_type: Type[SizedIntEnum], int_type: Type[StructStream]) -> None:
    # ignores here are to allow inheritance from `enum_type`
    class TestEnumClass(enum_type):  # type: ignore[valid-type, misc]
        min = int_type.MINIMUM
        one = 1
        max = int_type.MAXIMUM_EXCLUSIVE - 1

    assert TestEnumClass.one.name == "one"  # type: ignore[attr-defined] # pylint: disable = no-member
    assert type(TestEnumClass.one.value) == int_type  # type: ignore[attr-defined] # pylint: disable = no-member
    assert TestEnumClass.one.value == 1  # type: ignore[attr-defined] # pylint: disable = no-member
    assert int(TestEnumClass.one) == 1
    assert TestEnumClass(1) == TestEnumClass.one


@pytest.mark.parametrize(
    "enum_type, value, exception",
    [
        # Python 3.11 raises TypeError, Python 3.9 raises ValueError
        (Int8Enum, int8.MAXIMUM_EXCLUSIVE, (ValueError, TypeError)),
        (Int8Enum, "text", ValueError),
        (Int16Enum, int16.MAXIMUM_EXCLUSIVE, (ValueError, TypeError)),
        (Int16Enum, "text", ValueError),
        (Int32Enum, int32.MAXIMUM_EXCLUSIVE, (ValueError, TypeError)),
        (Int32Enum, "text", ValueError),
        (UInt8Enum, uint8.MAXIMUM_EXCLUSIVE, (ValueError, TypeError)),
        (UInt8Enum, "text", ValueError),
        (UInt16Enum, uint16.MAXIMUM_EXCLUSIVE, (ValueError, TypeError)),
        (UInt16Enum, "text", ValueError),
        (UInt32Enum, uint32.MAXIMUM_EXCLUSIVE, (ValueError, TypeError)),
        (UInt32Enum, "text", ValueError),
    ],
)
def test_int_enum_failure(
    enum_type: Type[SizedIntEnum],
    value: Union[int32, uint32],
    exception: Union[Type[Exception], Tuple[Type[Exception], ...]],
) -> None:
    with pytest.raises(exception):

        class BadEnum(enum_type):  # type: ignore[valid-type, misc] # ignore to allow subclassing `enum_type`
            bad_entry = value
