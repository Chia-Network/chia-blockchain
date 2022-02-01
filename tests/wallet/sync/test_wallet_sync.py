# flake8: noqa: F811, F401
import asyncio

import pytest
from colorlog import getLogger

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.protocols import full_node_protocol
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32
from chia.wallet.wallet_state_manager import WalletStateManager
from tests.connection_utils import disconnect_all_and_reconnect
from tests.setup_nodes import bt, self_hostname, setup_node_and_wallet, setup_simulators_and_wallets, test_constants
from tests.time_out_assert import time_out_assert


def wallet_height_at_least(wallet_node, h):
    height = wallet_node.wallet_state_manager.blockchain.get_peak_height()
    if height == h:
        return True
    return False


log = getLogger(__name__)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestWalletSync:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_node_and_wallet(test_constants):
            yield _

    @pytest.fixture(scope="function")
    async def wallet_node_simulator(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def wallet_node_starting_height(self):
        async for _ in setup_node_and_wallet(test_constants, starting_height=100):
            yield _

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_basic_sync_wallet(self, wallet_node, default_400_blocks, trusted):

        full_node_api, wallet_node, full_node_server, wallet_server = wallet_node

        for block in default_400_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1.
        await time_out_assert(100, wallet_height_at_least, True, wallet_node, len(default_400_blocks) - 1)

        # Tests a reorg with the wallet
        num_blocks = 30
        blocks_reorg = bt.get_consecutive_blocks(num_blocks, block_list_input=default_400_blocks[:-5])
        for i in range(1, len(blocks_reorg)):
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks_reorg[i]))

        await disconnect_all_and_reconnect(wallet_server, full_node_server)

        await time_out_assert(
            100, wallet_height_at_least, True, wallet_node, len(default_400_blocks) + num_blocks - 5 - 1
        )

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_almost_recent(self, wallet_node, default_1000_blocks, trusted):
        # Tests the edge case of receiving funds right before the recent blocks  in weight proof
        full_node_api, wallet_node, full_node_server, wallet_server = wallet_node

        for block in default_1000_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}

        # Tests a reorg with the wallet
        num_blocks = 20
        new_blocks = bt.get_consecutive_blocks(
            num_blocks, block_list_input=default_1000_blocks, pool_reward_puzzle_hash=ph
        )
        for i in range(1000, len(new_blocks)):
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(new_blocks[i]))

        new_blocks = bt.get_consecutive_blocks(
            test_constants.WEIGHT_PROOF_RECENT_BLOCKS + 10, block_list_input=new_blocks
        )
        for i in range(1020, len(new_blocks)):
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(new_blocks[i]))

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        await time_out_assert(30, wallet.get_confirmed_balance, 20 * calculate_pool_reward(1000))

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_backtrack_sync_wallet(self, wallet_node, default_400_blocks, trusted):
        full_node_api, wallet_node, full_node_server, wallet_server = wallet_node
        for block in default_400_blocks[:20]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1.
        await time_out_assert(100, wallet_height_at_least, True, wallet_node, 19)

    # Tests a reorg with the wallet
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_short_batch_sync_wallet(self, wallet_node, default_400_blocks, trusted):
        full_node_api, wallet_node, full_node_server, wallet_server = wallet_node

        for block in default_400_blocks[:200]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))
        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1.
        await time_out_assert(100, wallet_height_at_least, True, wallet_node, 199)
        # Tests a reorg with the wallet

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_long_sync_wallet(self, wallet_node, default_1000_blocks, default_400_blocks, trusted):

        full_node_api, wallet_node, full_node_server, wallet_server = wallet_node

        for block in default_400_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))
        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}

        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        # The second node should eventually catch up to the first one, and have the
        # same tip at height num_blocks - 1.
        await time_out_assert(600, wallet_height_at_least, True, wallet_node, len(default_400_blocks) - 1)

        # Tests a long reorg
        for block in default_1000_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await disconnect_all_and_reconnect(wallet_server, full_node_server)

        log.info(f"wallet node height is {wallet_node.wallet_state_manager.blockchain.get_peak_height()}")
        await time_out_assert(600, wallet_height_at_least, True, wallet_node, len(default_1000_blocks) - 1)

        await disconnect_all_and_reconnect(wallet_server, full_node_server)

        # Tests a short reorg
        num_blocks = 30
        blocks_reorg = bt.get_consecutive_blocks(num_blocks, block_list_input=default_1000_blocks[:-5])

        for i in range(1, len(blocks_reorg)):
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks_reorg[i]))

        await time_out_assert(
            600, wallet_height_at_least, True, wallet_node, len(default_1000_blocks) + num_blocks - 5 - 1
        )

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_reorg_sync(self, wallet_node_simulator, default_400_blocks, trusted):
        num_blocks = 5
        full_nodes, wallets = wallet_node_simulator
        full_node_api = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        fn_server = full_node_api.full_node.server
        wsm: WalletStateManager = wallet_node.wallet_state_manager
        wallet = wsm.main_wallet
        ph = await wallet.get_new_puzzlehash()

        if trusted:
            wallet_node.config["trusted_peers"] = {fn_server.node_id.hex(): fn_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)

        # Insert 400 blocks
        for block in default_400_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        # Farm few more with reward
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        # Confirm we have the funds
        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(5, wallet.get_confirmed_balance, funds)

        async def get_tx_count(wallet_id):
            txs = await wsm.get_all_transactions(wallet_id)
            return len(txs)

        await time_out_assert(5, get_tx_count, 2 * (num_blocks - 1), 1)

        # Reorg blocks that carry reward
        num_blocks = 30
        blocks_reorg = bt.get_consecutive_blocks(num_blocks, block_list_input=default_400_blocks[:-5])

        for block in blocks_reorg[-30:]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await time_out_assert(5, get_tx_count, 0, 1)
        await time_out_assert(5, wallet.get_confirmed_balance, 0)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_reorg_get_coinbase(self, wallet_node_simulator, default_400_blocks, trusted):
        full_nodes, wallets = wallet_node_simulator
        full_node_api = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        fn_server = full_node_api.full_node.server
        wsm = wallet_node.wallet_state_manager
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        if trusted:
            wallet_node.config["trusted_peers"] = {fn_server.node_id.hex(): fn_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)

        # Insert 400 blocks
        for block in default_400_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        # Reorg blocks that carry reward
        num_blocks_reorg = 30
        blocks_reorg = bt.get_consecutive_blocks(num_blocks_reorg, block_list_input=default_400_blocks[:-5])

        for block in blocks_reorg[:-5]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        async def get_tx_count(wallet_id):
            txs = await wsm.get_all_transactions(wallet_id)
            return len(txs)

        await time_out_assert(10, get_tx_count, 0, 1)

        num_blocks_reorg_1 = 40
        blocks_reorg_1 = bt.get_consecutive_blocks(
            1, pool_reward_puzzle_hash=ph, farmer_reward_puzzle_hash=ph, block_list_input=blocks_reorg[:-30]
        )
        blocks_reorg_2 = bt.get_consecutive_blocks(num_blocks_reorg_1, block_list_input=blocks_reorg_1)

        for block in blocks_reorg_2[-41:]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        await disconnect_all_and_reconnect(server_2, fn_server)

        # Confirm we have the funds
        funds = calculate_pool_reward(uint32(len(blocks_reorg_1))) + calculate_base_farmer_reward(
            uint32(len(blocks_reorg_1))
        )

        await time_out_assert(10, get_tx_count, 2, 1)
        await time_out_assert(10, wallet.get_confirmed_balance, funds)
