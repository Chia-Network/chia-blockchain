from __future__ import annotations

from asyncio import Queue
from dataclasses import dataclass
from random import Random
from typing import AsyncGenerator, Dict, List, Optional, OrderedDict, Set, Tuple

import pytest
from chia_rs import Coin, CoinState

from chia._tests.connection_utils import add_dummy_connection
from chia.protocols import wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message, NodeType
from chia.server.ws_connection import WSChiaConnection
from chia.simulator import simulator_protocol
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.aliases import SimulatorFullNodeService, WalletService
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64

OneNode = Tuple[List[SimulatorFullNodeService], List[WalletService], BlockTools]


async def connect_to_simulator(
    one_node: OneNode, self_hostname: str
) -> Tuple[FullNodeSimulator, Queue[Message], WSChiaConnection]:
    [full_node_service], _, _ = one_node

    full_node_api = full_node_service._api
    fn_server = full_node_api.server

    incoming_queue, peer_id = await add_dummy_connection(fn_server, self_hostname, 41723, NodeType.WALLET)
    peer = fn_server.all_connections[peer_id]

    return full_node_api, incoming_queue, peer


@pytest.mark.anyio
async def test_puzzle_subscriptions(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)
    subs = simulator.full_node.subscriptions

    await simulator.farm_blocks_to_puzzlehash(1)

    ph1 = bytes32(b"\x01" * 32)
    ph2 = bytes32(b"\x02" * 32)
    ph3 = bytes32(b"\x03" * 32)

    # Add puzzle subscriptions, ignore duplicates
    # Response can be in any order
    resp = await simulator.request_add_puzzle_subscriptions(
        wallet_protocol.RequestAddPuzzleSubscriptions([ph1, ph2, ph2]), peer
    )
    assert resp is not None

    add_response = wallet_protocol.RespondAddPuzzleSubscriptions.from_bytes(resp.data)
    assert set(add_response.puzzle_hashes) == {ph1, ph2}

    assert subs.puzzle_subscriptions(peer.peer_node_id) == {ph1, ph2}

    # Add another puzzle hash and existing ones
    resp = await simulator.request_add_puzzle_subscriptions(
        wallet_protocol.RequestAddPuzzleSubscriptions([ph1, ph2, ph3]), peer
    )
    assert resp is not None

    add_response = wallet_protocol.RespondAddPuzzleSubscriptions.from_bytes(resp.data)
    assert set(add_response.puzzle_hashes) == {ph3}

    assert subs.puzzle_subscriptions(peer.peer_node_id) == {ph1, ph2, ph3}

    # Remove puzzle subscriptions
    # Ignore duplicates or missing subscriptions
    resp = await simulator.request_remove_puzzle_subscriptions(
        wallet_protocol.RequestRemovePuzzleSubscriptions([ph1, ph1, ph2]), peer
    )
    assert resp is not None

    remove_response = wallet_protocol.RespondRemovePuzzleSubscriptions.from_bytes(resp.data)
    assert set(remove_response.puzzle_hashes) == {ph1, ph2}

    assert subs.puzzle_subscriptions(peer.peer_node_id) == {ph3}

    # Clear all puzzle subscriptions.
    resp = await simulator.request_remove_puzzle_subscriptions(
        wallet_protocol.RequestRemovePuzzleSubscriptions(None), peer
    )
    assert resp is not None

    remove_response = wallet_protocol.RespondRemovePuzzleSubscriptions.from_bytes(resp.data)
    assert set(remove_response.puzzle_hashes) == {ph3}

    assert len(subs.puzzle_subscriptions(peer.peer_node_id)) == 0


