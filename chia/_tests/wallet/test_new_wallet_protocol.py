from __future__ import annotations

from asyncio import Queue
from dataclasses import dataclass
from random import Random
from typing import AsyncGenerator, Dict, List, Optional, OrderedDict, Set, Tuple

import pytest
from chia_rs import Coin, CoinState

from chia.protocols import wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message, NodeType
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.types.aliases import SimulatorFullNodeService, WalletService
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from tests.connection_utils import add_dummy_connection
from tests.wallet.simple_sync.test_simple_sync_protocol import get_all_messages_in_queue

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


ph0 = bytes32(b"\x00" * 32)
ph1 = bytes32(b"\x01" * 32)
ph2 = bytes32(b"\x02" * 32)
ph3 = bytes32(b"\x03" * 32)


@pytest.mark.anyio
async def test_puzzle_subscriptions(one_node: OneNode, self_hostname: str) -> None:
    simulator, incoming_queue, peer = await connect_to_simulator(one_node, self_hostname)
    subs = simulator.full_node.subscriptions

    ph0 = bytes32(b"\x00" * 32)
    ph1 = bytes32(b"\x01" * 32)
    ph2 = bytes32(b"\x02" * 32)
    ph3 = bytes32(b"\x03" * 32)

    await simulator.farm_blocks_to_puzzlehash(1)

    # Add puzzle subscriptions, ignore duplicates
    resp = await simulator.request_add_puzzle_subscriptions(
        wallet_protocol.RequestAddPuzzleSubscriptions([ph1, ph2, ph2]), peer
    )
    assert resp is not None

    assert subs.puzzle_subscriptions(peer.peer_node_id) == {ph1, ph2}

    # Puzzle hashes can be returned in any order, due to implementation details
    add_response = wallet_protocol.RespondAddPuzzleSubscriptions.from_bytes(resp.data)
    assert set(add_response.puzzle_hashes) == {ph1, ph2}

    # Add the other puzzle hash, as well as existing ones
    resp = await simulator.request_add_puzzle_subscriptions(
        wallet_protocol.RequestAddPuzzleSubscriptions([ph1, ph2, ph3]), peer
    )
    assert resp is not None

    add_response = wallet_protocol.RespondAddPuzzleSubscriptions.from_bytes(resp.data)
    assert add_response.puzzle_hashes == [ph3]

    assert subs.puzzle_subscriptions(peer.peer_node_id) == {ph1, ph2, ph3}

    # Farm blocks and get coin state updates
    await simulator.farm_blocks_to_puzzlehash(5, farm_to=ph1, guarantee_transaction_blocks=True)
    await simulator.farm_blocks_to_puzzlehash(4, farm_to=ph2, guarantee_transaction_blocks=True)
    await simulator.farm_blocks_to_puzzlehash(3, farm_to=ph3, guarantee_transaction_blocks=True)

    # Generate update for the previous block.
    await simulator.farm_blocks_to_puzzlehash(3, farm_to=ph0, guarantee_transaction_blocks=True)

    all_messages = await get_all_messages_in_queue(incoming_queue)
    coin_state_updates = [
        wallet_protocol.CoinStateUpdate.from_bytes(message.data)
        for message in all_messages
        if ProtocolMessageTypes(message.type).name == "coin_state_update"
    ]

    for update in coin_state_updates:
        assert len(update.items) == 2

    for update in coin_state_updates[0:5]:
        for item in update.items:
            assert item.coin.puzzle_hash == ph1

    for update in coin_state_updates[5:9]:
        for item in update.items:
            assert item.coin.puzzle_hash == ph2

    for update in coin_state_updates[9:12]:
        for item in update.items:
            assert item.coin.puzzle_hash == ph3

    # Remove puzzle subscriptions, ignore duplicates or missing subscriptions
    resp = await simulator.request_remove_puzzle_subscriptions(
        wallet_protocol.RequestRemovePuzzleSubscriptions([ph1, ph1, ph2]), peer
    )
    assert resp is not None

    remove_response = wallet_protocol.RespondRemovePuzzleSubscriptions.from_bytes(resp.data)
    assert set(remove_response.puzzle_hashes) == {ph1, ph2}

    assert subs.puzzle_subscriptions(peer.peer_node_id) == {ph3}

    # There should be no puzzle subscriptions now, so no more coin state updates
    await simulator.farm_blocks_to_puzzlehash(5, farm_to=ph1, guarantee_transaction_blocks=True)

    all_messages = await get_all_messages_in_queue(incoming_queue)
    coin_state_updates = [
        wallet_protocol.CoinStateUpdate.from_bytes(message.data)
        for message in all_messages
        if ProtocolMessageTypes(message.type).name == "coin_state_update"
    ]
    assert len(coin_state_updates) == 0

    # Clear all puzzle subscriptions.
    resp = await simulator.request_remove_puzzle_subscriptions(
        wallet_protocol.RequestRemovePuzzleSubscriptions(None), peer
    )
    assert resp is not None

    remove_response = wallet_protocol.RespondRemovePuzzleSubscriptions.from_bytes(resp.data)
    assert set(remove_response.puzzle_hashes) == {ph3}

    assert len(subs.puzzle_subscriptions(peer.peer_node_id)) == 0


