from blspy import G1Element, G2Element

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.coin import Coin
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.util.puzzle_compression import PuzzleCompressor, CompressionVersionError
from chia.wallet.util.compressed_types import CompressedCoinSpend, CompressedSpendBundle
from chia.wallet.cc_wallet.cc_utils import CC_MOD, construct_cc_puzzle
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk

ZERO_32 = bytes([0] * 32)
ONE_32 = bytes([17] * 32)
COIN = Coin(ZERO_32, ZERO_32, uint64(0))
SOLUTION = Program.to([])


class DummyDriver:
    @staticmethod
    def match(puzzle, version):
        return True, [puzzle]

    @staticmethod
    def construct(driver_dict, args):
        return args[0]

    @staticmethod
    def solve(driver_dict, args, solution_dict):
        return Program.to([])


class TestSingleton:
    def test_standard_puzzle(self):
        coin_spend = CoinSpend(
            COIN,
            puzzle_for_pk(G1Element()),
            SOLUTION,
        )
        assert coin_spend == CompressedCoinSpend.compress(coin_spend).decompress()

    def test_cat_puzzle(self):
        coin_spend = CoinSpend(
            COIN,
            construct_cc_puzzle(CC_MOD, Program.to([]).get_tree_hash(), Program.to(1)),
            SOLUTION,
        )
        assert coin_spend == CompressedCoinSpend.compress(coin_spend).decompress()

    def test_nesting_puzzles(self):
        coin_spend = CoinSpend(
            COIN,
            construct_cc_puzzle(CC_MOD, Program.to([]).get_tree_hash(), puzzle_for_pk(G1Element())),
            SOLUTION,
        )
        assert coin_spend == CompressedCoinSpend.compress(coin_spend).decompress()

    def test_unknown_wrapper(self):
        unknown = Program.to([2, 2, []])  # (a 2 ())
        coin_spend = CoinSpend(
            COIN,
            unknown.curry(puzzle_for_pk(G1Element())),
            SOLUTION,
        )
        assert (
            bytes(coin_spend.puzzle_reveal).hex()
            in bytes(CompressedCoinSpend.compress(coin_spend).compressed_coin_spend.puzzle_reveal).hex()
        )

    def test_version_override(self):
        coin_spend = CoinSpend(
            COIN,
            Program.to([]),
            SOLUTION,
        )
        spend_bundle = SpendBundle([coin_spend], G2Element())
        new_version_dict = {ONE_32: DummyDriver}
        new_compressor = PuzzleCompressor(driver_dict=new_version_dict)
        # Our custom compression is super bad so the length should actually be greater
        assert len(bytes(CompressedSpendBundle.compress(spend_bundle, compressor=new_compressor))) > len(
            bytes(spend_bundle)
        )
        assert spend_bundle == CompressedSpendBundle.compress(spend_bundle, compressor=new_compressor).decompress(
            compressor=new_compressor
        )

        try:
            CompressedSpendBundle.compress(spend_bundle, compressor=new_compressor).decompress()
            assert False
        except CompressionVersionError:
            pass
