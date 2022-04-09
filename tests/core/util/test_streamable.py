from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import io
import pytest

from clvm_tools import binutils
from pytest import raises

from chia.protocols.wallet_protocol import RespondRemovals
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.weight_proof import SubEpochChallengeSegment
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import (
    DefinitionError,
    Streamable,
    streamable,
    parse_bool,
    parse_uint32,
    write_uint32,
    parse_optional,
    parse_bytes,
    parse_list,
    parse_tuple,
    parse_size_hints,
    parse_str,
    is_type_List,
    is_type_SpecificOptional,
)
from tests.setup_nodes import test_constants


def test_int_not_supported() -> None:
    with raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClassInt(Streamable):
            a: int


def test_float_not_supported() -> None:
    with raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClassFloat(Streamable):
            a: float


def test_dict_not_suppported() -> None:
    with raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClassDict(Streamable):
            a: Dict[str, str]


def test_pure_dataclass_not_supported() -> None:
    @dataclass(frozen=True)
    class DataClassOnly:
        a: uint8

    with raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClassDataclass(Streamable):
            a: DataClassOnly


def test_plain_class_not_supported() -> None:
    class PlainClass:
        a: uint8

    with raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClassPlain(Streamable):
            a: PlainClass


def test_basic_list():
    a = [1, 2, 3]
    assert is_type_List(type(a))
    assert is_type_List(List)
    assert is_type_List(List[int])
    assert is_type_List(List[uint8])
    assert is_type_List(list)
    assert not is_type_List(Tuple)
    assert not is_type_List(tuple)
    assert not is_type_List(dict)


def test_not_lists():
    assert not is_type_List(Dict)


def test_basic_optional():
    assert is_type_SpecificOptional(Optional[int])
    assert is_type_SpecificOptional(Optional[Optional[int]])
    assert not is_type_SpecificOptional(List[int])


def test_StrictDataClass():
    @streamable
    @dataclass(frozen=True)
    class TestClass1(Streamable):
        a: uint8
        b: str

    good: TestClass1 = TestClass1(24, "!@12")
    assert TestClass1.__name__ == "TestClass1"
    assert good
    assert good.a == 24
    assert good.b == "!@12"
    good2 = TestClass1(52, bytes([1, 2, 3]))
    assert good2.b == str(bytes([1, 2, 3]))


def test_StrictDataClassBad():
    @streamable
    @dataclass(frozen=True)
    class TestClass2(Streamable):
        a: uint8
        b = 0

    assert TestClass2(25)

    with raises(TypeError):
        TestClass2(1, 2)  # pylint: disable=too-many-function-args


def test_StrictDataClassLists():
    @streamable
    @dataclass(frozen=True)
    class TestClass(Streamable):
        a: List[uint8]
        b: List[List[uint8]]

    assert TestClass([1, 2, 3], [[uint8(200), uint8(25)], [uint8(25)]])

    with raises(ValueError):
        TestClass({"1": 1}, [[uint8(200), uint8(25)], [uint8(25)]])

    with raises(ValueError):
        TestClass([1, 2, 3], [uint8(200), uint8(25)])


def test_StrictDataClassOptional():
    @streamable
    @dataclass(frozen=True)
    class TestClass(Streamable):
        a: Optional[uint8]
        b: Optional[uint8]
        c: Optional[Optional[uint8]]
        d: Optional[Optional[uint8]]

    good = TestClass(12, None, 13, None)
    assert good


def test_basic():
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

    a = TestClass(24, 352, [1, 2, 4], [[1, 2, 3], [3, 4]], 728, None, (383, "hello", b"goodbye"))

    b: bytes = bytes(a)
    assert a == TestClass.from_bytes(b)


def test_variable_size():
    @streamable
    @dataclass(frozen=True)
    class TestClass2(Streamable):
        a: uint32
        b: uint32
        c: bytes

    a = TestClass2(uint32(1), uint32(2), b"3")
    bytes(a)

    with raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClass3(Streamable):
            a: int


