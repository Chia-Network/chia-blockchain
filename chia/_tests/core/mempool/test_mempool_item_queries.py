from __future__ import annotations

from typing import List

from chia_rs import AugSchemeMPL, Coin, Program
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.core.mempool.test_mempool_manager import TEST_HEIGHT, make_bundle_spends_map_and_fee
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bitcoin_fee_estimator import create_bitcoin_fee_estimator
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.fee_estimation import MempoolInfo
from chia.full_node.mempool import Mempool
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.program import INFINITE_COST
from chia.types.clvm_cost import CLVMCost
from chia.types.coin_spend import CoinSpend
from chia.types.fee_rate import FeeRate
from chia.types.mempool_item import MempoolItem
from chia.types.spend_bundle import SpendBundle

MEMPOOL_INFO = MempoolInfo(
    max_size_in_cost=CLVMCost(uint64(INFINITE_COST * 10)),
    minimum_fee_per_cost_to_replace=FeeRate(uint64(5)),
    max_block_clvm_cost=CLVMCost(uint64(INFINITE_COST)),
)

IDENTITY_PUZZLE = Program.to(1)
IDENTITY_PUZZLE_HASH = IDENTITY_PUZZLE.get_tree_hash()

OTHER_PUZZLE = Program.to(2)
OTHER_PUZZLE_HASH = OTHER_PUZZLE.get_tree_hash()

IDENTITY_COIN_1 = Coin(bytes32(b"0" * 32), IDENTITY_PUZZLE_HASH, uint64(1000))
IDENTITY_COIN_2 = Coin(bytes32(b"1" * 32), IDENTITY_PUZZLE_HASH, uint64(1000))
IDENTITY_COIN_3 = Coin(bytes32(b"2" * 32), IDENTITY_PUZZLE_HASH, uint64(1000))

OTHER_COIN_1 = Coin(bytes32(b"3" * 32), OTHER_PUZZLE_HASH, uint64(1000))
OTHER_COIN_2 = Coin(bytes32(b"4" * 32), OTHER_PUZZLE_HASH, uint64(1000))
OTHER_COIN_3 = Coin(bytes32(b"5" * 32), OTHER_PUZZLE_HASH, uint64(1000))

EMPTY_SIGNATURE = AugSchemeMPL.aggregate([])


def make_item(coin_spends: List[CoinSpend]) -> MempoolItem:
    spend_bundle = SpendBundle(coin_spends, EMPTY_SIGNATURE)
    generator = simple_solution_generator(spend_bundle)
    npc_result = get_name_puzzle_conditions(
        generator=generator, max_cost=INFINITE_COST, mempool_mode=True, height=uint32(0), constants=DEFAULT_CONSTANTS
    )
    assert npc_result.conds is not None
    bundle_coin_spends, fee = make_bundle_spends_map_and_fee(spend_bundle, npc_result.conds)
    return MempoolItem(
        spend_bundle=spend_bundle,
        fee=fee,
        conds=npc_result.conds,
        spend_bundle_name=spend_bundle.name(),
        height_added_to_mempool=TEST_HEIGHT,
        bundle_coin_spends=bundle_coin_spends,
    )


def test_empty_pool() -> None:
    fee_estimator = create_bitcoin_fee_estimator(uint64(INFINITE_COST))
    mempool = Mempool(MEMPOOL_INFO, fee_estimator)
    assert mempool.items_with_coin_ids({IDENTITY_COIN_1.name()}) == []
    assert mempool.items_with_puzzle_hashes({IDENTITY_PUZZLE_HASH}, False) == []


def test_by_spent_coin_ids() -> None:
    fee_estimator = create_bitcoin_fee_estimator(uint64(INFINITE_COST))
    mempool = Mempool(MEMPOOL_INFO, fee_estimator)

    # Add an item with both queried coins, to ensure there are no duplicates in the response.
    item_1 = make_item(
        [
            CoinSpend(IDENTITY_COIN_1, IDENTITY_PUZZLE, Program.to([])),
            CoinSpend(IDENTITY_COIN_2, IDENTITY_PUZZLE, Program.to([])),
        ]
    )
    mempool.add_to_pool(item_1)

    # Another coin with the same puzzle hash shouldn't match.
    other = make_item(
        [
            CoinSpend(IDENTITY_COIN_3, IDENTITY_PUZZLE, Program.to([])),
        ]
    )
    mempool.add_to_pool(other)

    # And this coin is completely unrelated.
    other = make_item([CoinSpend(OTHER_COIN_1, OTHER_PUZZLE, Program.to([[]]))])
    mempool.add_to_pool(other)

    # Only the first transaction includes these coins.
    assert mempool.items_with_coin_ids({IDENTITY_COIN_1.name(), IDENTITY_COIN_2.name()}) == [item_1.spend_bundle_name]
    assert mempool.items_with_coin_ids({IDENTITY_COIN_1.name()}) == [item_1.spend_bundle_name]
    assert mempool.items_with_coin_ids({OTHER_COIN_2.name(), OTHER_COIN_3.name()}) == []


