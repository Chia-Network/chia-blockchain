from __future__ import annotations

import asyncio
import logging
from random import sample
from secrets import token_bytes
from typing import Dict, List, Optional, Tuple

import aiohttp
import blspy
import pytest
import pytest_asyncio

from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.tx_processing_queue import TransactionQueue
from chia.protocols.shared_protocol import capabilities
from chia.server.outbound_message import Message, NodeType
from chia.server.server import ChiaServer, ssl_context_for_client
from chia.server.ssl_context import chia_ssl_ca_paths
from chia.server.ws_connection import WSChiaConnection
from chia.ssl.create_ssl import generate_ca_signed_cert
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.types.transaction_queue_entry import TransactionQueueEntry
from chia.util.config import load_config
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


async def get_dummy_peers(
    server: ChiaServer, num_peers: int = 1, self_hostname: str = "localhost"
) -> List[WSChiaConnection]:
    server_port = server.get_port()
    url = f"wss://{self_hostname}:{server_port}/ws"
    timeout = aiohttp.ClientTimeout(total=10)
    session = aiohttp.ClientSession(timeout=timeout)
    incoming_queue: asyncio.Queue[Tuple[Message, WSChiaConnection]] = asyncio.Queue()
    # this is all only used to get a web socket that we never use again.
    config = load_config(server.root_path, "config.yaml")
    chia_ca_crt_path, chia_ca_key_path = chia_ssl_ca_paths(server.root_path, config)
    dummy_crt_path = server.root_path / "dummy.crt"
    dummy_key_path = server.root_path / "dummy.key"
    generate_ca_signed_cert(
        chia_ca_crt_path.read_bytes(), chia_ca_key_path.read_bytes(), dummy_crt_path, dummy_key_path
    )
    ssl_context = ssl_context_for_client(chia_ca_crt_path, chia_ca_key_path, dummy_crt_path, dummy_key_path)
    ws = await session.ws_connect(url, autoclose=True, autoping=True, ssl=ssl_context)
    # we just reuse everything above, except for the peer id.
    peer_list: List[WSChiaConnection] = []
    for i in range(num_peers):
        peer_id = bytes32(token_bytes(32))  # random peer id for each peer.
        peer_list.append(
            WSChiaConnection(
                NodeType.FULL_NODE,
                ws,
                server_port,
                log,
                True,
                False,
                self_hostname,
                incoming_queue,
                lambda x, y: None,
                peer_id,
                100,
                30,
                local_capabilities_for_handshake=capabilities,
            )
        )
    return peer_list


def get_transaction_queue_entry(peer: Optional[WSChiaConnection] = None) -> TransactionQueueEntry:
    sb: SpendBundle = standard_spend_bundle
    return TransactionQueueEntry(
        sb,
        None,
        sb.name(),
        peer,
        False,
    )


class TestTransactionQueue:
    @pytest.fixture(scope="function")
    def transaction_queue(self) -> TransactionQueue:
        return TransactionQueue(1000, log)

    @pytest_asyncio.fixture(scope="function")
    async def get_server(self, node_with_params: FullNodeAPI) -> ChiaServer:
        return node_with_params.full_node.server

    @pytest.mark.asyncio
    async def test_local_txs(self, transaction_queue: TransactionQueue) -> None:
        # test 1 tx
        first_tx = get_transaction_queue_entry()
        await transaction_queue.put(first_tx)

        assert transaction_queue._index_to_peer_map == []
        assert transaction_queue._queue_length._value == 1

        result1 = await transaction_queue.pop()

        assert transaction_queue._queue_length._value == 0
        assert result1 == first_tx

        # test 100 txs
        num_txs = 100
        list_txs = [get_transaction_queue_entry() for _ in range(num_txs)]
        for tx in list_txs:
            await transaction_queue.put(tx)

        assert transaction_queue._queue_length._value == num_txs  # check that all are included
        assert transaction_queue._index_to_peer_map == []  # sanity checking

        resulting_txs = []
        for _ in range(num_txs):
            resulting_txs.append(await transaction_queue.pop())

        assert transaction_queue._queue_length._value == 0  # check that all are removed
        for i in range(num_txs):
            assert list_txs[i] == resulting_txs[i]

    @pytest.mark.asyncio
    async def test_one_peer(self, transaction_queue: TransactionQueue, get_server: ChiaServer) -> None:
        num_txs = 100
        peer: WSChiaConnection = (await get_dummy_peers(get_server))[0]
        peer_id = peer.peer_node_id  # generated random peer id.

        list_txs = [get_transaction_queue_entry(peer) for _ in range(num_txs)]
        for tx in list_txs:
            await transaction_queue.put(tx)

        assert transaction_queue._queue_length._value == num_txs  # check that all are included
        assert transaction_queue._index_to_peer_map == [peer_id]  # sanity checking

        resulting_txs = []
        for _ in range(num_txs):
            resulting_txs.append(await transaction_queue.pop())

        assert transaction_queue._queue_length._value == 0  # check that all are removed
        for i in range(num_txs):
            assert list_txs[i] == resulting_txs[i]

        await peer.close()

    @pytest.mark.asyncio
    async def test_lots_of_peers(self, transaction_queue: TransactionQueue, get_server: ChiaServer) -> None:
        num_peers = 1000
        num_txs = 100
        total_txs = num_txs * num_peers
        peers: List[WSChiaConnection] = await get_dummy_peers(get_server, num_peers)
        peer_ids = [peer.peer_node_id for peer in peers]

        list_txs = [get_transaction_queue_entry(peer) for peer in peers for _ in range(num_txs)]  # 100 txs per peer
        for tx in list_txs:
            await transaction_queue.put(tx)

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

        await peers[0].close()

    @pytest.mark.asyncio
    async def test_queue_cleanup(self, transaction_queue: TransactionQueue, get_server: ChiaServer) -> None:
        num_peers = 1000
        num_txs = 100
        total_txs = num_txs * num_peers
        peers: List[WSChiaConnection] = await get_dummy_peers(get_server, num_peers)
        peer_ids = [peer.peer_node_id for peer in peers]

        list_txs = [get_transaction_queue_entry(peer) for peer in peers for _ in range(num_txs)]  # 100 txs per peer
        for tx in list_txs:
            await transaction_queue.put(tx)

        assert transaction_queue._queue_length._value == total_txs  # check that all are included
        assert transaction_queue._index_to_peer_map == peer_ids  # check that all peers are in the map

        # add extra transactions for the cleanup test
        extra_tx_list = sample(range(num_peers), 5)
        extra_tx_list.sort()  # sort so that we can evaluate the results easier
        extra_txs = [get_transaction_queue_entry(peers[i]) for i in extra_tx_list]
        for tx in extra_txs:
            await transaction_queue.put(tx)

        resulting_txs = []
        for _ in range(total_txs):
            resulting_txs.append(await transaction_queue.pop())

        assert transaction_queue._queue_length._value == 5  # check that all the first txs are removed.
        assert transaction_queue._index_to_peer_map == [peer_ids[i] for i in extra_tx_list]  # only peers with 2 tx's.

        resulting_extra_txs = []
        for _ in range(5):
            resulting_extra_txs.append(await transaction_queue.pop())

        assert extra_txs == resulting_extra_txs  # validate that the extra txs are the same as the ones we put in.

        assert transaction_queue._queue_length._value == 0  # check that all tx's are removed
        assert transaction_queue._index_to_peer_map == []  # now there should be no peers in the map
        # There are 1000 peers, so each peer will have one transaction processed every 1000 iterations.
        for i in range(num_txs):
            assert list_txs[i] == resulting_txs[i * 1000]

        await peers[0].close()
