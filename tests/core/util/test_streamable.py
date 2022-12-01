from __future__ import annotations

import io
import re
from dataclasses import dataclass, field, fields
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, get_type_hints

import pytest
from blspy import G1Element
from clvm_tools import binutils
from typing_extensions import Literal, get_args

from chia.protocols.wallet_protocol import RespondRemovals
from chia.simulator.block_tools import BlockTools, test_constants
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes4, bytes32
from chia.types.full_block import FullBlock
from chia.types.weight_proof import SubEpochChallengeSegment
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import (
    ConversionError,
    DefinitionError,
    InvalidSizeError,
    InvalidTypeError,
    ParameterMissingError,
    Streamable,
    UnsupportedType,
    function_to_parse_one_item,
    function_to_stream_one_item,
    is_type_List,
    is_type_SpecificOptional,
    is_type_Tuple,
    parse_bool,
    parse_bytes,
    parse_list,
    parse_optional,
    parse_size_hints,
    parse_str,
    parse_tuple,
    parse_uint32,
    recurse_jsonify,
    streamable,
    streamable_from_dict,
    write_uint32,
)


def test_int_not_supported() -> None:
    with pytest.raises(UnsupportedType):

        @streamable
        @dataclass(frozen=True)
        class TestClassInt(Streamable):
            a: int


def test_float_not_supported() -> None:
    with pytest.raises(UnsupportedType):

        @streamable
        @dataclass(frozen=True)
        class TestClassFloat(Streamable):
            a: float


def test_dict_not_suppported() -> None:
    with pytest.raises(UnsupportedType):

        @streamable
        @dataclass(frozen=True)
        class TestClassDict(Streamable):
            a: Dict[str, str]


@dataclass(frozen=True)
class DataclassOnly:
    a: uint8


def test_pure_dataclass_not_supported() -> None:

    with pytest.raises(UnsupportedType):

        @streamable
        @dataclass(frozen=True)
        class TestClassDataclass(Streamable):
            a: DataclassOnly


class PlainClass:
    a: uint8


def test_plain_class_not_supported() -> None:

    with pytest.raises(UnsupportedType):

        @streamable
        @dataclass(frozen=True)
        class TestClassPlain(Streamable):
            a: PlainClass


@streamable
@dataclass(frozen=True)
class StreamableFromDict1(Streamable):
    a: uint8
    b: str
    c: G1Element


@streamable
@dataclass(frozen=True)
class StreamableFromDict2(Streamable):
    a: StreamableFromDict1
    b: StreamableFromDict1
    c: uint64


@streamable
@dataclass(frozen=True)
class ConvertTupleFailures(Streamable):
    a: Tuple[uint8, uint8]
    b: Tuple[uint8, Tuple[uint8, uint8]]


@pytest.mark.parametrize(
    "input_dict, error",
    [
        pytest.param({"a": (1,), "b": (1, (2, 2))}, InvalidSizeError, id="a: item missing"),
        pytest.param({"a": (1, 1, 1), "b": (1, (2, 2))}, InvalidSizeError, id="a: item too much"),
        pytest.param({"a": (1, 1), "b": (1, (2,))}, InvalidSizeError, id="b: item missing"),
        pytest.param({"a": (1, 1), "b": (1, (2, 2, 2))}, InvalidSizeError, id="b: item too much"),
        pytest.param({"a": "11", "b": (1, (2, 2))}, InvalidTypeError, id="a: invalid type list"),
        pytest.param({"a": 1, "b": (1, (2, 2))}, InvalidTypeError, id="a: invalid type int"),
        pytest.param({"a": "11", "b": (1, (2, 2))}, InvalidTypeError, id="a: invalid type str"),
        pytest.param({"a": (1, 1), "b": (1, "22")}, InvalidTypeError, id="b: invalid type list"),
        pytest.param({"a": (1, 1), "b": (1, 2)}, InvalidTypeError, id="b: invalid type int"),
        pytest.param({"a": (1, 1), "b": (1, "22")}, InvalidTypeError, id="b: invalid type str"),
    ],
)
def test_convert_tuple_failures(input_dict: Dict[str, Any], error: Any) -> None:

    with pytest.raises(error):
        streamable_from_dict(ConvertTupleFailures, input_dict)


