from __future__ import annotations

import asyncio
import logging
from random import sample
from secrets import token_bytes
from typing import Dict, List

import blspy
import pytest

from chia.full_node.tx_processing_queue import TransactionQueue, TransactionQueueFull
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.types.transaction_queue_entry import TransactionQueueEntry
from chia.util.ints import uint64
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import solution_for_conditions
from tests.core.make_block_generator import puzzle_hash_for_index

log = logging.getLogger(__name__)


# this code generates random spend bundles.


def make_standard_spend_bundle(count: int) -> SpendBundle:
    puzzle_dict: Dict[bytes32, Program] = {}
    starting_ph: bytes32 = puzzle_hash_for_index(0, puzzle_dict)
    solution: Program = solution_for_conditions(
        Program.to([[ConditionOpcode.CREATE_COIN, puzzle_hash_for_index(1, puzzle_dict), uint64(100000)]])
    )
    coins = [Coin(bytes32(index.to_bytes(32, "big")), starting_ph, uint64(100000)) for index in range(count)]
    coin_spends = [CoinSpend(coin, puzzle_dict[starting_ph], solution) for coin in coins]
    spend_bundle = SpendBundle(coin_spends, blspy.G2Element())
    return spend_bundle


# we only want to call this once as it can take minutes if we call it many times.
standard_spend_bundle = make_standard_spend_bundle(3)


def get_peer_id() -> bytes32:
    return bytes32(token_bytes(32))


def get_transaction_queue_entry(peer_id: bytes32) -> TransactionQueueEntry:
    sb: SpendBundle = standard_spend_bundle
    return TransactionQueueEntry(
        sb,
        peer_id,  # we cheat a bit here by reusing transaction_bytes to store our peer_id
        sb.name(),
        None,
        False,
    )


@pytest.mark.asyncio
async def test_local_txs() -> None:
    transaction_queue = TransactionQueue(1000, log)
    # test 1 tx
    first_tx = get_transaction_queue_entry(get_peer_id())
    await transaction_queue.put(first_tx, None)

    assert transaction_queue._index_to_peer_map == []
    assert transaction_queue._queue_length._value == 1

    result1 = await transaction_queue.pop()

    assert transaction_queue._queue_length._value == 0
    assert result1 == first_tx

    # test 2000 txs
    num_txs = 2000
    list_txs = [get_transaction_queue_entry(get_peer_id()) for _ in range(num_txs)]
    for tx in list_txs:
        await transaction_queue.put(tx, None)

    assert transaction_queue._queue_length._value == num_txs  # check that all are included
    assert transaction_queue._index_to_peer_map == []  # sanity checking

    resulting_txs = []
    for _ in range(num_txs):
        resulting_txs.append(await transaction_queue.pop())

    assert transaction_queue._queue_length._value == 0  # check that all are removed
    for i in range(num_txs):
        assert list_txs[i] == resulting_txs[i]


@pytest.mark.asyncio
async def test_one_peer_and_await() -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_txs = 100
    peer_id = bytes32(token_bytes(32))

    list_txs = [get_transaction_queue_entry(peer_id) for _ in range(num_txs)]
    for tx in list_txs:
        await transaction_queue.put(tx, peer_id)

    assert transaction_queue._queue_length._value == num_txs  # check that all are included
    assert transaction_queue._index_to_peer_map == [peer_id]  # sanity checking

    resulting_txs = []
    for _ in range(num_txs):
        resulting_txs.append(await transaction_queue.pop())

    assert transaction_queue._queue_length._value == 0  # check that all are removed
    for i in range(num_txs):
        assert list_txs[i] == resulting_txs[i]

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(transaction_queue.pop(), 1)  # check that we can't pop anymore


