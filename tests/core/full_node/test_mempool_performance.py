# flake8: noqa: F811, F401
"""
Commenting out until clvm_rs is in.

import asyncio
import time

import pytest
import logging

from src.protocols import full_node_protocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16
from src.wallet.transaction_record import TransactionRecord
from tests.core.full_node.test_full_node import connect_and_get_peer
from tests.setup_nodes import bt, self_hostname, setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert
from tests.core.fixtures import (
    default_400_blocks,
)


def wallet_height_at_least(wallet_node, h):
    height = wallet_node.wallet_state_manager.blockchain.peak_sub_height
    if height == h:
        return True
    return False


log = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class XTestMempoolPerformance:
    @pytest.fixture(scope="module")
    async def wallet_nodes(self):
        key_seed = bt.farmer_master_sk_entropy
        async for _ in setup_simulators_and_wallets(2, 1, {}, key_seed=key_seed):
            yield _

    @pytest.mark.asyncio
    async def test_mempool_update_performance(self, wallet_nodes, default_400_blocks):
        blocks = default_400_blocks
        full_nodes, wallets = wallet_nodes
        wallet_node = wallets[0][0]
        wallet_server = wallets[0][1]
        full_node_api_1 = full_nodes[0]
        full_node_api_2 = full_nodes[1]
        server_1 = full_node_api_1.full_node.server
        server_2 = full_node_api_2.full_node.server
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        for block in blocks:
            await full_node_api_1.full_node.respond_sub_block(full_node_protocol.RespondSubBlock(block))

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        await time_out_assert(60, wallet_height_at_least, True, wallet_node, 399)

        big_transaction: TransactionRecord = await wallet.generate_signed_transaction(40000000000000, ph, 2213)

        peer = await connect_and_get_peer(server_1, server_2)
        await full_node_api_1.respond_transaction(
            full_node_protocol.RespondTransaction(big_transaction.spend_bundle), peer, test=True
        )
        cons = list(server_1.all_connections.values())[:]
        for con in cons:
            await con.close()

        # blocks = bt.get_consecutive_blocks(3, blocks)
        # await full_node_api_1.full_node.respond_sub_block(full_node_protocol.respondsubblock(blocks[-3]))
        #
        # for block in blocks[-2:]:
        #     start_t_2 = time.time()
        #     await full_node_api_1.full_node.respond_sub_block(full_node_protocol.respondsubblock(block))
        #     assert time.time() - start_t_2 < 1
"""