@streamable
@dataclass(frozen=True)
class ConvertListFailures(Streamable):
    a: List[uint8]
    b: List[List[uint8]]


@pytest.mark.parametrize(
    "input_dict, error",
    [
        pytest.param({"a": [1, 1], "b": [1, [2, 2]]}, InvalidTypeError, id="a: invalid type list"),
        pytest.param({"a": 1, "b": [1, [2, 2]]}, InvalidTypeError, id="a: invalid type int"),
        pytest.param({"a": "11", "b": [1, [2, 2]]}, InvalidTypeError, id="a: invalid type str"),
        pytest.param({"a": [1, 1], "b": [1, [2, 2]]}, InvalidTypeError, id="b: invalid type list"),
        pytest.param({"a": [1, 1], "b": [1, 2]}, InvalidTypeError, id="b: invalid type int"),
        pytest.param({"a": [1, 1], "b": [1, "22"]}, InvalidTypeError, id="b: invalid type str"),
    ],
)
def test_convert_list_failures(input_dict: Dict[str, Any], error: Any) -> None:

    with pytest.raises(error):
        streamable_from_dict(ConvertListFailures, input_dict)


@streamable
@dataclass(frozen=True)
class ConvertByteTypeFailures(Streamable):
    a: bytes4
    b: bytes


@pytest.mark.parametrize(
    "input_dict, error",
    [
        pytest.param({"a": 0, "b": bytes(0)}, InvalidTypeError, id="a: no string and no bytes"),
        pytest.param({"a": [], "b": bytes(0)}, InvalidTypeError, id="a: no string and no bytes"),
        pytest.param({"a": {}, "b": bytes(0)}, InvalidTypeError, id="a: no string and no bytes"),
        pytest.param({"a": "invalid", "b": bytes(0)}, ConversionError, id="a: invalid hex string"),
        pytest.param({"a": "000000", "b": bytes(0)}, ConversionError, id="a: hex string too short"),
        pytest.param({"a": "0000000000", "b": bytes(0)}, ConversionError, id="a: hex string too long"),
        pytest.param({"a": b"\00\00\00", "b": bytes(0)}, ConversionError, id="a: bytes too short"),
        pytest.param({"a": b"\00\00\00\00\00", "b": bytes(0)}, ConversionError, id="a: bytes too long"),
        pytest.param({"a": "00000000", "b": 0}, InvalidTypeError, id="b: no string and no bytes"),
        pytest.param({"a": "00000000", "b": []}, InvalidTypeError, id="b: no string and no bytes"),
        pytest.param({"a": "00000000", "b": {}}, InvalidTypeError, id="b: no string and no bytes"),
        pytest.param({"a": "00000000", "b": "invalid"}, ConversionError, id="b: invalid hex string"),
    ],
)
def test_convert_byte_type_failures(input_dict: Dict[str, Any], error: Any) -> None:

    with pytest.raises(error):
        streamable_from_dict(ConvertByteTypeFailures, input_dict)


@streamable
@dataclass(frozen=True)
class ConvertUnhashableTypeFailures(Streamable):
    a: G1Element


@pytest.mark.parametrize(
    "input_dict, error",
    [
        pytest.param({"a": 0}, InvalidTypeError, id="a: no string and no bytes"),
        pytest.param({"a": []}, InvalidTypeError, id="a: no string and no bytes"),
        pytest.param({"a": {}}, InvalidTypeError, id="a: no string and no bytes"),
        pytest.param({"a": "invalid"}, ConversionError, id="a: invalid hex string"),
        pytest.param({"a": "00" * (G1Element.SIZE - 1)}, ConversionError, id="a: hex string too short"),
        pytest.param({"a": "00" * (G1Element.SIZE + 1)}, ConversionError, id="a: hex string too long"),
        pytest.param({"a": b"\00" * (G1Element.SIZE - 1)}, ConversionError, id="a: bytes too short"),
        pytest.param({"a": b"\00" * (G1Element.SIZE + 1)}, ConversionError, id="a: bytes too long"),
        pytest.param({"a": b"\00" * G1Element.SIZE}, ConversionError, id="a: invalid g1 element"),
    ],
)
def test_convert_unhashable_type_failures(input_dict: Dict[str, Any], error: Any) -> None:

    with pytest.raises(error):
        streamable_from_dict(ConvertUnhashableTypeFailures, input_dict)