@dataclass(frozen=True)
class PuzzleStateData:
    coin_states: List[CoinState]
    end_of_batch: bool
    next_height: uint32
    next_header_hash: Optional[bytes32]
    reorg: bool


async def sync_puzzle_hashes(
    puzzle_hashes: List[bytes32],
    *,
    min_height: uint32,
    header_hash: Optional[bytes32],
    filters: wallet_protocol.CoinStateFilters,
    subscribe_when_finished: bool = False,
    max_hashes_in_request: int = 100000,
    simulator: FullNodeSimulator,
    peer: WSChiaConnection,
) -> AsyncGenerator[PuzzleStateData, None]:
    remaining = puzzle_hashes.copy()

    while len(remaining) > 0:
        next_height: Optional[uint32] = min_height
        next_header_hash = header_hash

        while next_height is not None:
            resp = await simulator.request_puzzle_state(
                wallet_protocol.RequestPuzzleState(
                    remaining[:max_hashes_in_request],
                    next_height,
                    None,
                    next_header_hash,
                    filters,
                    subscribe_when_finished,
                ),
                peer,
            )
            assert resp is not None

            if ProtocolMessageTypes(resp.type).name == "reject_puzzle_state":
                rejection = wallet_protocol.RejectPuzzleState.from_bytes(resp.data)
                assert rejection.header_hash is not None
                yield PuzzleStateData(
                    coin_states=[],
                    end_of_batch=True,
                    next_height=min_height,
                    next_header_hash=header_hash,
                    reorg=True,
                )
                next_height = None
            else:
                response = wallet_protocol.RespondPuzzleState.from_bytes(resp.data)

                consumed = len(response.puzzle_hashes)
                assert set(response.puzzle_hashes) == set(remaining[:consumed])

                if response.next_height is not None:
                    assert response.next_header_hash is not None
                    next_height = response.next_height
                    next_header_hash = response.next_header_hash
                    yield PuzzleStateData(
                        coin_states=response.coin_states,
                        end_of_batch=False,
                        next_height=next_height,
                        next_header_hash=next_header_hash,
                        reorg=False,
                    )
                else:
                    remaining = remaining[consumed:]
                    yield PuzzleStateData(
                        coin_states=response.coin_states,
                        end_of_batch=True,
                        next_height=min_height,
                        next_header_hash=header_hash,
                        reorg=False,
                    )
                    next_height = None


@pytest.fixture(scope="module", params=[(0, 0), (1000, 2), (20000, 5)])
def coin_record_data(
    request: pytest.FixtureRequest,
) -> Tuple[List[bytes32], List[Tuple[bytes32, bytes]], Dict[bytes32, CoinRecord]]:
    puzzle_hashes: List[bytes32] = []
    hints: List[Tuple[bytes32, bytes]] = []
    coin_records: Dict[bytes32, CoinRecord] = dict()

    rng = Random(0)

    for i in range(request.param[0]):
        puzzle_hash = std_hash(i.to_bytes(4, "big"))
        puzzle_hashes.append(puzzle_hash)

        base_amount = rng.randint(0, 1000000000)

        for added_amount in range(request.param[1]):
            coin_ph = puzzle_hash

            if rng.choice([True, False]):
                coin_ph = std_hash(coin_ph)

            coin = Coin(bytes32(b"\0" * 32), coin_ph, base_amount + added_amount)

            coin_records[coin.name()] = CoinRecord(
                coin=coin,
                confirmed_block_index=uint32(i),
                spent_block_index=uint32(i + 100 if rng.choice([True, False]) else 0),
                coinbase=False,
                timestamp=uint64(rng.randint(1000, 100000000)),
            )

            if coin_ph != puzzle_hash:
                hints.append((coin.name(), puzzle_hash))

    return puzzle_hashes, hints, coin_records