@pytest.mark.anyio
async def test_coin_subscriptions(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)
    subs = simulator.full_node.subscriptions

    await simulator.farm_blocks_to_puzzlehash(1)

    coin1 = bytes32(b"\x01" * 32)
    coin2 = bytes32(b"\x02" * 32)
    coin3 = bytes32(b"\x03" * 32)

    # Add coin subscriptions, ignore duplicates
    # Response can be in any order
    resp = await simulator.request_add_coin_subscriptions(
        wallet_protocol.RequestAddCoinSubscriptions([coin1, coin2, coin2]), peer
    )
    assert resp is not None

    add_response = wallet_protocol.RespondAddCoinSubscriptions.from_bytes(resp.data)
    assert set(add_response.coin_ids) == {coin1, coin2}

    assert subs.coin_subscriptions(peer.peer_node_id) == {coin1, coin2}

    # Add another puzzle hash and existing ones
    resp = await simulator.request_add_coin_subscriptions(
        wallet_protocol.RequestAddCoinSubscriptions([coin1, coin2, coin3]), peer
    )
    assert resp is not None

    add_response = wallet_protocol.RespondAddCoinSubscriptions.from_bytes(resp.data)
    assert set(add_response.coin_ids) == {coin3}

    assert subs.coin_subscriptions(peer.peer_node_id) == {coin1, coin2, coin3}

    # Remove coin subscriptions
    # Ignore duplicates or missing subscriptions
    resp = await simulator.request_remove_coin_subscriptions(
        wallet_protocol.RequestRemoveCoinSubscriptions([coin1, coin1, coin2]), peer
    )
    assert resp is not None

    remove_response = wallet_protocol.RespondRemoveCoinSubscriptions.from_bytes(resp.data)
    assert set(remove_response.coin_ids) == {coin1, coin2}

    assert subs.coin_subscriptions(peer.peer_node_id) == {coin3}

    # Clear all coin subscriptions.
    resp = await simulator.request_remove_coin_subscriptions(wallet_protocol.RequestRemoveCoinSubscriptions(None), peer)
    assert resp is not None

    remove_response = wallet_protocol.RespondRemoveCoinSubscriptions.from_bytes(resp.data)
    assert set(remove_response.coin_ids) == {coin3}

    assert len(subs.coin_subscriptions(peer.peer_node_id)) == 0


@pytest.mark.anyio
async def test_subscription_limits(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)
    subs = simulator.full_node.subscriptions

    await simulator.farm_blocks_to_puzzlehash(1)

    max_subs = simulator.max_subscriptions(peer)
    puzzle_hashes = [std_hash(i.to_bytes(4, byteorder="big", signed=False)) for i in range(max_subs + 100)]

    # Add puzzle subscriptions to the limit
    first_batch = puzzle_hashes[:max_subs]
    first_batch_set = set(first_batch)

    resp = await simulator.request_add_puzzle_subscriptions(
        wallet_protocol.RequestAddPuzzleSubscriptions(first_batch), peer
    )
    assert resp is not None

    add_ph_response = wallet_protocol.RespondAddPuzzleSubscriptions.from_bytes(resp.data)
    assert set(add_ph_response.puzzle_hashes) == first_batch_set

    assert subs.puzzle_subscriptions(peer.peer_node_id) == first_batch_set

    # Try to add the remaining subscriptions
    resp = await simulator.request_add_puzzle_subscriptions(
        wallet_protocol.RequestAddPuzzleSubscriptions(puzzle_hashes[max_subs:]), peer
    )
    assert resp is not None

    overflow_ph_response = wallet_protocol.RespondAddPuzzleSubscriptions.from_bytes(resp.data)
    assert len(overflow_ph_response.puzzle_hashes) == 0

    assert subs.puzzle_subscriptions(peer.peer_node_id) == first_batch_set

    # Try to overflow with coin subscriptions
    resp = await simulator.request_add_coin_subscriptions(
        wallet_protocol.RequestAddCoinSubscriptions([bytes32(b"coin" * 8)]), peer
    )
    assert resp is not None

    overflow_coin_response = wallet_protocol.RespondAddCoinSubscriptions.from_bytes(resp.data)
    assert len(overflow_coin_response.coin_ids) == 0


