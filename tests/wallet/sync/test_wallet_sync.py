import pytest
from colorlog import getLogger

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol, wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability, capabilities
from chia.protocols.wallet_protocol import RejectBlockHeaders, RespondBlockHeaders
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32
from tests.connection_utils import disconnect_all_and_reconnect
from tests.pools.test_pool_rpc import wallet_is_synced
from tests.setup_nodes import test_constants
from tests.time_out_assert import time_out_assert


def wallet_height_at_least(wallet_node, h):
    height = wallet_node.wallet_state_manager.blockchain.get_peak_height()
    if height == h:
        return True
    return False


log = getLogger(__name__)


class TestWalletSync:
    @pytest.mark.asyncio
    async def test_request_block_headers(self, bt, wallet_node, default_1000_blocks):
        # Tests the edge case of receiving funds right before the recent blocks  in weight proof
        full_node_api: FullNodeAPI
        full_node_api, wallet_node, full_node_server, wallet_server = wallet_node

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        for block in default_1000_blocks[:100]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(10, 15, False))
        assert msg.type == ProtocolMessageTypes.respond_block_headers.value
        res_block_headers = RespondBlockHeaders.from_bytes(msg.data)
        bh = res_block_headers.header_blocks
        assert len(bh) == 6
        assert [x.reward_chain_block.height for x in default_1000_blocks[10:16]] == [
            x.reward_chain_block.height for x in bh
        ]

        assert [x.foliage for x in default_1000_blocks[10:16]] == [x.foliage for x in bh]

        assert [x.transactions_filter for x in bh] == [b"\x00"] * 6

        num_blocks = 20
        new_blocks = bt.get_consecutive_blocks(
            num_blocks, block_list_input=default_1000_blocks, pool_reward_puzzle_hash=ph
        )
        for i in range(0, len(new_blocks)):
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(new_blocks[i]))

        msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(110, 115, True))
        res_block_headers = RespondBlockHeaders.from_bytes(msg.data)
        bh = res_block_headers.header_blocks
        assert len(bh) == 6

    @pytest.mark.asyncio
    async def test_request_block_headers_rejected(self, bt, wallet_node, default_1000_blocks):
        # Tests the edge case of receiving funds right before the recent blocks  in weight proof
        full_node_api: FullNodeAPI
        full_node_api, wallet_node, full_node_server, wallet_server = wallet_node

        msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(1000000, 1000010, False))
        assert msg.type == ProtocolMessageTypes.reject_block_headers.value

        for block in default_1000_blocks[:100]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(80, 99, False))
        assert msg.type == ProtocolMessageTypes.respond_block_headers.value
        msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(10, 8, False))
        assert msg is None

        msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(10, 8, True))
        assert msg is None

        msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(90, 110, False))
        assert msg.type == ProtocolMessageTypes.reject_block_headers.value
        msg = await full_node_api.request_block_headers(wallet_protocol.RequestBlockHeaders(90, 110, True))
        assert msg.type == ProtocolMessageTypes.reject_block_headers.value