@pytest.mark.parametrize(argnames="include_spent", argvalues=[True, False])
@pytest.mark.parametrize(argnames="include_unspent", argvalues=[True, False])
@pytest.mark.parametrize(argnames="include_hinted", argvalues=[True, False])
@pytest.mark.anyio
async def test_puzzle_state(
    one_node: OneNode,
    coin_record_data: Tuple[List[bytes32], List[Tuple[bytes32, bytes]], Dict[bytes32, CoinRecord]],
    self_hostname: str,
    include_spent: bool,
    include_unspent: bool,
    include_hinted: bool,
) -> None:
    # Setup simulator
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    # Add coin records and hints
    puzzle_hashes, hints, coin_records = coin_record_data
    await simulator.full_node.coin_store._add_coin_records(list(coin_records.values()))
    await simulator.full_node.hint_store.add_hints(hints)

    # Calculate expected coin records based on filters
    expected_coin_records: Dict[bytes32, CoinRecord] = dict()

    for coin_id, coin_record in coin_records.items():
        if not include_spent and coin_record.spent_block_index > 0:
            continue
        if not include_unspent and coin_record.spent_block_index == 0:
            continue
        if not include_hinted and coin_record.coin.puzzle_hash not in puzzle_hashes:
            continue

        expected_coin_records[coin_id] = coin_record

    # Sync all coin states
    coin_ids: Set[bytes32] = set()
    last_height = -1

    async for batch in sync_puzzle_hashes(
        puzzle_hashes,
        min_height=uint32(0),
        header_hash=None,
        filters=wallet_protocol.CoinStateFilters(include_spent, include_unspent, include_hinted),
        simulator=simulator,
        peer=peer,
    ):
        for coin_state in batch.coin_states:
            coin_id = coin_state.coin.name()
            coin_ids.add(coin_id)

            coin_record = coin_records[coin_id]
            assert coin_record.coin_state == coin_state

            height = max(coin_state.created_height or 0, coin_state.spent_height or 0)

            assert height > last_height
            if batch.end_of_batch:
                last_height = -1

    assert len(coin_ids) == len(expected_coin_records)


@pytest.mark.anyio
async def test_coin_state(one_node: OneNode, self_hostname: str) -> None:
    simulator, _, peer = await connect_to_simulator(one_node, self_hostname)

    # Add more than the max response coin records
    coin_records: OrderedDict[bytes32, CoinRecord] = OrderedDict()
    for i in range(110000):
        coin_record = CoinRecord(
            coin=Coin(bytes32(b"\0" * 32), ph1, i),
            confirmed_block_index=uint32(i),
            spent_block_index=uint32(0),
            coinbase=False,
            timestamp=uint64(472618),
        )
        coin_records[coin_record.coin.name()] = coin_record

    await simulator.full_node.coin_store._add_coin_records(list(coin_records.values()))

    # Fetch the coin records using the wallet protocol,
    # only after height 10000, so that the limit of 100000 isn't exceeded
    resp = await simulator.request_coin_state(
        wallet_protocol.RequestCoinState(list(coin_records.keys()), uint32(10000), None, None, subscribe=False), peer
    )
    assert resp is not None

    response = wallet_protocol.RespondCoinState.from_bytes(resp.data)

    # We did still search for all of the coin ids.
    assert set(response.coin_ids) == set(coin_records.keys())
    assert len(response.coin_states) == len(coin_records) - 10000

    for coin_state in response.coin_states:
        coin_record = coin_records[coin_state.coin.name()]
        assert coin_record.coin_state == coin_state

    # The expected behavior when the limit is exceeded, is to skip the rest
    resp = await simulator.request_coin_state(
        wallet_protocol.RequestCoinState(list(coin_records.keys()), uint32(0), None, None, subscribe=False), peer
    )
    assert resp is not None

    response = wallet_protocol.RespondCoinState.from_bytes(resp.data)