def test_json(bt):
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
def test_optional_json(a: Optional[str], b: Optional[bool], c: Optional[List[Optional[str]]]):
    obj: OptionalTestClass = OptionalTestClass.from_json_dict({"a": a, "b": b, "c": c})
    assert obj.a == a
    assert obj.b == b
    assert obj.c == c


def test_recursive_json():
    @streamable
    @dataclass(frozen=True)
    class TestClass1(Streamable):
        a: List[uint32]

    @streamable
    @dataclass(frozen=True)
    class TestClass2(Streamable):
        a: uint32
        b: List[Optional[List[TestClass1]]]
        c: bytes32

    tc1_a = TestClass1([uint32(1), uint32(2)])
    tc1_b = TestClass1([uint32(4), uint32(5)])
    tc1_c = TestClass1([uint32(7), uint32(8)])

    tc2 = TestClass2(uint32(5), [[tc1_a], [tc1_b, tc1_c], None], bytes32(bytes([1] * 32)))
    assert TestClass2.from_json_dict(tc2.to_json_dict()) == tc2


def test_recursive_types():
    coin: Optional[Coin] = None
    l1 = [(bytes32([2] * 32), coin)]
    rr = RespondRemovals(uint32(1), bytes32([1] * 32), l1, None)
    RespondRemovals(rr.height, rr.header_hash, rr.coins, rr.proofs)


def test_ambiguous_deserialization_optionals():
    with raises(AssertionError):
        SubEpochChallengeSegment.from_bytes(b"\x00\x00\x00\x03\xff\xff\xff\xff")

    @streamable
    @dataclass(frozen=True)
    class TestClassOptional(Streamable):
        a: Optional[uint8]

    # Does not have the required elements
    with raises(AssertionError):
        TestClassOptional.from_bytes(bytes([]))

    TestClassOptional.from_bytes(bytes([0]))
    TestClassOptional.from_bytes(bytes([1, 2]))


def test_ambiguous_deserialization_int():
    @streamable
    @dataclass(frozen=True)
    class TestClassUint(Streamable):
        a: uint32

    # Does not have the required uint size
    with raises(AssertionError):
        TestClassUint.from_bytes(b"\x00\x00")


def test_ambiguous_deserialization_list():
    @streamable
    @dataclass(frozen=True)
    class TestClassList(Streamable):
        a: List[uint8]

    # Does not have the required elements
    with raises(AssertionError):
        TestClassList.from_bytes(bytes([0, 0, 100, 24]))


def test_ambiguous_deserialization_tuple():
    @streamable
    @dataclass(frozen=True)
    class TestClassTuple(Streamable):
        a: Tuple[uint8, str]

    # Does not have the required elements
    with raises(AssertionError):
        TestClassTuple.from_bytes(bytes([0, 0, 100, 24]))


def test_ambiguous_deserialization_str():
    @streamable
    @dataclass(frozen=True)
    class TestClassStr(Streamable):
        a: str

    # Does not have the required str size
    with raises(AssertionError):
        TestClassStr.from_bytes(bytes([0, 0, 100, 24, 52]))


def test_ambiguous_deserialization_bytes():
    @streamable
    @dataclass(frozen=True)
    class TestClassBytes(Streamable):
        a: bytes

    # Does not have the required str size
    with raises(AssertionError):
        TestClassBytes.from_bytes(bytes([0, 0, 100, 24, 52]))

    with raises(AssertionError):
        TestClassBytes.from_bytes(bytes([0, 0, 0, 1]))

    TestClassBytes.from_bytes(bytes([0, 0, 0, 1, 52]))
    TestClassBytes.from_bytes(bytes([0, 0, 0, 2, 52, 21]))


def test_ambiguous_deserialization_bool():
    @streamable
    @dataclass(frozen=True)
    class TestClassBool(Streamable):
        a: bool

    # Does not have the required str size
    with raises(AssertionError):
        TestClassBool.from_bytes(bytes([]))

    TestClassBool.from_bytes(bytes([0]))
    TestClassBool.from_bytes(bytes([1]))