@pytest.mark.anyio
async def test_request_coin_state(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    genesis = simulator.full_node.blockchain.constants.GENESIS_CHALLENGE
    assert genesis is not None

    # Add coin records
    coin_records = [
        CoinRecord(
            coin=Coin(bytes32(b"\0" * 32), bytes32(b"\0" * 32), uint64(i)),
            confirmed_block_index=uint32(1),
            spent_block_index=uint32(1 if i % 2 == 0 else 0),
            coinbase=False,
            timestamp=uint64(0),
        )
        for i in range(50)
    ]
    ignored_coin = CoinRecord(
        coin=Coin(bytes32(b"\1" * 32), bytes32(b"\1" * 32), uint64(1)),
        confirmed_block_index=uint32(1),
        spent_block_index=uint32(2),
        coinbase=False,
        timestamp=uint64(1),
    )
    await simulator.full_node.coin_store._add_coin_records(coin_records + [ignored_coin])

    # Request no coin states
    resp = await simulator.request_coin_state(wallet_protocol.RequestCoinState([], None, genesis, False), peer)
    assert resp is not None

    response = wallet_protocol.RespondCoinState.from_bytes(resp.data)

    assert len(response.coin_ids) == 0
    assert len(response.coin_states) == 0

    # Request coin state
    coin_ids = [cr.coin.name() for cr in coin_records]

    resp = await simulator.request_coin_state(wallet_protocol.RequestCoinState(coin_ids, None, genesis, False), peer)
    assert resp is not None

    response = wallet_protocol.RespondCoinState.from_bytes(resp.data)

    assert response.coin_ids == coin_ids
    assert set(response.coin_states) == {cr.coin_state for cr in coin_records}


@pytest.mark.anyio
async def test_request_coin_state_and_subscribe(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    genesis = simulator.full_node.blockchain.constants.GENESIS_CHALLENGE
    assert genesis is not None

    c1 = bytes32(b"1" * 32)
    c2 = bytes32(b"2" * 32)
    c3 = bytes32(b"3" * 32)
    c4 = bytes32(b"4" * 32)

    # Request initial state (empty in this case) and subscribe
    resp = await simulator.request_coin_state(
        wallet_protocol.RequestCoinState([c1, c2, c3, c3, c4], None, genesis, True), peer
    )
    assert resp is not None

    response = wallet_protocol.RespondCoinState.from_bytes(resp.data)

    assert len(response.coin_ids) == 4
    assert len(response.coin_states) == 0

    # Make sure the subscriptions were added
    assert simulator.full_node.subscriptions.coin_subscriptions(peer.peer_node_id) == {c1, c2, c3, c4}


@pytest.mark.anyio
async def test_request_coin_state_reorg(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    # Farm block
    await simulator.farm_blocks_to_puzzlehash(8)

    header_hash = simulator.full_node.blockchain.height_to_hash(uint32(5))
    assert header_hash is not None

    # Reorg
    await simulator.reorg_from_index_to_new_index(
        simulator_protocol.ReorgProtocol(uint32(3), uint32(10), bytes32(b"\1" * 32), bytes32(b"\0" * 32))
    )

    # Request coin state, should reject due to reorg
    resp = await simulator.request_coin_state(wallet_protocol.RequestCoinState([], uint32(5), header_hash, False), peer)
    assert resp is not None

    assert wallet_protocol.RejectCoinState.from_bytes(resp.data) == wallet_protocol.RejectCoinState()


@pytest.mark.anyio
async def test_request_coin_state_limit(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    # Farm blocks 0-11 and make sure the last one is farmed
    await simulator.farm_blocks_to_puzzlehash(12)

    h0 = simulator.full_node.blockchain.height_to_hash(uint32(0))
    assert h0 is not None

    h1 = simulator.full_node.blockchain.height_to_hash(uint32(1))
    assert h1 is not None

    # Add more than the max response coin records
    coin_records: OrderedDict[bytes32, CoinRecord] = OrderedDict()
    for height in range(1, 12):
        for i in range(10000):
            coin_record = CoinRecord(
                coin=Coin(std_hash(i.to_bytes(4, "big")), std_hash(height.to_bytes(4, "big")), uint64(i)),
                confirmed_block_index=uint32(height),
                spent_block_index=uint32(0),
                coinbase=False,
                timestamp=uint64(472618),
            )
            coin_records[coin_record.coin.name()] = coin_record

    await simulator.full_node.coin_store._add_coin_records(list(coin_records.values()))

    # Fetch the coin records using the wallet protocol,
    # only after height 10000, so that the limit of 100000 isn't exceeded
    resp = await simulator.request_coin_state(
        wallet_protocol.RequestCoinState(list(coin_records.keys()), uint32(1), h1, False),
        peer,
    )
    assert resp is not None

    response = wallet_protocol.RespondCoinState.from_bytes(resp.data)

    assert set(response.coin_ids) == set(coin_records.keys())
    assert len(response.coin_states) == len(coin_records) - 10000

    for coin_state in response.coin_states:
        coin_record = coin_records[coin_state.coin.name()]
        assert coin_record.coin_state == coin_state
        assert coin_record.confirmed_block_index > 1

    # The expected behavior when the limit is exceeded, is to skip the rest
    # The order is not guaranteed, so it can't be relied upon here
    # Just request the remaining coin ids in subsequent request(s)
    resp = await simulator.request_coin_state(
        wallet_protocol.RequestCoinState(list(coin_records.keys()), uint32(0), h0, False),
        peer,
    )
    assert resp is not None

    response = wallet_protocol.RespondCoinState.from_bytes(resp.data)

    assert set(response.coin_ids) == set(coin_records.keys())
    assert len(response.coin_states) == len(coin_records) - 10000

    for coin_state in response.coin_states:
        coin_record = coin_records[coin_state.coin.name()]
        assert coin_record.coin_state == coin_state


@pytest.mark.anyio
async def test_request_puzzle_state(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    # Farm block to a puzzle hash we aren't looking at
    await simulator.farm_blocks_to_puzzlehash(3, farm_to=bytes32(b"\x0A" * 32))

    genesis = simulator.full_node.blockchain.constants.GENESIS_CHALLENGE

    peak_height = simulator.full_node.blockchain.get_peak_height()
    assert peak_height is not None

    peak_header_hash = simulator.full_node.blockchain.height_to_hash(peak_height)
    assert peak_header_hash is not None

    # Add coin records
    coin_records: List[CoinRecord] = []
    puzzle_hashes: List[bytes32] = []

    for ph_i in range(10):
        puzzle_hash = bytes32(ph_i.to_bytes(1, "big") * 32)
        puzzle_hashes.append(puzzle_hash)

        for i in range(5):
            coin_records.append(
                CoinRecord(
                    coin=Coin(bytes32(b"\0" * 32), puzzle_hash, uint64(i)),
                    confirmed_block_index=uint32(1),
                    spent_block_index=uint32(1 if i % 2 == 0 else 0),
                    coinbase=False,
                    timestamp=uint64(0),
                )
            )

    ignored_coin = CoinRecord(
        coin=Coin(bytes32(b"\1" * 32), bytes32(b"\1" * 31 + b"\0"), uint64(1)),
        confirmed_block_index=uint32(1),
        spent_block_index=uint32(2),
        coinbase=False,
        timestamp=uint64(1),
    )

    await simulator.full_node.coin_store._add_coin_records(coin_records + [ignored_coin])

    # We already test permutations of CoinStateFilters in the CoinStore tests
    # So it's redundant to do so here
    filters = wallet_protocol.CoinStateFilters(True, True, True, uint64(0))

    # Request no coin states
    resp = await simulator.request_puzzle_state(
        wallet_protocol.RequestPuzzleState([], None, genesis, filters, False), peer
    )
    assert resp is not None

    response = wallet_protocol.RespondPuzzleState.from_bytes(resp.data)

    # The peak height and header hash is returned when you are caught up to the peak
    assert response == wallet_protocol.RespondPuzzleState([], peak_height, peak_header_hash, True, [])

    # Request coin state
    resp = await simulator.request_puzzle_state(
        wallet_protocol.RequestPuzzleState(puzzle_hashes, None, genesis, filters, False), peer
    )
    assert resp is not None

    response = wallet_protocol.RespondPuzzleState.from_bytes(resp.data)

    assert response.puzzle_hashes == puzzle_hashes
    assert set(response.coin_states) == {cr.coin_state for cr in coin_records}

    assert response.height == peak_height
    assert response.header_hash == peak_header_hash

    assert response.is_finished


@pytest.mark.anyio
async def test_request_puzzle_state_and_subscribe(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    # You have to farm a block so there is a peak.
    # Otherwise you will get an AssertionError from `request_puzzle_state`.
    await simulator.farm_blocks_to_puzzlehash(1)

    genesis = simulator.full_node.blockchain.constants.GENESIS_CHALLENGE
    assert genesis is not None

    ph1 = bytes32(b"1" * 32)
    ph2 = bytes32(b"2" * 32)
    ph3 = bytes32(b"3" * 32)
    ph4 = bytes32(b"4" * 32)

    # Request initial state (empty in this case) and subscribe
    resp = await simulator.request_puzzle_state(
        wallet_protocol.RequestPuzzleState(
            [ph1, ph2, ph3, ph3, ph4],
            None,
            genesis,
            wallet_protocol.CoinStateFilters(True, True, True, uint64(0)),
            True,
        ),
        peer,
    )
    assert resp is not None

    response = wallet_protocol.RespondPuzzleState.from_bytes(resp.data)

    assert len(response.puzzle_hashes) == 4
    assert len(response.coin_states) == 0

    # Make sure the subscriptions were added
    assert simulator.full_node.subscriptions.puzzle_subscriptions(peer.peer_node_id) == {ph1, ph2, ph3, ph4}


@pytest.mark.anyio
async def test_request_puzzle_state_reorg(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    # Farm block
    await simulator.farm_blocks_to_puzzlehash(8)

    header_hash = simulator.full_node.blockchain.height_to_hash(uint32(5))
    assert header_hash is not None

    # Reorg
    await simulator.reorg_from_index_to_new_index(
        simulator_protocol.ReorgProtocol(uint32(3), uint32(10), bytes32(b"\1" * 32), bytes32(b"\0" * 32))
    )

    # Request coin state, should reject due to reorg
    resp = await simulator.request_puzzle_state(
        wallet_protocol.RequestPuzzleState(
            [], uint32(5), header_hash, wallet_protocol.CoinStateFilters(True, True, True, uint64(0)), False
        ),
        peer,
    )
    assert resp is not None

    assert wallet_protocol.RejectPuzzleState.from_bytes(resp.data) == wallet_protocol.RejectPuzzleState()


@pytest.mark.anyio
async def test_request_puzzle_state_limit(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    # Farm blocks 0-11 and make sure the last one is farmed
    await simulator.farm_blocks_to_puzzlehash(12)

    h0 = simulator.full_node.blockchain.height_to_hash(uint32(0))
    assert h0 is not None

    h1 = simulator.full_node.blockchain.height_to_hash(uint32(1))
    assert h1 is not None

    # Add more than the max response coin records
    coin_records: OrderedDict[bytes32, CoinRecord] = OrderedDict()
    ph = bytes32(b"\1" * 32)

    for height in range(1, 12):
        for i in range(10000):
            coin_record = CoinRecord(
                coin=Coin(std_hash(i.to_bytes(4, "big")), ph, uint64(height)),
                confirmed_block_index=uint32(height),
                spent_block_index=uint32(0),
                coinbase=False,
                timestamp=uint64(472618),
            )
            coin_records[coin_record.coin.name()] = coin_record

    await simulator.full_node.coin_store._add_coin_records(list(coin_records.values()))

    # Fetch the coin records using the wallet protocol,
    # only after height 10000, so that the limit of 100000 isn't exceeded
    resp = await simulator.request_puzzle_state(
        wallet_protocol.RequestPuzzleState(
            [ph], uint32(1), h1, wallet_protocol.CoinStateFilters(True, True, True, uint64(0)), False
        ),
        peer,
    )
    assert resp is not None

    response = wallet_protocol.RespondPuzzleState.from_bytes(resp.data)

    assert response.puzzle_hashes == [ph]
    assert len(response.coin_states) == len(coin_records) - 10000

    for coin_state in response.coin_states:
        coin_record = coin_records[coin_state.coin.name()]
        assert coin_record.coin_state == coin_state
        assert coin_record.confirmed_block_index > 1

    # The expected behavior when the limit is exceeded, is to skip the rest
    resp = await simulator.request_puzzle_state(
        wallet_protocol.RequestPuzzleState(
            [ph],
            uint32(0),
            h0,
            wallet_protocol.CoinStateFilters(True, True, True, uint64(0)),
            False,
        ),
        peer,
    )
    assert resp is not None

    response = wallet_protocol.RespondPuzzleState.from_bytes(resp.data)

    assert response.puzzle_hashes == [ph]
    assert len(response.coin_states) == len(coin_records) - 10000

    for coin_state in response.coin_states:
        coin_record = coin_records[coin_state.coin.name()]
        assert coin_record.coin_state == coin_state
        # Unlike requesting coin state by ids, the order is enforced here so block 11 should be excluded
        assert coin_record.confirmed_block_index <= 10


@dataclass(frozen=True)
class PuzzleStateData:
    coin_states: List[CoinState]
    end_of_batch: bool
    previous_height: Optional[uint32]
    header_hash: Optional[bytes32]
    reorg: bool


async def sync_puzzle_hashes(
    puzzle_hashes: List[bytes32],
    *,
    initial_previous_height: Optional[uint32],
    initial_header_hash: bytes32,
    filters: wallet_protocol.CoinStateFilters,
    subscribe_when_finished: bool = False,
    max_hashes_in_request: int = 15000,
    simulator: FullNodeSimulator,
    peer: WSChiaConnection,
) -> AsyncGenerator[PuzzleStateData, None]:
    remaining = puzzle_hashes.copy()

    while len(remaining) > 0:
        previous_height = initial_previous_height
        previous_header_hash = initial_header_hash
        is_finished = False

        while not is_finished:
            resp = await simulator.request_puzzle_state(
                wallet_protocol.RequestPuzzleState(
                    remaining[:max_hashes_in_request],
                    previous_height,
                    previous_header_hash,
                    filters,
                    subscribe_when_finished,
                ),
                peer,
            )
            assert resp is not None

            if ProtocolMessageTypes(resp.type).name == "reject_puzzle_state":
                # Validate response
                wallet_protocol.RejectPuzzleState.from_bytes(resp.data)

                yield PuzzleStateData(
                    coin_states=[],
                    end_of_batch=True,
                    previous_height=initial_previous_height,
                    header_hash=initial_header_hash,
                    reorg=True,
                )
                return
            else:
                response = wallet_protocol.RespondPuzzleState.from_bytes(resp.data)

                consumed = len(response.puzzle_hashes)
                assert set(response.puzzle_hashes) == set(remaining[:consumed])

                if not response.is_finished:
                    previous_height = response.height
                    previous_header_hash = response.header_hash
                    yield PuzzleStateData(
                        coin_states=response.coin_states,
                        end_of_batch=False,
                        previous_height=previous_height,
                        header_hash=previous_header_hash,
                        reorg=False,
                    )
                else:
                    remaining = remaining[consumed:]
                    yield PuzzleStateData(
                        coin_states=response.coin_states,
                        end_of_batch=True,
                        previous_height=previous_height,
                        header_hash=previous_header_hash,
                        reorg=False,
                    )
                    is_finished = True


@pytest.mark.anyio
@pytest.mark.parametrize("block_count,coins_per_block", [(0, 0), (5, 100), (3000, 3), (25000, 1)])
async def test_sync_puzzle_state(one_node: OneNode, self_hostname: str, block_count: int, coins_per_block: int) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    # Generate coin records
    puzzle_hashes: List[bytes32] = []
    hints: List[Tuple[bytes32, bytes]] = []
    coin_records: Dict[bytes32, CoinRecord] = dict()

    rng = Random(0)

    # Skip block 0 because it's skipped by `RequestPuzzleState`.
    for i in range(1, block_count + 1):
        puzzle_hash = std_hash(i.to_bytes(4, "big"))
        puzzle_hashes.append(puzzle_hash)

        base_amount = rng.randint(0, 1000000000)

        for added_amount in range(coins_per_block):
            coin_ph = puzzle_hash

            # Weight toward normal puzzle hash.
            if rng.choice([True, False, False, False, False]):
                coin_ph = std_hash(coin_ph)

            coin = Coin(bytes32(b"\0" * 32), coin_ph, uint64(base_amount + added_amount))

            coin_records[coin.name()] = CoinRecord(
                coin=coin,
                confirmed_block_index=uint32(i),
                spent_block_index=uint32(i + 100 if rng.choice([True, False]) else 0),
                coinbase=False,
                timestamp=uint64(rng.randint(1000, 100000000)),
            )

            if coin_ph != puzzle_hash:
                hints.append((coin.name(), puzzle_hash))

    await simulator.full_node.coin_store._add_coin_records(list(coin_records.values()))
    await simulator.full_node.hint_store.add_hints(hints)

    # Farm peak
    await simulator.farm_blocks_to_puzzlehash(1)

    genesis = simulator.full_node.blockchain.constants.GENESIS_CHALLENGE

    async def run_test(include_spent: bool, include_unspent: bool, include_hinted: bool, min_amount: uint64) -> None:
        # Calculate expected coin records based on filters
        expected_coin_records: Dict[bytes32, CoinRecord] = dict()

        for coin_id, coin_record in coin_records.items():
            if not include_spent and coin_record.spent_block_index > 0:
                continue
            if not include_unspent and coin_record.spent_block_index == 0:
                continue
            if not include_hinted and coin_record.coin.puzzle_hash not in puzzle_hashes:
                continue
            if coin_record.coin.amount < min_amount:
                continue

            expected_coin_records[coin_id] = coin_record

        # Sync all coin states
        coin_ids: Set[bytes32] = set()
        last_height = -1

        async for batch in sync_puzzle_hashes(
            puzzle_hashes,
            initial_previous_height=None,
            initial_header_hash=genesis,
            filters=wallet_protocol.CoinStateFilters(include_spent, include_unspent, include_hinted, min_amount),
            simulator=simulator,
            peer=peer,
        ):
            assert not batch.reorg

            for coin_state in batch.coin_states:
                coin_id = coin_state.coin.name()
                coin_ids.add(coin_id)

                coin_record = expected_coin_records[coin_id]
                assert coin_record.coin_state == coin_state

                height = max(coin_state.created_height or 0, coin_state.spent_height or 0)

                assert height > last_height
                if batch.end_of_batch:
                    last_height = -1

        assert len(coin_ids) == len(expected_coin_records)

    for include_spent in [True, False]:
        for include_unspent in [True, False]:
            for include_hinted in [True, False]:
                for min_amount in [0, 100000, 500000000]:
                    await run_test(include_spent, include_unspent, include_hinted, uint64(min_amount))