def test_by_spend_puzzle_hashes() -> None:
    fee_estimator = create_bitcoin_fee_estimator(uint64(INFINITE_COST))
    mempool = Mempool(MEMPOOL_INFO, fee_estimator)

    # Add a transaction with the queried puzzle hashes.
    item_1 = make_item(
        [
            CoinSpend(IDENTITY_COIN_1, IDENTITY_PUZZLE, Program.to([])),
            CoinSpend(IDENTITY_COIN_2, IDENTITY_PUZZLE, Program.to([])),
        ]
    )
    mempool.add_to_pool(item_1)

    # Another coin with the same puzzle hash should match.
    item_2 = make_item(
        [
            CoinSpend(IDENTITY_COIN_3, IDENTITY_PUZZLE, Program.to([])),
        ]
    )
    mempool.add_to_pool(item_2)

    # But this coin has a different puzzle hash.
    other = make_item([CoinSpend(OTHER_COIN_1, OTHER_PUZZLE, Program.to([[]]))])
    mempool.add_to_pool(other)

    # Only the first two transactions include the puzzle hash.
    assert mempool.items_with_puzzle_hashes({IDENTITY_PUZZLE_HASH}, False) == [
        item_1.spend_bundle_name,
        item_2.spend_bundle_name,
    ]

    # Test the other puzzle hash as well.
    assert mempool.items_with_puzzle_hashes({OTHER_PUZZLE_HASH}, False) == [
        other.spend_bundle_name,
    ]

    # And an unrelated puzzle hash.
    assert mempool.items_with_puzzle_hashes({bytes32(b"0" * 32)}, False) == []


def test_by_created_coin_id() -> None:
    fee_estimator = create_bitcoin_fee_estimator(uint64(INFINITE_COST))
    mempool = Mempool(MEMPOOL_INFO, fee_estimator)

    # Add a transaction that creates the queried coin id.
    item = make_item(
        [
            CoinSpend(IDENTITY_COIN_1, IDENTITY_PUZZLE, Program.to([[51, IDENTITY_PUZZLE_HASH, 1000]])),
        ]
    )
    mempool.add_to_pool(item)

    # Test that the transaction is found.
    assert mempool.items_with_coin_ids({Coin(IDENTITY_COIN_1.name(), IDENTITY_PUZZLE_HASH, uint64(1000)).name()}) == [
        item.spend_bundle_name
    ]


def test_by_created_puzzle_hash() -> None:
    fee_estimator = create_bitcoin_fee_estimator(uint64(INFINITE_COST))
    mempool = Mempool(MEMPOOL_INFO, fee_estimator)

    # Add a transaction that creates the queried puzzle hash.
    item_1 = make_item(
        [
            CoinSpend(
                IDENTITY_COIN_1,
                IDENTITY_PUZZLE,
                Program.to([[51, OTHER_PUZZLE_HASH, 400], [51, OTHER_PUZZLE_HASH, 600]]),
            ),
        ]
    )
    mempool.add_to_pool(item_1)

    # This one is hinted.
    item_2 = make_item(
        [
            CoinSpend(
                IDENTITY_COIN_2,
                IDENTITY_PUZZLE,
                Program.to([[51, IDENTITY_PUZZLE_HASH, 1000, [OTHER_PUZZLE_HASH]]]),
            ),
        ]
    )
    mempool.add_to_pool(item_2)

    # Test that the transactions are both found.
    assert mempool.items_with_puzzle_hashes({OTHER_PUZZLE_HASH}, include_hints=True) == [
        item_1.spend_bundle_name,
        item_2.spend_bundle_name,
    ]