class NoStrClass:
    def __str__(self) -> str:
        raise RuntimeError("No string")


@streamable
@dataclass(frozen=True)
class ConvertPrimitiveFailures(Streamable):
    a: uint8
    b: uint8
    c: str


@pytest.mark.parametrize(
    "input_dict, error",
    [
        pytest.param({"a": "a", "b": uint8(1), "c": "2"}, ConversionError, id="a: invalid value"),
        pytest.param({"a": 0, "b": [], "c": "2"}, ConversionError, id="b: invalid value"),
        pytest.param({"a": 0, "b": uint8(1), "c": NoStrClass()}, ConversionError, id="c: invalid value"),
    ],
)
def test_convert_primitive_failures(input_dict: Dict[str, Any], error: Any) -> None:

    with pytest.raises(error):
        streamable_from_dict(ConvertPrimitiveFailures, input_dict)


@pytest.mark.parametrize(
    "test_class, input_dict, error, error_message",
    [
        [
            StreamableFromDict1,
            {"a": "asdf", "b": "2", "c": G1Element()},
            ConversionError,
            "Failed to convert 'asdf' from type str to uint8: ValueError: invalid literal "
            "for int() with base 10: 'asdf'",
        ],
        [StreamableFromDict1, {"a": 1, "b": "2"}, ParameterMissingError, "1 field missing for StreamableFromDict1: c"],
        [StreamableFromDict1, {"a": 1}, ParameterMissingError, "2 fields missing for StreamableFromDict1: b, c"],
        [StreamableFromDict1, {}, ParameterMissingError, "3 fields missing for StreamableFromDict1: a, b, c"],
        [
            StreamableFromDict1,
            {"a": 1, "b": "2", "c": "asd"},
            ConversionError,
            "Failed to convert 'asd' from type str to bytes: ValueError: non-hexadecimal number found in fromhex() arg "
            "at position 1",
        ],
        [
            StreamableFromDict1,
            {"a": 1, "b": "2", "c": "00" * G1Element.SIZE},
            ConversionError,
            f"Failed to convert {bytes.fromhex('00' * G1Element.SIZE)!r} from type bytes to G1Element: ValueError: "
            "Given G1 non-infinity element must start with 0b10",
        ],
        [
            StreamableFromDict1,
            {"a": [], "b": "2", "c": G1Element()},
            ConversionError,
            "Failed to convert [] from type list to uint8: TypeError: int() argument",
        ],
        [
            StreamableFromDict1,
            {"a": {}, "b": "2", "c": G1Element()},
            ConversionError,
            "Failed to convert {} from type dict to uint8: TypeError: int() argument",
        ],
        [
            StreamableFromDict2,
            {"a": "asdf", "b": 12345, "c": 12345},
            InvalidTypeError,
            "Invalid type: Expected dict, Actual: str",
        ],
        [
            StreamableFromDict2,
            {"a": 12345, "b": {"a": 1, "b": "2"}, "c": 12345},
            InvalidTypeError,
            "Invalid type: Expected dict, Actual: int",
        ],
        [
            StreamableFromDict2,
            {"a": {"a": 1, "b": "2", "c": G1Element()}, "b": {"a": 1, "b": "2"}},
            ParameterMissingError,
            "1 field missing for StreamableFromDict1: c",
        ],
        [
            StreamableFromDict2,
            {"a": {"a": 1, "b": "2"}, "b": {"a": 1, "b": "2"}, "c": 12345},
            ParameterMissingError,
            "1 field missing for StreamableFromDict1: c",
        ],
    ],
)
def test_streamable_from_dict_failures(
    test_class: Type[Streamable], input_dict: Dict[str, Any], error: Any, error_message: str
) -> None:

    with pytest.raises(error, match=re.escape(error_message)):
        streamable_from_dict(test_class, input_dict)


