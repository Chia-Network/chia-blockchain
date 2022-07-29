from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import struct
import io
from typing import Iterable, List, Optional, Type

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.mark.structures import ParameterSet

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest
from typing_extensions import final

from chia.util.ints import int8, uint8, int16, uint16, int32, uint32, int64, uint64, uint128, int512
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
    format: Optional[str]

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
        format: Optional[str] = None
        return cls(
            name=name,
            cls=parsed_cls,
            size=size,
            bits=size * 8,
            signed=signed,
            maximum_exclusive=maximum_exclusive,
            minimum=minimum,
            format=format,
        )

    @classmethod
    def from_existing(
        cls,
        existing: Type[StructStream],
        size: int,
        signed: bool,
        maximum_exclusive: int,
        minimum: int,
        bits: Optional[int] = None,
        format: Optional[str] = None,
    ) -> Good:
        if bits is None:
            bits = size * 8

        return cls(
            name=existing.__name__,
            cls=existing,
            size=size,
            bits=bits,
            signed=signed,
            maximum_exclusive=maximum_exclusive,
            minimum=minimum,
            format=format,
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
    Good.from_existing(existing=uint8, size=1, signed=False, maximum_exclusive=0xFF + 1, minimum=0, format="!B"),
    Good.from_existing(existing=int8, size=1, signed=True, maximum_exclusive=0x80, minimum=-0x80, format="!b"),
    Good.from_existing(existing=uint16, size=2, signed=False, maximum_exclusive=0xFFFF + 1, minimum=0, format="!H"),
    Good.from_existing(existing=int16, size=2, signed=True, maximum_exclusive=0x8000, minimum=-0x8000, format="!h"),
    Good.from_existing(existing=uint32, size=4, signed=False, maximum_exclusive=0xFFFFFFFF + 1, minimum=0, format="!L"),
    Good.from_existing(
        existing=int32, size=4, signed=True, maximum_exclusive=0x80000000, minimum=-0x80000000, format="!l"
    ),
    Good.from_existing(
        existing=uint64, size=8, signed=False, maximum_exclusive=0xFFFFFFFFFFFFFFFF + 1, minimum=0, format="!Q"
    ),
    Good.from_existing(
        existing=int64,
        size=8,
        signed=True,
        maximum_exclusive=0x8000000000000000,
        minimum=-0x8000000000000000,
        format="!q",
    ),
    Good.from_existing(
        existing=uint128,
        size=16,
        signed=False,
        maximum_exclusive=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF + 1,
        minimum=0,
    ),
    Good.from_existing(
        existing=int512,
        size=65,
        signed=True,
        maximum_exclusive=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF  # noqa: E501
        + 1,
        minimum=-0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,  # noqa: E501
        bits=512,
    ),
]


@pytest.fixture(
    name="good",
    params=dataclass_parameters(good_classes),
)
def good_fixture(request: SubRequest) -> Good:
    return request.param  # type: ignore[no-any-return]


@pytest.fixture(name="valid_limit", params=["minimum", "maximum"])
def valid_limit_fixture(request: SubRequest, good: Good) -> int:
    if request.param == "minimum":
        limit_value = good.minimum
    elif request.param == "maximum":
        limit_value = good.maximum_exclusive - 1
    else:
        raise Exception(f"invalid parametrization: {request.param}")

    return limit_value


@pytest.fixture(name="invalid_limit", params=["minimum", "maximum"])
def invalid_limit_fixture(request: SubRequest, good: Good) -> int:
    if request.param == "minimum":
        limit_value = good.minimum - 1
    elif request.param == "maximum":
        limit_value = good.maximum_exclusive
    else:
        raise Exception(f"invalid parametrization: {request.param}")

    return limit_value


def format_is_none(good: Good, **kwargs: object) -> bool:
    return good.format is None


def test_struct_stream_cannot_be_instantiated_directly() -> None:
    with pytest.raises(ValueError, match="does not fit"):
        StructStream(0)


def test_zero_equals(good: Good) -> None:
    assert good.cls(0) == 0


def test_below_minimum_raises(good: Good) -> None:
    with pytest.raises(ValueError):
        good.cls(good.minimum - 1)


def test_at_minimum_equals(good: Good) -> None:
    assert good.cls(good.minimum) == good.minimum


def test_below_maximum_equals(good: Good) -> None:
    value = good.maximum_exclusive - 1
    assert good.cls(value) == value


def test_at_maximum_exclusive_raises(good: Good) -> None:
    with pytest.raises(ValueError):
        good.cls(good.maximum_exclusive)


def test_too_few_bytes_for_parse_raises(good: Good) -> None:
    with pytest.raises(ValueError):
        good.cls.parse(io.BytesIO(b"\0" * (good.size - 1)))


def test_too_few_bytes_for_from_bytes_raises(good: Good) -> None:
    with pytest.raises(ValueError):
        good.cls.from_bytes(b"\0" * (good.size - 1))


def test_too_many_bytes_for_from_bytes_raises(good: Good) -> None:
    with pytest.raises(ValueError):
        good.cls.from_bytes(b"\0" * (good.size + 1))


def test_from_decimal(good: Good) -> None:
    assert good.cls(Decimal("117")) == 117


def test_from_float(good: Good) -> None:
    assert good.cls(4.0) == 4


def test_from_str(good: Good) -> None:
    assert good.cls("43") == 43


def test_from_bytes(good: Good) -> None:
    assert good.cls(b"125") == 125


def test_roundtrip(good: Good, valid_limit: int) -> None:
    fixed_width_value = good.cls(valid_limit)

    bytes_io = io.BytesIO()
    fixed_width_value.stream(bytes_io)

    bytes_io.seek(0)
    parsed_value = good.cls.parse(bytes_io)

    assert (type(parsed_value), parsed_value) == (good.cls, fixed_width_value)


@pytest.mark.uncollect_if(func=format_is_none)
def test_packing_invalid_limit_raises(good: Good, invalid_limit: int) -> None:
    assert good.format is not None
    with pytest.raises(struct.error):
        struct.pack(good.format, invalid_limit)


@pytest.mark.uncollect_if(func=format_is_none)
def test_packing_valid_limit_passes(good: Good, valid_limit: int) -> None:
    assert good.format is not None
    struct.pack(good.format, valid_limit)


@pytest.mark.uncollect_if(func=format_is_none)
def test_stream_to_bytes_matches_struct_pack(good: Good, valid_limit: int) -> None:
    assert good.format is not None
    bytes_io = io.BytesIO()

    value = good.cls(valid_limit)
    value.stream(bytes_io)

    streamed = bytes_io.getvalue()
    expected = struct.pack(good.format, valid_limit)

    assert streamed == expected


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
def test_parse_metadata_from_name_raises(bad_name: BadName) -> None:
    cls = type(bad_name.name, (StructStream,), {})
    with pytest.raises(ValueError, match=bad_name.error):
        parse_metadata_from_name(cls)


def test_parse_metadata_from_name_correct_size(good: Good) -> None:
    assert good.cls.SIZE == good.size


def test_parse_metadata_from_name_correct_bits(good: Good) -> None:
    assert good.cls.BITS == good.bits


def test_parse_metadata_from_name_correct_signedness(good: Good) -> None:
    assert good.cls.SIGNED == good.signed


def test_parse_metadata_from_name_correct_maximum(good: Good) -> None:
    assert good.cls.MAXIMUM_EXCLUSIVE == good.maximum_exclusive


def test_parse_metadata_from_name_correct_minimum(good: Good) -> None:
    assert good.cls.MINIMUM == good.minimum
