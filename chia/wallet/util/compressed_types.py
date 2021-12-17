from dataclasses import dataclass

from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.puzzle_compression import PuzzleCompressor


@dataclass(frozen=True)
@streamable
class CompressedPuzzle(Streamable):
    compressed_puzzle: Program

    @classmethod
    def compress(cls, puzzle: Program, compressor=PuzzleCompressor()):
        return cls(Program.to(compressor.serialize(puzzle)))

    def decompress(self, compressor=PuzzleCompressor()) -> Program:
        return compressor.deserialize(self.compressed_puzzle.as_python())


@dataclass(frozen=True)
@streamable
class CompressedCoinSpend(Streamable):
    compressed_coin_spend: CoinSpend

    @classmethod
    def compress(cls, coin_spend: CoinSpend, compressor=PuzzleCompressor()):
        return cls(
            CoinSpend(
                coin_spend.coin,
                CompressedPuzzle.compress(
                    coin_spend.puzzle_reveal.to_program(), compressor=compressor
                ).compressed_puzzle.to_serialized_program(),
                coin_spend.solution,
            )
        )

    def decompress(self, compressor=PuzzleCompressor()) -> CoinSpend:
        return CoinSpend(
            self.compressed_coin_spend.coin,
            CompressedPuzzle(self.compressed_coin_spend.puzzle_reveal.to_program())
            .decompress(compressor=compressor)
            .to_serialized_program(),
            self.compressed_coin_spend.solution,
        )


@dataclass(frozen=True)
@streamable
class CompressedSpendBundle(Streamable):
    compressed_spend_bundle: SpendBundle

    @classmethod
    def compress(cls, spend_bundle: SpendBundle, compressor=PuzzleCompressor()):
        return cls(
            SpendBundle(
                [CompressedCoinSpend.compress(cs, compressor=compressor) for cs in spend_bundle.coin_spends],
                spend_bundle.aggregated_signature,
            )
        )

    def decompress(self, compressor=PuzzleCompressor()) -> SpendBundle:
        return SpendBundle(
            [CompressedCoinSpend(cs).decompress(compressor=compressor) for cs in self.compressed_spend_bundle.coin_spends],
            self.compressed_spend_bundle.aggregated_signature,
        )