@streamable
@dataclass(frozen=True)
class TestFromJsonDictDefaultValues(Streamable):
    a: uint64 = uint64(1)
    b: str = "default"
    c: List[uint64] = field(default_factory=list)


@pytest.mark.parametrize(
    "input_dict, output_dict",
    [
        [{}, {"a": 1, "b": "default", "c": []}],
        [{"a": 2}, {"a": 2, "b": "default", "c": []}],
        [{"b": "not_default"}, {"a": 1, "b": "not_default", "c": []}],
        [{"c": [1, 2]}, {"a": 1, "b": "default", "c": [1, 2]}],
        [{"a": 2, "b": "not_default", "c": [1, 2]}, {"a": 2, "b": "not_default", "c": [1, 2]}],
    ],
)
def test_from_json_dict_default_values(input_dict: Dict[str, object], output_dict: Dict[str, object]) -> None:
    assert str(TestFromJsonDictDefaultValues.from_json_dict(input_dict).to_json_dict()) == str(output_dict)


def test_basic_list() -> None:
    a = [1, 2, 3]
    assert is_type_List(type(a))
    assert is_type_List(List)
    assert is_type_List(List[int])
    assert is_type_List(List[uint8])
    assert is_type_List(list)
    assert not is_type_List(type(Tuple))
    assert not is_type_List(tuple)
    assert not is_type_List(dict)


def test_not_lists() -> None:
    assert not is_type_List(Dict)


def test_basic_optional() -> None:
    assert is_type_SpecificOptional(Optional[int])
    assert is_type_SpecificOptional(Optional[Optional[int]])
    assert not is_type_SpecificOptional(List[int])


@streamable
@dataclass(frozen=True)
class PostInitTestClassBasic(Streamable):
    a: uint8
    b: str
    c: bytes
    d: bytes32
    e: G1Element


@streamable
@dataclass(frozen=True)
class PostInitTestClassBad(Streamable):
    a: uint8
    b = 0


@streamable
@dataclass(frozen=True)
class PostInitTestClassOptional(Streamable):
    a: Optional[uint8]
    b: Optional[uint8]
    c: Optional[Optional[uint8]]
    d: Optional[Optional[uint8]]


@streamable
@dataclass(frozen=True)
class PostInitTestClassList(Streamable):
    a: List[uint8]
    b: List[List[G1Element]]


@streamable
@dataclass(frozen=True)
class PostInitTestClassTuple(Streamable):
    a: Tuple[uint8, str]
    b: Tuple[Tuple[uint8, str], bytes32]


@pytest.mark.parametrize(
    "test_class, args",
    [
        (PostInitTestClassBasic, (24, 99, 300, b"\12" * 32, bytes(G1Element()))),
        (PostInitTestClassBasic, (24, "test", b"\00\01", b"\x1a" * 32, G1Element())),
        (PostInitTestClassBad, (25,)),
        (PostInitTestClassList, ([1, 2, 3], [[G1Element(), bytes(G1Element())], [bytes(G1Element())]])),
        (PostInitTestClassTuple, ((1, "test"), ((200, "test_2"), b"\xba" * 32))),
        (PostInitTestClassOptional, (12, None, 13, None)),
    ],
)
def test_post_init_valid(test_class: Type[Any], args: Tuple[Any, ...]) -> None:
    def validate_item_type(type_in: Type[Any], item: object) -> bool:
        if is_type_SpecificOptional(type_in):
            return item is None or validate_item_type(get_args(type_in)[0], item)
        if is_type_Tuple(type_in):
            assert type(item) == tuple
            types = get_args(type_in)
            return all(validate_item_type(tuple_type, tuple_item) for tuple_type, tuple_item in zip(types, item))
        if is_type_List(type_in):
            list_type = get_args(type_in)[0]
            assert type(item) == list
            return all(validate_item_type(list_type, list_item) for list_item in item)
        return isinstance(item, type_in)

    test_object = test_class(*args)
    hints = get_type_hints(test_class)
    test_fields = {field.name: hints.get(field.name, field.type) for field in fields(test_class)}
    for field_name, field_type in test_fields.items():
        assert validate_item_type(field_type, test_object.__dict__[field_name])


