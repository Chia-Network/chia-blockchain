import unittest
from dataclasses import dataclass
from typing import List, Optional

from pytest import raises

from chia.protocols.wallet_protocol import RespondRemovals
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.weight_proof import SubEpochChallengeSegment
from chia.util.ints import uint8, uint32
from chia.util.streamable import Streamable, streamable
from tests.setup_nodes import bt, test_constants


class TestStreamable(unittest.TestCase):
    def test_basic(self):
        @dataclass(frozen=True)
        @streamable
        class TestClass(Streamable):
            a: uint32
            b: uint32
            c: List[uint32]
            d: List[List[uint32]]
            e: Optional[uint32]
            f: Optional[uint32]

        a = TestClass(24, 352, [1, 2, 4], [[1, 2, 3], [3, 4]], 728, None)  # type: ignore

        b: bytes = bytes(a)
        assert a == TestClass.from_bytes(b)

    def test_variablesize(self):
        @dataclass(frozen=True)
        @streamable
        class TestClass2(Streamable):
            a: uint32
            b: uint32
            c: bytes

        a = TestClass2(uint32(1), uint32(2), b"3")
        bytes(a)

        @dataclass(frozen=True)
        @streamable
        class TestClass3(Streamable):
            a: int

        b = TestClass3(1)
        try:
            bytes(b)
            assert False
        except NotImplementedError:
            pass

    def test_json(self):
        block = bt.create_genesis_block(test_constants, bytes([0] * 32), b"0")

        dict_block = block.to_json_dict()
        assert FullBlock.from_json_dict(dict_block) == block

    def test_recursive_json(self):
        @dataclass(frozen=True)
        @streamable
        class TestClass1(Streamable):
            a: List[uint32]

        @dataclass(frozen=True)
        @streamable
        class TestClass2(Streamable):
            a: uint32
            b: List[Optional[List[TestClass1]]]
            c: bytes32

        tc1_a = TestClass1([uint32(1), uint32(2)])
        tc1_b = TestClass1([uint32(4), uint32(5)])
        tc1_c = TestClass1([uint32(7), uint32(8)])

        tc2 = TestClass2(uint32(5), [[tc1_a], [tc1_b, tc1_c], None], bytes32(bytes([1] * 32)))
        assert TestClass2.from_json_dict(tc2.to_json_dict()) == tc2

    def test_recursive_types(self):
        coin: Optional[Coin] = None
        l1 = [(bytes32([2] * 32), coin)]
        rr = RespondRemovals(uint32(1), bytes32([1] * 32), l1, None)
        RespondRemovals(rr.height, rr.header_hash, rr.coins, rr.proofs)

    def test_ambiguous_deserialization_optionals(self):
        with raises(AssertionError):
            SubEpochChallengeSegment.from_bytes(b"\x00\x00\x00\x03\xff\xff\xff\xff")

        @dataclass(frozen=True)
        @streamable
        class TestClassOptional(Streamable):
            a: Optional[uint8]

        # Does not have the required elements
        with raises(AssertionError):
            TestClassOptional.from_bytes(bytes([]))

        TestClassOptional.from_bytes(bytes([0]))
        TestClassOptional.from_bytes(bytes([1, 2]))

    def test_ambiguous_deserialization_int(self):
        @dataclass(frozen=True)
        @streamable
        class TestClassUint(Streamable):
            a: uint32

        # Does not have the required uint size
        with raises(AssertionError):
            TestClassUint.from_bytes(b"\x00\x00")

    def test_ambiguous_deserialization_list(self):
        @dataclass(frozen=True)
        @streamable
        class TestClassList(Streamable):
            a: List[uint8]

        # Does not have the required elements
        with raises(AssertionError):
            TestClassList.from_bytes(bytes([0, 0, 100, 24]))

    def test_ambiguous_deserialization_str(self):
        @dataclass(frozen=True)
        @streamable
        class TestClassStr(Streamable):
            a: str

        # Does not have the required str size
        with raises(AssertionError):
            TestClassStr.from_bytes(bytes([0, 0, 100, 24, 52]))

    def test_ambiguous_deserialization_bytes(self):
        @dataclass(frozen=True)
        @streamable
        class TestClassBytes(Streamable):
            a: bytes

        # Does not have the required str size
        with raises(AssertionError):
            TestClassBytes.from_bytes(bytes([0, 0, 100, 24, 52]))

        with raises(AssertionError):
            TestClassBytes.from_bytes(bytes([0, 0, 0, 1]))

        TestClassBytes.from_bytes(bytes([0, 0, 0, 1, 52]))
        TestClassBytes.from_bytes(bytes([0, 0, 0, 2, 52, 21]))

    def test_ambiguous_deserialization_bool(self):
        @dataclass(frozen=True)
        @streamable
        class TestClassBool(Streamable):
            a: bool

        # Does not have the required str size
        with raises(AssertionError):
            TestClassBool.from_bytes(bytes([]))

        TestClassBool.from_bytes(bytes([0]))
        TestClassBool.from_bytes(bytes([1]))


if __name__ == "__main__":
    unittest.main()
