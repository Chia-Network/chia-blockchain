from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional, Type

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.mark.structures import ParameterSet
from typing_extensions import final

from chia.util.ints import int8, int16, int32, int64, int512, uint8, uint16, uint32, uint64, uint128
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
    maximum: int
    minimum: int

    @classmethod
    def create(
        cls,
        name: str,
        size: int,
        signed: bool,
        maximum: int,
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
            maximum=maximum,
            minimum=minimum,
        )


good_classes = [
    Good.create(name="uint8", size=1, signed=False, maximum=0xFF, minimum=0),
    Good.create(name="int8", size=1, signed=True, maximum=0x7F, minimum=-0x80),
    Good.create(name="uint16", size=2, signed=False, maximum=0xFFFF, minimum=0),
    Good.create(name="int16", size=2, signed=True, maximum=0x7FFF, minimum=-0x8000),
    Good.create(name="uint24", size=3, signed=False, maximum=0xFFFFFF, minimum=0),
    Good.create(name="int24", size=3, signed=True, maximum=0x7FFFFF, minimum=-0x800000),
    Good.create(
        name="uint128",
        size=16,
        signed=False,
        maximum=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        minimum=0,
    ),
    Good.create(
        name="int128",
        size=16,
        signed=True,
        maximum=0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
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

        assert type(cls.MINIMUM) == cls
        assert type(cls.MAXIMUM) == cls

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
        with pytest.raises(AttributeError, match="object has no attribute"):
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
        assert good.cls.MAXIMUM == good.maximum

    def test_parse_metadata_from_name_correct_minimum(self, good: Good) -> None:
        assert good.cls.MINIMUM == good.minimum