@pytest.mark.parametrize(
    "test_class, args, expected_exception",
    [
        (PostInitTestClassBasic, (None, "test", b"\00\01", b"\12" * 32, G1Element()), TypeError),
        (PostInitTestClassBasic, (1, "test", None, b"\12" * 32, G1Element()), AttributeError),
        (PostInitTestClassBasic, (1, "test", b"\00\01", b"\12" * 31, G1Element()), ValueError),
        (PostInitTestClassBasic, (1, "test", b"\00\01", b"\12" * 32, b"\12" * 10), ValueError),
        (PostInitTestClassBad, (1, 2), TypeError),
        (PostInitTestClassList, ({"1": 1}, [[uint8(200), uint8(25)], [uint8(25)]]), InvalidTypeError),
        (PostInitTestClassList, (("1", 1), [[uint8(200), uint8(25)], [uint8(25)]]), InvalidTypeError),
        (PostInitTestClassList, ([1, 2, 3], [uint8(200), uint8(25)]), InvalidTypeError),
        (PostInitTestClassTuple, ((1,), ((200, "test_2"), b"\xba" * 32)), InvalidSizeError),
        (PostInitTestClassTuple, ((1, "test", 1), ((200, "test_2"), b"\xba" * 32)), InvalidSizeError),
        (PostInitTestClassTuple, ((1, "test"), ({"a": 2}, b"\xba" * 32)), InvalidTypeError),
        (PostInitTestClassTuple, ((1, "test"), (G1Element(), b"\xba" * 32)), InvalidTypeError),
        (PostInitTestClassOptional, ([], None, None, None), ValueError),
    ],
)
def test_post_init_failures(test_class: Type[Any], args: Tuple[Any, ...], expected_exception: Type[Exception]) -> None:
    with pytest.raises(expected_exception):
        test_class(*args)


def test_basic() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClass(Streamable):
        a: uint32
        b: uint32
        c: List[uint32]
        d: List[List[uint32]]
        e: Optional[uint32]
        f: Optional[uint32]
        g: Tuple[uint32, str, bytes]

    # we want to test invalid here, hence the ignore.
    a = TestClass(24, 352, [1, 2, 4], [[1, 2, 3], [3, 4]], 728, None, (383, "hello", b"goodbye"))  # type: ignore[arg-type,list-item] # noqa: E501

    b: bytes = bytes(a)
    assert a == TestClass.from_bytes(b)


def test_variable_size() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClass2(Streamable):
        a: uint32
        b: uint32
        c: bytes

    a = TestClass2(uint32(1), uint32(2), b"3")
    bytes(a)

    with pytest.raises(UnsupportedType):

        @streamable
        @dataclass(frozen=True)
        class TestClass3(Streamable):
            a: int


def test_json(bt: BlockTools) -> None:
    block = bt.create_genesis_block(test_constants, bytes32([0] * 32), uint64(0))
    dict_block = block.to_json_dict()
    assert FullBlock.from_json_dict(dict_block) == block


@streamable
@dataclass(frozen=True)
class OptionalTestClass(Streamable):
    a: Optional[str]
    b: Optional[bool]
    c: Optional[List[Optional[str]]]


@pytest.mark.parametrize(
    "a, b, c",
    [
        ("", True, ["1"]),
        ("1", False, ["1"]),
        ("1", True, []),
        ("1", True, [""]),
        ("1", True, ["1"]),
        (None, None, None),
    ],
)
def test_optional_json(a: Optional[str], b: Optional[bool], c: Optional[List[Optional[str]]]) -> None:
    obj: OptionalTestClass = OptionalTestClass.from_json_dict({"a": a, "b": b, "c": c})
    assert obj.a == a
    assert obj.b == b
    assert obj.c == c


@streamable
@dataclass(frozen=True)
class TestClassRecursive1(Streamable):
    a: List[uint32]


@streamable
@dataclass(frozen=True)
class TestClassRecursive2(Streamable):
    a: uint32
    b: List[Optional[List[TestClassRecursive1]]]
    c: bytes32


