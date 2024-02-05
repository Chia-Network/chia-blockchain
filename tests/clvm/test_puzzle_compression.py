from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, SupportsBytes

import pytest
from chia_rs import G1Element, G2Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, construct_cat_puzzle
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk
from chia.wallet.trading.offer import OFFER_MOD
from chia.wallet.util.puzzle_compression import (
    LATEST_VERSION,
    OFFER_MOD_OLD,
    compress_object_with_puzzles,
    decompress_object_with_puzzles,
    lowest_best_version,
)

ZERO_32 = bytes32([0] * 32)
ONE_32 = bytes32([17] * 32)
COIN = Coin(ZERO_32, ZERO_32, uint64(0))
SOLUTION = Program.to([])


log = logging.getLogger(__name__)


@dataclass
class CompressionReporter:
    record_property: Callable

    def __call__(self, name: str, original: SupportsBytes, compressed: SupportsBytes):
        ratio = len(bytes(compressed)) / len(bytes(original))
        self.record_property(name="compression_ratio", value=ratio)
        log.warning(f"{name} compression ratio: {ratio}")


@pytest.fixture(name="report_compression")
def report_compression_fixture(record_property):
    return CompressionReporter(record_property=record_property)


def test_standard_puzzle(report_compression):
    coin_spend = make_spend(
        COIN,
        puzzle_for_pk(G1Element()),
        SOLUTION,
    )
    compressed = compress_object_with_puzzles(bytes(coin_spend), LATEST_VERSION)
    assert len(bytes(coin_spend)) > len(compressed)
    assert coin_spend == CoinSpend.from_bytes(decompress_object_with_puzzles(compressed))

    report_compression(name="standard puzzle", original=coin_spend, compressed=compressed)


def test_decompress_limit():
    buffer = bytearray(10 * 1024 * 1024)
    compressed = compress_object_with_puzzles(buffer, LATEST_VERSION)
    print(len(compressed))
    decompressed = decompress_object_with_puzzles(compressed)
    print(len(decompressed))
    assert len(decompressed) <= 6 * 1024 * 1024


def test_cat_puzzle(report_compression):
    coin_spend = make_spend(
        COIN,
        construct_cat_puzzle(CAT_MOD, Program.to([]).get_tree_hash(), Program.to(1)),
        SOLUTION,
    )
    compressed = compress_object_with_puzzles(bytes(coin_spend), LATEST_VERSION)
    assert len(bytes(coin_spend)) > len(compressed)
    assert coin_spend == CoinSpend.from_bytes(decompress_object_with_puzzles(compressed))

    report_compression(name="CAT puzzle", original=coin_spend, compressed=compressed)


def test_offer_puzzle(report_compression):
    coin_spend = make_spend(
        COIN,
        OFFER_MOD,
        SOLUTION,
    )
    compressed = compress_object_with_puzzles(bytes(coin_spend), LATEST_VERSION)
    assert len(bytes(coin_spend)) > len(compressed)
    assert coin_spend == CoinSpend.from_bytes(decompress_object_with_puzzles(compressed))

    report_compression(name="offer puzzle", original=coin_spend, compressed=compressed)


def test_nesting_puzzles(report_compression):
    coin_spend = make_spend(
        COIN,
        construct_cat_puzzle(CAT_MOD, Program.to([]).get_tree_hash(), puzzle_for_pk(G1Element())),
        SOLUTION,
    )
    compressed = compress_object_with_puzzles(bytes(coin_spend), LATEST_VERSION)
    assert len(bytes(coin_spend)) > len(compressed)
    assert coin_spend == CoinSpend.from_bytes(decompress_object_with_puzzles(compressed))

    report_compression(name="nesting puzzle", original=coin_spend, compressed=compressed)


def test_unknown_wrapper(report_compression):
    unknown = Program.to([2, 2, []])  # (a 2 ())
    coin_spend = make_spend(
        COIN,
        unknown.curry(puzzle_for_pk(G1Element())),
        SOLUTION,
    )
    compressed = compress_object_with_puzzles(bytes(coin_spend), LATEST_VERSION)
    assert len(bytes(coin_spend)) > len(compressed)
    assert coin_spend == CoinSpend.from_bytes(decompress_object_with_puzzles(compressed))

    report_compression(name="unknown wrapper", original=coin_spend, compressed=compressed)


def test_lowest_best_version():
    assert lowest_best_version([bytes(CAT_MOD)]) == 4
    assert lowest_best_version([bytes(OFFER_MOD_OLD)]) == 2
    assert lowest_best_version([bytes(OFFER_MOD)]) == 5


def test_version_override():
    coin_spend = make_spend(
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
