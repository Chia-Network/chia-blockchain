import pytest

from blspy import G1Element, G2Element

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.trading.offer import OFFER_MOD
from chia.wallet.util.puzzle_compression import LATEST_VERSION, CompressionVersionError
from chia.wallet.util.compressed_types import CompressedCoinSpend, CompressedSpendBundle
from chia.wallet.cc_wallet.cc_utils import CC_MOD, construct_cc_puzzle
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk

ZERO_32 = bytes32([0] * 32)
ONE_32 = bytes32([17] * 32)
COIN = Coin(ZERO_32, ZERO_32, uint64(0))
SOLUTION = Program.to([])


class TestPuzzleCompression:
    compression_factors = {}

    def test_standard_puzzle(self):
        coin_spend = CoinSpend(
            COIN,
            puzzle_for_pk(G1Element()),
            SOLUTION,
        )
        compressed = CompressedCoinSpend.compress(coin_spend, LATEST_VERSION)
        assert len(bytes(coin_spend)) > len(bytes(compressed))
        assert coin_spend == compressed.decompress()
        self.compression_factors["standard_puzzle"] = len(bytes(compressed)) / len(bytes(coin_spend))

    def test_cat_puzzle(self):
        coin_spend = CoinSpend(
            COIN,
            construct_cc_puzzle(CC_MOD, Program.to([]).get_tree_hash(), Program.to(1)),
            SOLUTION,
        )
        compressed = CompressedCoinSpend.compress(coin_spend, LATEST_VERSION)
        assert len(bytes(coin_spend)) > len(bytes(compressed))
        assert coin_spend == compressed.decompress()
        self.compression_factors["cat_puzzle"] = len(bytes(compressed)) / len(bytes(coin_spend))

    def test_offer_puzzle(self):
        coin_spend = CoinSpend(
            COIN,
            OFFER_MOD,
            SOLUTION,
        )
        compressed = CompressedCoinSpend.compress(coin_spend, LATEST_VERSION)
        assert len(bytes(coin_spend)) > len(bytes(compressed))
        assert coin_spend == compressed.decompress()
        self.compression_factors["offer_puzzle"] = len(bytes(compressed)) / len(bytes(coin_spend))

    def test_nesting_puzzles(self):
        coin_spend = CoinSpend(
            COIN,
            construct_cc_puzzle(CC_MOD, Program.to([]).get_tree_hash(), puzzle_for_pk(G1Element())),
            SOLUTION,
        )
        compressed = CompressedCoinSpend.compress(coin_spend, LATEST_VERSION)
        assert len(bytes(coin_spend)) > len(bytes(compressed))
        assert coin_spend == compressed.decompress()
        self.compression_factors["cat_w_standard_puzzle"] = len(bytes(compressed)) / len(bytes(coin_spend))

    def test_unknown_wrapper(self):
        unknown = Program.to([2, 2, []])  # (a 2 ())
        coin_spend = CoinSpend(
            COIN,
            unknown.curry(puzzle_for_pk(G1Element())),
            SOLUTION,
        )
        compressed = CompressedCoinSpend.compress(coin_spend, LATEST_VERSION)
        assert len(bytes(coin_spend)) > len(bytes(compressed))
        assert coin_spend == compressed.decompress()
        self.compression_factors["unknown_and_standard"] = len(bytes(compressed)) / len(bytes(coin_spend))

    def test_compression_factors(self):
        import json
        import logging

        log = logging.getLogger(__name__)
        log.warning(json.dumps(self.compression_factors))

    def test_version_override(self):
        coin_spend = CoinSpend(
            COIN,
            OFFER_MOD,
            SOLUTION,
        )
        spend_bundle = SpendBundle([coin_spend], G2Element())
        compressed = CompressedSpendBundle.compress(spend_bundle, LATEST_VERSION)
        compressed_earlier = CompressedSpendBundle.compress(spend_bundle, 1)
        assert len(bytes(spend_bundle)) > len(bytes(compressed))
        assert spend_bundle == compressed.decompress()
        assert spend_bundle == compressed_earlier.decompress()
        assert len(bytes(compressed_earlier)) > len(bytes(compressed))