def test_recursive_json() -> None:
    tc1_a = TestClassRecursive1([uint32(1), uint32(2)])
    tc1_b = TestClassRecursive1([uint32(4), uint32(5)])
    tc1_c = TestClassRecursive1([uint32(7), uint32(8)])

    tc2 = TestClassRecursive2(uint32(5), [[tc1_a], [tc1_b, tc1_c], None], bytes32(bytes([1] * 32)))
    assert TestClassRecursive2.from_json_dict(tc2.to_json_dict()) == tc2


def test_recursive_types() -> None:
    coin: Optional[Coin] = None
    l1 = [(bytes32([2] * 32), coin)]
    rr = RespondRemovals(uint32(1), bytes32([1] * 32), l1, None)
    RespondRemovals(rr.height, rr.header_hash, rr.coins, rr.proofs)


def test_ambiguous_deserialization_optionals() -> None:
    with pytest.raises(AssertionError):
        SubEpochChallengeSegment.from_bytes(b"\x00\x00\x00\x03\xff\xff\xff\xff")

    @streamable
    @dataclass(frozen=True)
    class TestClassOptional(Streamable):
        a: Optional[uint8]

    # Does not have the required elements
    with pytest.raises(AssertionError):
        TestClassOptional.from_bytes(bytes([]))

    TestClassOptional.from_bytes(bytes([0]))
    TestClassOptional.from_bytes(bytes([1, 2]))


def test_ambiguous_deserialization_int() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClassUint(Streamable):
        a: uint32

    # Does not have the required uint size
    with pytest.raises(ValueError):
        TestClassUint.from_bytes(b"\x00\x00")


def test_ambiguous_deserialization_list() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClassList(Streamable):
        a: List[uint8]

    # Does not have the required elements
    with pytest.raises(ValueError):
        TestClassList.from_bytes(bytes([0, 0, 100, 24]))


def test_ambiguous_deserialization_tuple() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClassTuple(Streamable):
        a: Tuple[uint8, str]

    # Does not have the required elements
    with pytest.raises(AssertionError):
        TestClassTuple.from_bytes(bytes([0, 0, 100, 24]))


def test_ambiguous_deserialization_str() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClassStr(Streamable):
        a: str

    # Does not have the required str size
    with pytest.raises(AssertionError):
        TestClassStr.from_bytes(bytes([0, 0, 100, 24, 52]))


def test_ambiguous_deserialization_bytes() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClassBytes(Streamable):
        a: bytes

    # Does not have the required str size
    with pytest.raises(AssertionError):
        TestClassBytes.from_bytes(bytes([0, 0, 100, 24, 52]))

    with pytest.raises(AssertionError):
        TestClassBytes.from_bytes(bytes([0, 0, 0, 1]))

    TestClassBytes.from_bytes(bytes([0, 0, 0, 1, 52]))
    TestClassBytes.from_bytes(bytes([0, 0, 0, 2, 52, 21]))


def test_ambiguous_deserialization_bool() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClassBool(Streamable):
        a: bool

    # Does not have the required str size
    with pytest.raises(AssertionError):
        TestClassBool.from_bytes(bytes([]))

    TestClassBool.from_bytes(bytes([0]))
    TestClassBool.from_bytes(bytes([1]))


def test_ambiguous_deserialization_program() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClassProgram(Streamable):
        a: Program

    program = Program.to(binutils.assemble("()"))  # type: ignore[no-untyped-call]  # TODO, add typing in clvm_tools

    TestClassProgram.from_bytes(bytes(program))

    with pytest.raises(AssertionError):
        TestClassProgram.from_bytes(bytes(program) + b"9")


def test_streamable_empty() -> None:
    @streamable
    @dataclass(frozen=True)
    class A(Streamable):
        pass

    assert A.from_bytes(bytes(A())) == A()


def test_parse_bool() -> None:
    assert not parse_bool(io.BytesIO(b"\x00"))
    assert parse_bool(io.BytesIO(b"\x01"))

    # EOF
    with pytest.raises(AssertionError):
        parse_bool(io.BytesIO(b""))

    with pytest.raises(ValueError):
        parse_bool(io.BytesIO(b"\xff"))

    with pytest.raises(ValueError):
        parse_bool(io.BytesIO(b"\x02"))


