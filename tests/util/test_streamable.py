import unittest
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from src.util.ints import uint32
from src.types.coin import Coin
from src.types.sized_bytes import bytes32
from src.types.full_block import FullBlock
from src.util.streamable import Streamable, streamable
from tests.block_tools import BlockTools
from src.protocols.wallet_protocol import RespondRemovals
from src.util import cbor


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
        bt = BlockTools()

        test_constants: Dict[str, Any] = {
            "DIFFICULTY_STARTING": 5,
            "DISCRIMINANT_SIZE_BITS": 16,
            "BLOCK_TIME_TARGET": 10,
            "MIN_BLOCK_TIME": 2,
            "DIFFICULTY_EPOCH": 12,  # The number of blocks per epoch
            "DIFFICULTY_DELAY": 3,  # EPOCH / WARP_FACTOR
        }
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

        tc2 = TestClass2(
            uint32(5), [[tc1_a], [tc1_b, tc1_c], None], bytes32(bytes([1] * 32))
        )
        assert TestClass2.from_json_dict(tc2.to_json_dict()) == tc2

    def test_recursive_types(self):
        coin: Optional[Coin] = None
        l1 = [(bytes32([2] * 32), coin)]
        rr = RespondRemovals(uint32(1), bytes32([1] * 32), l1, None)
        c = cbor.loads(cbor.dumps(rr))
        RespondRemovals(c["height"], c["header_hash"], c["coins"], c["proofs"])


if __name__ == "__main__":
    unittest.main()