def test_ambiguous_deserialization_program():
    @streamable
    @dataclass(frozen=True)
    class TestClassProgram(Streamable):
        a: Program

    program = Program.to(binutils.assemble("()"))

    TestClassProgram.from_bytes(bytes(program))

    with raises(AssertionError):
        TestClassProgram.from_bytes(bytes(program) + b"9")


def test_streamable_empty():
    @streamable
    @dataclass(frozen=True)
    class A(Streamable):
        pass

    assert A.from_bytes(bytes(A())) == A()


def test_parse_bool():
    assert not parse_bool(io.BytesIO(b"\x00"))
    assert parse_bool(io.BytesIO(b"\x01"))

    # EOF
    with raises(AssertionError):
        parse_bool(io.BytesIO(b""))

    with raises(ValueError):
        parse_bool(io.BytesIO(b"\xff"))

    with raises(ValueError):
        parse_bool(io.BytesIO(b"\x02"))


def test_uint32():
    assert parse_uint32(io.BytesIO(b"\x00\x00\x00\x00")) == 0
    assert parse_uint32(io.BytesIO(b"\x00\x00\x00\x01")) == 1
    assert parse_uint32(io.BytesIO(b"\x00\x00\x00\x01"), "little") == 16777216
    assert parse_uint32(io.BytesIO(b"\x01\x00\x00\x00")) == 16777216
    assert parse_uint32(io.BytesIO(b"\x01\x00\x00\x00"), "little") == 1
    assert parse_uint32(io.BytesIO(b"\xff\xff\xff\xff"), "little") == 4294967295

    def test_write(value, byteorder):
        f = io.BytesIO()
        write_uint32(f, uint32(value), byteorder)
        f.seek(0)
        assert parse_uint32(f, byteorder) == value

    test_write(1, "big")
    test_write(1, "little")
    test_write(4294967295, "big")
    test_write(4294967295, "little")

    with raises(AssertionError):
        parse_uint32(io.BytesIO(b""))
    with raises(AssertionError):
        parse_uint32(io.BytesIO(b"\x00"))
    with raises(AssertionError):
        parse_uint32(io.BytesIO(b"\x00\x00"))
    with raises(AssertionError):
        parse_uint32(io.BytesIO(b"\x00\x00\x00"))


def test_parse_optional():
    assert parse_optional(io.BytesIO(b"\x00"), parse_bool) is None
    assert parse_optional(io.BytesIO(b"\x01\x01"), parse_bool)
    assert not parse_optional(io.BytesIO(b"\x01\x00"), parse_bool)

    # EOF
    with raises(AssertionError):
        parse_optional(io.BytesIO(b"\x01"), parse_bool)

    # optional must be 0 or 1
    with raises(ValueError):
        parse_optional(io.BytesIO(b"\x02\x00"), parse_bool)

    with raises(ValueError):
        parse_optional(io.BytesIO(b"\xff\x00"), parse_bool)


def test_parse_bytes():

    assert parse_bytes(io.BytesIO(b"\x00\x00\x00\x00")) == b""
    assert parse_bytes(io.BytesIO(b"\x00\x00\x00\x01\xff")) == b"\xff"

    # 512 bytes
    assert parse_bytes(io.BytesIO(b"\x00\x00\x02\x00" + b"a" * 512)) == b"a" * 512

    # 255 bytes
    assert parse_bytes(io.BytesIO(b"\x00\x00\x00\xff" + b"b" * 255)) == b"b" * 255

    # EOF
    with raises(AssertionError):
        parse_bytes(io.BytesIO(b"\x00\x00\x00\xff\x01\x02\x03"))

    with raises(AssertionError):
        parse_bytes(io.BytesIO(b"\xff\xff\xff\xff"))

    with raises(AssertionError):
        parse_bytes(io.BytesIO(b"\xff\xff\xff\xff" + b"a" * 512))

    # EOF off by one
    with raises(AssertionError):
        parse_bytes(io.BytesIO(b"\x00\x00\x02\x01" + b"a" * 512))