def test_uint32() -> None:
    assert parse_uint32(io.BytesIO(b"\x00\x00\x00\x00")) == 0
    assert parse_uint32(io.BytesIO(b"\x00\x00\x00\x01")) == 1
    assert parse_uint32(io.BytesIO(b"\x00\x00\x00\x01"), "little") == 16777216
    assert parse_uint32(io.BytesIO(b"\x01\x00\x00\x00")) == 16777216
    assert parse_uint32(io.BytesIO(b"\x01\x00\x00\x00"), "little") == 1
    assert parse_uint32(io.BytesIO(b"\xff\xff\xff\xff"), "little") == 4294967295

    def test_write(value: int, byteorder: Literal["little", "big"]) -> None:
        f = io.BytesIO()
        write_uint32(f, uint32(value), byteorder)
        f.seek(0)
        assert parse_uint32(f, byteorder) == value

    test_write(1, "big")
    test_write(1, "little")
    test_write(4294967295, "big")
    test_write(4294967295, "little")

    with pytest.raises(AssertionError):
        parse_uint32(io.BytesIO(b""))
    with pytest.raises(AssertionError):
        parse_uint32(io.BytesIO(b"\x00"))
    with pytest.raises(AssertionError):
        parse_uint32(io.BytesIO(b"\x00\x00"))
    with pytest.raises(AssertionError):
        parse_uint32(io.BytesIO(b"\x00\x00\x00"))


def test_parse_optional() -> None:
    assert parse_optional(io.BytesIO(b"\x00"), parse_bool) is None
    assert parse_optional(io.BytesIO(b"\x01\x01"), parse_bool)
    assert not parse_optional(io.BytesIO(b"\x01\x00"), parse_bool)

    # EOF
    with pytest.raises(AssertionError):
        parse_optional(io.BytesIO(b"\x01"), parse_bool)

    # optional must be 0 or 1
    with pytest.raises(ValueError):
        parse_optional(io.BytesIO(b"\x02\x00"), parse_bool)

    with pytest.raises(ValueError):
        parse_optional(io.BytesIO(b"\xff\x00"), parse_bool)


def test_parse_bytes() -> None:

    assert parse_bytes(io.BytesIO(b"\x00\x00\x00\x00")) == b""
    assert parse_bytes(io.BytesIO(b"\x00\x00\x00\x01\xff")) == b"\xff"

    # 512 bytes
    assert parse_bytes(io.BytesIO(b"\x00\x00\x02\x00" + b"a" * 512)) == b"a" * 512

    # 255 bytes
    assert parse_bytes(io.BytesIO(b"\x00\x00\x00\xff" + b"b" * 255)) == b"b" * 255

    # EOF
    with pytest.raises(AssertionError):
        parse_bytes(io.BytesIO(b"\x00\x00\x00\xff\x01\x02\x03"))

    with pytest.raises(AssertionError):
        parse_bytes(io.BytesIO(b"\xff\xff\xff\xff"))

    with pytest.raises(AssertionError):
        parse_bytes(io.BytesIO(b"\xff\xff\xff\xff" + b"a" * 512))

    # EOF off by one
    with pytest.raises(AssertionError):
        parse_bytes(io.BytesIO(b"\x00\x00\x02\x01" + b"a" * 512))


def test_parse_list() -> None:

    assert parse_list(io.BytesIO(b"\x00\x00\x00\x00"), parse_bool) == []
    assert parse_list(io.BytesIO(b"\x00\x00\x00\x01\x01"), parse_bool) == [True]
    assert parse_list(io.BytesIO(b"\x00\x00\x00\x03\x01\x00\x01"), parse_bool) == [True, False, True]

    # EOF
    with pytest.raises(AssertionError):
        parse_list(io.BytesIO(b"\x00\x00\x00\x01"), parse_bool)

    with pytest.raises(AssertionError):
        parse_list(io.BytesIO(b"\x00\x00\x00\xff\x00\x00"), parse_bool)

    with pytest.raises(AssertionError):
        parse_list(io.BytesIO(b"\xff\xff\xff\xff\x00\x00"), parse_bool)

    # failure to parser internal type
    with pytest.raises(ValueError):
        parse_list(io.BytesIO(b"\x00\x00\x00\x01\x02"), parse_bool)


