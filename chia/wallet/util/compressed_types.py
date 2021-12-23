from dataclasses import dataclass

from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.puzzle_compression import compress_object_with_puzzles, decompress_object_with_puzzles


@dataclass(frozen=True)
@streamable
class CompressedPuzzle(Streamable):
    compressed_puzzle: bytes

    @classmethod
    def compress(cls, puzzle: Program, version: int):
        return cls(b"PUZL" + compress_object_with_puzzles(bytes(puzzle), version))

    def decompress(self) -> Program:
        assert self.compressed_puzzle[0:4] == b"PUZL"
        return Program.from_bytes(decompress_object_with_puzzles(self.compressed_puzzle[4:]))


@dataclass(frozen=True)
@streamable
class CompressedCoinSpend(Streamable):
    compressed_coin_spend: bytes

    @classmethod
    def compress(cls, coin_spend: CoinSpend, version: int):
        return cls(b"CNSP" + compress_object_with_puzzles(bytes(coin_spend), version))

    def decompress(self) -> CoinSpend:
        assert self.compressed_coin_spend[0:4] == b"CNSP"
        return CoinSpend.from_bytes(decompress_object_with_puzzles(self.compressed_coin_spend[4:]))


@dataclass(frozen=True)
@streamable
class CompressedSpendBundle(Streamable):
    compressed_spend_bundle: bytes

    @classmethod
    def compress(cls, spend_bundle: SpendBundle, version: int):
        return cls(b"SPBL" + compress_object_with_puzzles(bytes(spend_bundle), version))

    def decompress(self) -> SpendBundle:
        assert self.compressed_spend_bundle[0:4] == b"SPBL"
        return SpendBundle.from_bytes(decompress_object_with_puzzles(self.compressed_spend_bundle[4:]))