class TestWalletSync:
    @pytest.mark.asyncio
    async def test_basic_sync_wallet(self, bt, two_wallet_nodes, default_400_blocks, self_hostname):
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server

        # Trusted node sync
        wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}

        # Untrusted node sync
        wallets[1][0].config["trusted_peers"] = {}

        for block in default_400_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        for wallet_node, wallet_server in wallets:
            await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        for wallet_node, wallet_server in wallets:
            await time_out_assert(100, wallet_height_at_least, True, wallet_node, len(default_400_blocks) - 1)

        # Tests a reorg with the wallet
        num_blocks = 30
        blocks_reorg = bt.get_consecutive_blocks(num_blocks, block_list_input=default_400_blocks[:-5])
        for i in range(1, len(blocks_reorg)):
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks_reorg[i]))

        for wallet_node, wallet_server in wallets:
            await disconnect_all_and_reconnect(wallet_server, full_node_server, self_hostname)

        for wallet_node, wallet_server in wallets:
            await time_out_assert(
                100, wallet_height_at_least, True, wallet_node, len(default_400_blocks) + num_blocks - 5 - 1
            )

    @pytest.mark.parametrize(
        "wallet_node",
        [
            dict(
                disable_capabilities=[Capability.BLOCK_HEADERS.name],
            ),
            dict(
                disable_capabilities=
                # this one should be ignored
                [Capability.BASE.name],
            ),
        ],
        indirect=True,
    )
    @pytest.mark.asyncio
    async def test_almost_recent(self, bt, two_wallet_nodes, default_400_blocks, self_hostname):
        # Tests the edge case of receiving funds right before the recent blocks  in weight proof
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server

        # Trusted node sync
        wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}

        # Untrusted node sync
        wallets[1][0].config["trusted_peers"] = {}

        base_num_blocks = 400
        for block in default_400_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        all_blocks = default_400_blocks
        both_phs = []
        for wallet_node, wallet_server in wallets:
            wallet = wallet_node.wallet_state_manager.main_wallet
            both_phs.append(await wallet.get_new_puzzlehash())

        for i in range(20):
            # Tests a reorg with the wallet
            ph = both_phs[i % 2]
            all_blocks = bt.get_consecutive_blocks(1, block_list_input=all_blocks, pool_reward_puzzle_hash=ph)
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(all_blocks[-1]))

        new_blocks = bt.get_consecutive_blocks(
            test_constants.WEIGHT_PROOF_RECENT_BLOCKS + 10, block_list_input=all_blocks
        )
        for i in range(base_num_blocks + 20, len(new_blocks)):
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(new_blocks[i]))

        for wallet_node, wallet_server in wallets:
            wallet = wallet_node.wallet_state_manager.main_wallet
            await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
            await time_out_assert(30, wallet.get_confirmed_balance, 10 * calculate_pool_reward(uint32(1000)))

    @pytest.mark.asyncio
    async def test_backtrack_sync_wallet(self, two_wallet_nodes, default_400_blocks, self_hostname):
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server

        # Trusted node sync
        wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}

        # Untrusted node sync
        wallets[1][0].config["trusted_peers"] = {}

        for block in default_400_blocks[:20]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        for wallet_node, wallet_server in wallets:
            await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        for wallet_node, wallet_server in wallets:
            await time_out_assert(100, wallet_height_at_least, True, wallet_node, 19)

    # Tests a reorg with the wallet
    @pytest.mark.asyncio
    async def test_short_batch_sync_wallet(self, two_wallet_nodes, default_400_blocks, self_hostname):
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server

        # Trusted node sync
        wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}

        # Untrusted node sync
        wallets[1][0].config["trusted_peers"] = {}

        for block in default_400_blocks[:200]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        for wallet_node, wallet_server in wallets:
            await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        for wallet_node, wallet_server in wallets:
            await time_out_assert(100, wallet_height_at_least, True, wallet_node, 199)

    @pytest.mark.asyncio
    async def test_long_sync_wallet(self, bt, two_wallet_nodes, default_1000_blocks, default_400_blocks, self_hostname):
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server

        # Trusted node sync
        wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}

        # Untrusted node sync
        wallets[1][0].config["trusted_peers"] = {}

        for block in default_400_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        for wallet_node, wallet_server in wallets:
            await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        for wallet_node, wallet_server in wallets:
            await time_out_assert(600, wallet_height_at_least, True, wallet_node, len(default_400_blocks) - 1)

        # Tests a long reorg
        for block in default_1000_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        for wallet_node, wallet_server in wallets:
            await disconnect_all_and_reconnect(wallet_server, full_node_server, self_hostname)

            log.info(f"wallet node height is {wallet_node.wallet_state_manager.blockchain.get_peak_height()}")
            await time_out_assert(600, wallet_height_at_least, True, wallet_node, len(default_1000_blocks) - 1)

            await disconnect_all_and_reconnect(wallet_server, full_node_server, self_hostname)

        # Tests a short reorg
        num_blocks = 30
        blocks_reorg = bt.get_consecutive_blocks(num_blocks, block_list_input=default_1000_blocks[:-5])

        for i in range(len(blocks_reorg) - num_blocks - 10, len(blocks_reorg)):
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks_reorg[i]))

        for wallet_node, wallet_server in wallets:
            await time_out_assert(
                600, wallet_height_at_least, True, wallet_node, len(default_1000_blocks) + num_blocks - 5 - 1
            )

    @pytest.mark.asyncio
    async def test_wallet_reorg_sync(self, bt, two_wallet_nodes, default_400_blocks, self_hostname):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server

        # Trusted node sync
        wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}

        # Untrusted node sync
        wallets[1][0].config["trusted_peers"] = {}

        phs = []
        for wallet_node, wallet_server in wallets:
            wallet = wallet_node.wallet_state_manager.main_wallet
            phs.append(await wallet.get_new_puzzlehash())
            await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        # Insert 400 blocks
        for block in default_400_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        # Farm few more with reward
        for i in range(0, num_blocks - 1):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(phs[0]))

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(phs[1]))

        # Confirm we have the funds
        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        async def get_tx_count(wsm, wallet_id):
            txs = await wsm.get_all_transactions(wallet_id)
            return len(txs)

        for wallet_node, wallet_server in wallets:
            wallet = wallet_node.wallet_state_manager.main_wallet
            await time_out_assert(5, wallet.get_confirmed_balance, funds)
            await time_out_assert(5, get_tx_count, 2 * (num_blocks - 1), wallet_node.wallet_state_manager, 1)

        # Reorg blocks that carry reward
        num_blocks = 30
        blocks_reorg = bt.get_consecutive_blocks(num_blocks, block_list_input=default_400_blocks[:-5])

        for block in blocks_reorg[-30:]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        for wallet_node, wallet_server in wallets:
            wallet = wallet_node.wallet_state_manager.main_wallet
            await time_out_assert(5, get_tx_count, 0, wallet_node.wallet_state_manager, 1)
            await time_out_assert(5, wallet.get_confirmed_balance, 0)

    @pytest.mark.asyncio
    async def test_wallet_reorg_get_coinbase(self, bt, two_wallet_nodes, default_400_blocks, self_hostname):
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server

        # Trusted node sync
        wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}

        # Untrusted node sync
        wallets[1][0].config["trusted_peers"] = {}

        for wallet_node, wallet_server in wallets:
            await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        # Insert 400 blocks
        for block in default_400_blocks:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        # Reorg blocks that carry reward
        num_blocks_reorg = 30
        blocks_reorg = bt.get_consecutive_blocks(num_blocks_reorg, block_list_input=default_400_blocks[:-5])

        for block in blocks_reorg[:-5]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        async def get_tx_count(wsm, wallet_id):
            txs = await wsm.get_all_transactions(wallet_id)
            return len(txs)

        for wallet_node, wallet_server in wallets:
            await time_out_assert(10, get_tx_count, 0, wallet_node.wallet_state_manager, 1)
            await time_out_assert(30, wallet_is_synced, True, wallet_node, full_node_api)

        num_blocks_reorg_1 = 40
        all_blocks_reorg_2 = blocks_reorg[:-30]
        for wallet_node, wallet_server in wallets:
            wallet = wallet_node.wallet_state_manager.main_wallet
            ph = await wallet.get_new_puzzlehash()
            all_blocks_reorg_2 = bt.get_consecutive_blocks(
                1, pool_reward_puzzle_hash=ph, farmer_reward_puzzle_hash=ph, block_list_input=all_blocks_reorg_2
            )
        blocks_reorg_2 = bt.get_consecutive_blocks(num_blocks_reorg_1, block_list_input=all_blocks_reorg_2)

        for block in blocks_reorg_2[-44:]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        for wallet_node, wallet_server in wallets:
            await disconnect_all_and_reconnect(wallet_server, full_node_server, self_hostname)

        # Confirm we have the funds
        funds = calculate_pool_reward(uint32(len(all_blocks_reorg_2))) + calculate_base_farmer_reward(
            uint32(len(all_blocks_reorg_2))
        )

        for wallet_node, wallet_server in wallets:
            wallet = wallet_node.wallet_state_manager.main_wallet
            await time_out_assert(60, wallet_is_synced, True, wallet_node, full_node_api)
            await time_out_assert(20, get_tx_count, 2, wallet_node.wallet_state_manager, 1)
            await time_out_assert(20, wallet.get_confirmed_balance, funds)