def test_parse_tuple() -> None:

    assert parse_tuple(io.BytesIO(b""), []) == ()
    assert parse_tuple(io.BytesIO(b"\x00\x00"), [parse_bool, parse_bool]) == (False, False)
    assert parse_tuple(io.BytesIO(b"\x00\x01"), [parse_bool, parse_bool]) == (False, True)

    # error in parsing internal type
    with pytest.raises(ValueError):
        parse_tuple(io.BytesIO(b"\x00\x02"), [parse_bool, parse_bool])

    # EOF
    with pytest.raises(AssertionError):
        parse_tuple(io.BytesIO(b"\x00"), [parse_bool, parse_bool])


class TestFromBytes:
    b: bytes

    @classmethod
    def from_bytes(cls, b: bytes) -> TestFromBytes:
        ret = TestFromBytes()
        ret.b = b
        return ret


class FailFromBytes:
    @classmethod
    def from_bytes(cls, b: bytes) -> FailFromBytes:
        raise ValueError()


def test_parse_size_hints() -> None:
    assert parse_size_hints(io.BytesIO(b"1337"), TestFromBytes, 4, False).b == b"1337"

    # EOF
    with pytest.raises(AssertionError):
        parse_size_hints(io.BytesIO(b"133"), TestFromBytes, 4, False)

    # error in underlying type
    with pytest.raises(ValueError):
        parse_size_hints(io.BytesIO(b"1337"), FailFromBytes, 4, False)


def test_parse_str() -> None:

    assert parse_str(io.BytesIO(b"\x00\x00\x00\x00")) == ""
    assert parse_str(io.BytesIO(b"\x00\x00\x00\x01a")) == "a"

    # 512 bytes
    assert parse_str(io.BytesIO(b"\x00\x00\x02\x00" + b"a" * 512)) == "a" * 512

    # 255 bytes
    assert parse_str(io.BytesIO(b"\x00\x00\x00\xff" + b"b" * 255)) == "b" * 255

    # EOF
    with pytest.raises(AssertionError):
        parse_str(io.BytesIO(b"\x00\x00\x00\xff\x01\x02\x03"))

    with pytest.raises(AssertionError):
        parse_str(io.BytesIO(b"\xff\xff\xff\xff"))

    with pytest.raises(AssertionError):
        parse_str(io.BytesIO(b"\xff\xff\xff\xff" + b"a" * 512))

    # EOF off by one
    with pytest.raises(AssertionError):
        parse_str(io.BytesIO(b"\x00\x00\x02\x01" + b"a" * 512))


def test_wrong_decorator_order() -> None:

    with pytest.raises(DefinitionError):

        @dataclass(frozen=True)
        @streamable
        class WrongDecoratorOrder(Streamable):
            pass


def test_dataclass_not_frozen() -> None:

    with pytest.raises(DefinitionError):

        @streamable
        @dataclass(frozen=False)
        class DataclassNotFrozen(Streamable):
            pass


def test_dataclass_missing() -> None:

    with pytest.raises(DefinitionError):

        @streamable
        class DataclassMissing(Streamable):
            pass


def test_streamable_inheritance_missing() -> None:

    with pytest.raises(DefinitionError):
        # we want to test invalid here, hence the ignore.
        @streamable
        @dataclass(frozen=True)
        class StreamableInheritanceMissing:  # type: ignore[type-var]
            pass


@pytest.mark.parametrize(
    "method, input_type",
    [
        (function_to_parse_one_item, float),
        (function_to_parse_one_item, int),
        (function_to_parse_one_item, dict),
        (function_to_stream_one_item, float),
        (function_to_stream_one_item, int),
        (function_to_stream_one_item, dict),
        (recurse_jsonify, 1.0),
        (recurse_jsonify, recurse_jsonify),
    ],
)
def test_unsupported_types(method: Callable[[object], object], input_type: object) -> None:
    with pytest.raises(UnsupportedType):
        method(input_type)
