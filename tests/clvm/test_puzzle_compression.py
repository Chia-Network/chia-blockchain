from blspy import G1Element, G2Element
from typing import Dict

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.trading.offer import OFFER_MOD
from chia.wallet.util.puzzle_compression import (
    LATEST_VERSION,
    lowest_best_version,
    compress_object_with_puzzles,
    decompress_object_with_puzzles,
)
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, construct_cat_puzzle
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk

ZERO_32 = bytes32([0] * 32)
ONE_32 = bytes32([17] * 32)
COIN = Coin(ZERO_32, ZERO_32, uint64(0))
SOLUTION = Program.to([])


class TestPuzzleCompression:
    compression_factors: Dict[str, float] = {}

    def test_standard_puzzle(self):
        coin_spend = CoinSpend(
            COIN,
            puzzle_for_pk(G1Element()),
            SOLUTION,
        )
        compressed = compress_object_with_puzzles(bytes(coin_spend), LATEST_VERSION)
        assert len(bytes(coin_spend)) > len(compressed)
        assert coin_spend == CoinSpend.from_bytes(decompress_object_with_puzzles(compressed))
        self.compression_factors["standard_puzzle"] = len(bytes(compressed)) / len(bytes(coin_spend))

    def test_cat_puzzle(self):
        coin_spend = CoinSpend(
            COIN,
            construct_cat_puzzle(CAT_MOD, Program.to([]).get_tree_hash(), Program.to(1)),
            SOLUTION,
        )
        compressed = compress_object_with_puzzles(bytes(coin_spend), LATEST_VERSION)
        assert len(bytes(coin_spend)) > len(compressed)
        assert coin_spend == CoinSpend.from_bytes(decompress_object_with_puzzles(compressed))
        self.compression_factors["cat_puzzle"] = len(bytes(compressed)) / len(bytes(coin_spend))

    def test_offer_puzzle(self):
        coin_spend = CoinSpend(
            COIN,
            OFFER_MOD,
            SOLUTION,
        )
        compressed = compress_object_with_puzzles(bytes(coin_spend), LATEST_VERSION)
        assert len(bytes(coin_spend)) > len(compressed)
        assert coin_spend == CoinSpend.from_bytes(decompress_object_with_puzzles(compressed))
        self.compression_factors["offer_puzzle"] = len(bytes(compressed)) / len(bytes(coin_spend))

    def test_nesting_puzzles(self):
        coin_spend = CoinSpend(
            COIN,
            construct_cat_puzzle(CAT_MOD, Program.to([]).get_tree_hash(), puzzle_for_pk(G1Element())),
            SOLUTION,
        )
        compressed = compress_object_with_puzzles(bytes(coin_spend), LATEST_VERSION)
        assert len(bytes(coin_spend)) > len(compressed)
        assert coin_spend == CoinSpend.from_bytes(decompress_object_with_puzzles(compressed))
        self.compression_factors["cat_w_standard_puzzle"] = len(bytes(compressed)) / len(bytes(coin_spend))

    def test_unknown_wrapper(self):
        unknown = Program.to([2, 2, []])  # (a 2 ())
        coin_spend = CoinSpend(
            COIN,
            unknown.curry(puzzle_for_pk(G1Element())),
            SOLUTION,
        )
        compressed = compress_object_with_puzzles(bytes(coin_spend), LATEST_VERSION)
        assert len(bytes(coin_spend)) > len(compressed)
        assert coin_spend == CoinSpend.from_bytes(decompress_object_with_puzzles(compressed))
        self.compression_factors["unknown_and_standard"] = len(bytes(compressed)) / len(bytes(coin_spend))

    def test_lowest_best_version(self):
        assert lowest_best_version([bytes(CAT_MOD)]) == 4
        assert lowest_best_version([bytes(OFFER_MOD)]) == 2

    def test_version_override(self):
        coin_spend = CoinSpend(
            COIN,
            OFFER_MOD,
            SOLUTION,
        )
        spend_bundle = SpendBundle([coin_spend], G2Element())
        compressed = compress_object_with_puzzles(bytes(spend_bundle), LATEST_VERSION)
        compressed_earlier = compress_object_with_puzzles(bytes(spend_bundle), 1)
        assert len(bytes(spend_bundle)) > len(bytes(compressed))
        assert spend_bundle == SpendBundle.from_bytes(decompress_object_with_puzzles(compressed))
        assert spend_bundle == SpendBundle.from_bytes(decompress_object_with_puzzles(compressed_earlier))
        assert len(bytes(compressed_earlier)) > len(bytes(compressed))

    def test_compression_factors(self):
        import json
        import logging

        log = logging.getLogger(__name__)
        log.warning(json.dumps(self.compression_factors))