def test_parse_list():

    assert parse_list(io.BytesIO(b"\x00\x00\x00\x00"), parse_bool) == []
    assert parse_list(io.BytesIO(b"\x00\x00\x00\x01\x01"), parse_bool) == [True]
    assert parse_list(io.BytesIO(b"\x00\x00\x00\x03\x01\x00\x01"), parse_bool) == [True, False, True]

    # EOF
    with raises(AssertionError):
        parse_list(io.BytesIO(b"\x00\x00\x00\x01"), parse_bool)

    with raises(AssertionError):
        parse_list(io.BytesIO(b"\x00\x00\x00\xff\x00\x00"), parse_bool)

    with raises(AssertionError):
        parse_list(io.BytesIO(b"\xff\xff\xff\xff\x00\x00"), parse_bool)

    # failure to parser internal type
    with raises(ValueError):
        parse_list(io.BytesIO(b"\x00\x00\x00\x01\x02"), parse_bool)


def test_parse_tuple():

    assert parse_tuple(io.BytesIO(b""), []) == ()
    assert parse_tuple(io.BytesIO(b"\x00\x00"), [parse_bool, parse_bool]) == (False, False)
    assert parse_tuple(io.BytesIO(b"\x00\x01"), [parse_bool, parse_bool]) == (False, True)

    # error in parsing internal type
    with raises(ValueError):
        parse_tuple(io.BytesIO(b"\x00\x02"), [parse_bool, parse_bool])

    # EOF
    with raises(AssertionError):
        parse_tuple(io.BytesIO(b"\x00"), [parse_bool, parse_bool])


def test_parse_size_hints():
    class TestFromBytes:
        b: bytes

        @classmethod
        def from_bytes(cls, b):
            ret = TestFromBytes()
            ret.b = b
            return ret

    assert parse_size_hints(io.BytesIO(b"1337"), TestFromBytes, 4).b == b"1337"

    # EOF
    with raises(AssertionError):
        parse_size_hints(io.BytesIO(b"133"), TestFromBytes, 4)

    class FailFromBytes:
        @classmethod
        def from_bytes(cls, b):
            raise ValueError()

    # error in underlying type
    with raises(ValueError):
        parse_size_hints(io.BytesIO(b"1337"), FailFromBytes, 4)


def test_parse_str():

    assert parse_str(io.BytesIO(b"\x00\x00\x00\x00")) == ""
    assert parse_str(io.BytesIO(b"\x00\x00\x00\x01a")) == "a"

    # 512 bytes
    assert parse_str(io.BytesIO(b"\x00\x00\x02\x00" + b"a" * 512)) == "a" * 512

    # 255 bytes
    assert parse_str(io.BytesIO(b"\x00\x00\x00\xff" + b"b" * 255)) == "b" * 255

    # EOF
    with raises(AssertionError):
        parse_str(io.BytesIO(b"\x00\x00\x00\xff\x01\x02\x03"))

    with raises(AssertionError):
        parse_str(io.BytesIO(b"\xff\xff\xff\xff"))

    with raises(AssertionError):
        parse_str(io.BytesIO(b"\xff\xff\xff\xff" + b"a" * 512))

    # EOF off by one
    with raises(AssertionError):
        parse_str(io.BytesIO(b"\x00\x00\x02\x01" + b"a" * 512))


def test_wrong_decorator_order():

    with raises(DefinitionError):

        @dataclass(frozen=True)
        @streamable
        class WrongDecoratorOrder(Streamable):
            pass


def test_dataclass_not_frozen():

    with raises(DefinitionError):

        @streamable
        @dataclass(frozen=False)
        class DataclassNotFrozen(Streamable):
            pass


def test_dataclass_missing():

    with raises(DefinitionError):

        @streamable
        class DataclassMissing(Streamable):
            pass


def test_streamable_inheritance_missing():

    with raises(DefinitionError):

        @streamable
        @dataclass(frozen=True)
        class StreamableInheritanceMissing:
            pass
