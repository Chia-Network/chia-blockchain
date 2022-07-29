from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pytest
from clvm_tools import binutils
from typing_extensions import Literal

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
    is_type_List,
    is_type_SpecificOptional,
    parse_bool,
    parse_bytes,
    parse_list,
    parse_optional,
    parse_size_hints,
    parse_str,
    parse_tuple,
    parse_uint32,
    streamable,
    write_uint32,
)
from tests.block_tools import BlockTools
from tests.setup_nodes import test_constants


def test_int_not_supported() -> None:
    with pytest.raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClassInt(Streamable):
            a: int


def test_float_not_supported() -> None:
    with pytest.raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClassFloat(Streamable):
            a: float


def test_dict_not_suppported() -> None:
    with pytest.raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClassDict(Streamable):
            a: Dict[str, str]


@dataclass(frozen=True)
class DataclassOnly:
    a: uint8


def test_pure_dataclass_not_supported() -> None:

    with pytest.raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClassDataclass(Streamable):
            a: DataclassOnly


class PlainClass:
    a: uint8


def test_plain_class_not_supported() -> None:

    with pytest.raises(NotImplementedError):

        @streamable
        @dataclass(frozen=True)
        class TestClassPlain(Streamable):
            a: PlainClass


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


def test_StrictDataClass() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClass1(Streamable):
        a: uint8
        b: str

    # we want to test invalid here, hence the ignore.
    good: TestClass1 = TestClass1(24, "!@12")  # type: ignore[arg-type]
    assert TestClass1.__name__ == "TestClass1"
    assert good
    assert good.a == 24
    assert good.b == "!@12"
    # we want to test invalid here, hence the ignore.
    good2 = TestClass1(52, bytes([1, 2, 3]))  # type: ignore[arg-type]
    assert good2.b == str(bytes([1, 2, 3]))


def test_StrictDataClassBad() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClass2(Streamable):
        a: uint8
        b = 0

    # we want to test invalid here, hence the ignore.
    assert TestClass2(25)  # type: ignore[arg-type]

    # we want to test invalid here, hence the ignore.
    with pytest.raises(TypeError):
        TestClass2(1, 2)  # type: ignore[call-arg,arg-type] # pylint: disable=too-many-function-args


def test_StrictDataClassLists() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClass(Streamable):
        a: List[uint8]
        b: List[List[uint8]]

    # we want to test invalid here, hence the ignore.
    assert TestClass([1, 2, 3], [[uint8(200), uint8(25)], [uint8(25)]])  # type: ignore[list-item]

    # we want to test invalid here, hence the ignore.
    with pytest.raises(ValueError):
        TestClass({"1": 1}, [[uint8(200), uint8(25)], [uint8(25)]])  # type: ignore[arg-type]

    # we want to test invalid here, hence the ignore.
    with pytest.raises(ValueError):
        TestClass([1, 2, 3], [uint8(200), uint8(25)])  # type: ignore[list-item]


def test_StrictDataClassOptional() -> None:
    @streamable
    @dataclass(frozen=True)
    class TestClass(Streamable):
        a: Optional[uint8]
        b: Optional[uint8]
        c: Optional[Optional[uint8]]
        d: Optional[Optional[uint8]]

    # we want to test invalid here, hence the ignore.
    good = TestClass(12, None, 13, None)  # type: ignore[arg-type]
    assert good


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

    with pytest.raises(NotImplementedError):

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
