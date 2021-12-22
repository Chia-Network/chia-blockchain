from blspy import G1Element

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.cc_wallet.cc_utils import CC_MOD, construct_cc_puzzle
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk

COIN = Coin(bytes([0] * 32), bytes([0] * 32), uint64(0))
SOLUTION = Program.to([])


class TestSingleton:
    def test_standard_puzzle(self):
        coin_spend = CoinSpend(
            COIN,
            puzzle_for_pk(G1Element()),
            SOLUTION,
        )
        assert coin_spend == CoinSpend.decompress(CoinSpend.compress(coin_spend))

    def test_cat_puzzle(self):
        coin_spend = CoinSpend(
            COIN,
            construct_cc_puzzle(CC_MOD, Program.to([]).get_tree_hash(), Program.to(1)),
            SOLUTION,
        )
        assert coin_spend == CoinSpend.decompress(CoinSpend.compress(coin_spend))

    def test_nesting_puzzles(self):
        coin_spend = CoinSpend(
            COIN,
            construct_cc_puzzle(CC_MOD, Program.to([]).get_tree_hash(), puzzle_for_pk(G1Element())),
            SOLUTION,
        )
        assert coin_spend == CoinSpend.decompress(CoinSpend.compress(coin_spend))

    def test_unknown_wrapper(self):
        unknown = Program.to([2, 2, []])  # (a 2 ())
        coin_spend = CoinSpend(
            COIN,
            unknown.curry(puzzle_for_pk(G1Element())),
            SOLUTION,
        )
        assert bytes(coin_spend.puzzle_reveal).hex() in bytes(CoinSpend.compress(coin_spend).puzzle_reveal).hex()