@pytest.mark.asyncio
async def test_lots_of_peers() -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_peers = 1000
    num_txs = 100
    total_txs = num_txs * num_peers
    peer_ids: List[bytes32] = [get_peer_id() for _ in range(num_peers)]

    # 100 txs per peer
    list_txs = [get_transaction_queue_entry(peer_id) for peer_id in peer_ids for _ in range(num_txs)]
    for tx in list_txs:
        assert tx.transaction_bytes is not None
        await transaction_queue.put(tx, bytes32(tx.transaction_bytes))  # as said above, we cheat a bit here

    assert transaction_queue._queue_length._value == total_txs  # check that all are included
    assert transaction_queue._index_to_peer_map == peer_ids  # make sure all peers are in the map

    resulting_txs = []
    for _ in range(total_txs):
        resulting_txs.append(await transaction_queue.pop())

    assert transaction_queue._queue_length._value == 0  # check that all are removed
    assert transaction_queue._index_to_peer_map == []  # we should have removed all the peer ids
    # There are 1000 peers, so each peer will have one transaction processed every 1000 iterations.
    for i in range(num_txs):
        assert list_txs[i] == resulting_txs[i * 1000]


@pytest.mark.asyncio
async def test_full_queue() -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_peers = 100
    num_txs = 1000
    total_txs = num_txs * num_peers
    peer_ids: List[bytes32] = [get_peer_id() for _ in range(num_peers)]

    # 999 txs per peer then 1 to fail later
    list_txs = [get_transaction_queue_entry(peer_id) for peer_id in peer_ids for _ in range(num_txs)]
    for tx in list_txs:
        assert tx.transaction_bytes is not None
        await transaction_queue.put(tx, bytes32(tx.transaction_bytes))  # as said above, we cheat a bit here

    assert transaction_queue._queue_length._value == total_txs  # check that all are included
    assert transaction_queue._index_to_peer_map == peer_ids  # make sure all peers are in the map

    # test failure case.
    with pytest.raises(TransactionQueueFull):
        await transaction_queue.put(get_transaction_queue_entry(peer_ids[0]), peer_ids[0])

    resulting_txs = []
    for _ in range(total_txs):
        resulting_txs.append(await transaction_queue.pop())

    assert transaction_queue._queue_length._value == 0  # check that all are removed
    assert transaction_queue._index_to_peer_map == []  # we should have removed all the peer ids


@pytest.mark.asyncio
async def test_queue_cleanup_and_fairness() -> None:
    transaction_queue = TransactionQueue(1000, log)
    num_peers = 1000
    num_txs = 100
    total_txs = num_txs * num_peers
    peer_ids: List[bytes32] = [get_peer_id() for _ in range(num_peers)]

    # 100 txs per peer
    list_txs = [get_transaction_queue_entry(peer_id) for peer_id in peer_ids for _ in range(num_txs)]
    for tx in list_txs:
        assert tx.transaction_bytes is not None
        await transaction_queue.put(tx, bytes32(tx.transaction_bytes))  # as said above, we cheat a bit here

    assert transaction_queue._queue_length._value == total_txs  # check that all are included
    assert transaction_queue._index_to_peer_map == peer_ids  # check that all peers are in the map

    # give random peers another transaction
    peer_index = sample(range(num_peers), 10)
    peer_index.sort()  # use a sorted list to avoid stupid complexities.
    selected_peers = [peer_ids[i] for i in peer_index]
    extra_txs = [get_transaction_queue_entry(peers) for peers in selected_peers]
    for tx in extra_txs:
        assert tx.transaction_bytes is not None
        await transaction_queue.put(tx, bytes32(tx.transaction_bytes))  # as said above, we cheat a bit here

    resulting_txs = []
    for _ in range(total_txs):
        resulting_txs.append(await transaction_queue.pop())

    assert transaction_queue._queue_length._value == 10  # check that all the first txs are removed for fairness.
    assert transaction_queue._index_to_peer_map == selected_peers  # only peers with 2 tx's.

    resulting_extra_txs = []
    for _ in range(10):
        resulting_extra_txs.append(await transaction_queue.pop())

    assert extra_txs == resulting_extra_txs  # validate that the extra txs are the same as the ones we put in.

    assert transaction_queue._queue_length._value == 0  # check that all tx's are removed
    assert transaction_queue._index_to_peer_map == []  # now there should be no peers in the map
