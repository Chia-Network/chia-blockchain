from typing import List, Optional

import pytest
from colorlog import getLogger

from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.weight_proof import WeightProofHandler
from chia.protocols import full_node_protocol, wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.protocols.wallet_protocol import RequestAdditions, RespondAdditions, RespondBlockHeaders, SendTransaction
from chia.server.outbound_message import Message
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert
from chia.types.peer_info import PeerInfo
from chia.util.block_cache import BlockCache
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import AmountWithPuzzlehash
from chia.wallet.wallet_weight_proof_handler import get_wp_fork_point
from tests.connection_utils import disconnect_all, disconnect_all_and_reconnect
from tests.setup_nodes import test_constants
from tests.util.wallet_is_synced import wallet_is_synced
from tests.weight_proof.test_weight_proof import load_blocks_dont_validate


def wallet_height_at_least(wallet_node, h):
    height = wallet_node.wallet_state_manager.blockchain.get_peak_height()
    if height == h:
        return True
    return False


log = getLogger(__name__)


class TestWalletSync:
    @pytest.mark.asyncio
    async def test_request_block_headers(self, wallet_node, default_1000_blocks):
        # Tests the edge case of receiving funds right before the recent blocks  in weight proof
        full_node_api: FullNodeAPI
        full_node_api, wallet_node, full_node_server, wallet_server, bt = wallet_node

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        for block in default_1000_blocks[:100]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        msg = await full_node_api.request_block_headers(
            wallet_protocol.RequestBlockHeaders(uint32(10), uint32(15), False)
        )
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

        msg = await full_node_api.request_block_headers(
            wallet_protocol.RequestBlockHeaders(uint32(110), uint32(115), True)
        )
        res_block_headers = RespondBlockHeaders.from_bytes(msg.data)
        bh = res_block_headers.header_blocks
        assert len(bh) == 6

    # @pytest.mark.parametrize(
    #     "test_case",
    #     [(1000000, 10000010, False, ProtocolMessageTypes.reject_block_headers)],
    #     [(80, 99, False, ProtocolMessageTypes.respond_block_headers)],
    #     [(10, 8, False, None)],
    # )
    @pytest.mark.asyncio
    async def test_request_block_headers_rejected(self, wallet_node, default_1000_blocks):
        # Tests the edge case of receiving funds right before the recent blocks  in weight proof
        full_node_api: FullNodeAPI
        full_node_api, wallet_node, full_node_server, wallet_server, bt = wallet_node

        # start_height, end_height, return_filter, expected_res = test_case

        msg = await full_node_api.request_block_headers(
            wallet_protocol.RequestBlockHeaders(uint32(1000000), uint32(1000010), False)
        )
        assert msg.type == ProtocolMessageTypes.reject_block_headers.value

        for block in default_1000_blocks[:150]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        msg = await full_node_api.request_block_headers(
            wallet_protocol.RequestBlockHeaders(uint32(80), uint32(99), False)
        )
        assert msg.type == ProtocolMessageTypes.respond_block_headers.value
        msg = await full_node_api.request_block_headers(
            wallet_protocol.RequestBlockHeaders(uint32(10), uint32(8), False)
        )
        assert msg.type == ProtocolMessageTypes.reject_block_headers.value

        msg = await full_node_api.request_block_headers(
            wallet_protocol.RequestBlockHeaders(uint32(10), uint32(8), True)
        )
        assert msg.type == ProtocolMessageTypes.reject_block_headers.value

        # test for 128 blocks to fetch at once limit
        msg = await full_node_api.request_block_headers(
            wallet_protocol.RequestBlockHeaders(uint32(10), uint32(140), True)
        )
        assert msg.type == ProtocolMessageTypes.reject_block_headers.value

        msg = await full_node_api.request_block_headers(
            wallet_protocol.RequestBlockHeaders(uint32(90), uint32(160), False)
        )
        assert msg.type == ProtocolMessageTypes.reject_block_headers.value
        msg = await full_node_api.request_block_headers(
            wallet_protocol.RequestBlockHeaders(uint32(90), uint32(160), True)
        )
        assert msg.type == ProtocolMessageTypes.reject_block_headers.value

    @pytest.mark.parametrize(
        "two_wallet_nodes",
        [
            dict(
                disable_capabilities=[Capability.BLOCK_HEADERS],
            ),
            dict(
                disable_capabilities=[Capability.BASE],
            ),
        ],
        indirect=True,
    )
    @pytest.mark.asyncio
    async def test_basic_sync_wallet(self, two_wallet_nodes, default_400_blocks, self_hostname):
        full_nodes, wallets, bt = two_wallet_nodes
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
        blocks_reorg = bt.get_consecutive_blocks(num_blocks - 1, block_list_input=default_400_blocks[:-5])
        blocks_reorg = bt.get_consecutive_blocks(1, blocks_reorg, guarantee_transaction_block=True, current_time=True)
        for i in range(1, len(blocks_reorg)):
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(blocks_reorg[i]))

        for wallet_node, wallet_server in wallets:
            await disconnect_all_and_reconnect(wallet_server, full_node_server, self_hostname)

        for wallet_node, wallet_server in wallets:
            await time_out_assert(
                100, wallet_height_at_least, True, wallet_node, len(default_400_blocks) + num_blocks - 5 - 1
            )
            await time_out_assert(20, wallet_node.wallet_state_manager.synced)
            await disconnect_all(wallet_server)
            assert not (await wallet_node.wallet_state_manager.synced())

    @pytest.mark.parametrize(
        "two_wallet_nodes",
        [
            dict(
                disable_capabilities=[Capability.BLOCK_HEADERS],
            ),
            dict(
                disable_capabilities=[Capability.BASE],
            ),
        ],
        indirect=True,
    )
    @pytest.mark.asyncio
    async def test_almost_recent(self, two_wallet_nodes, default_400_blocks, self_hostname):
        # Tests the edge case of receiving funds right before the recent blocks  in weight proof
        full_nodes, wallets, bt = two_wallet_nodes
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
        full_nodes, wallets, _ = two_wallet_nodes
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
        full_nodes, wallets, _ = two_wallet_nodes
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
    async def test_long_sync_wallet(self, two_wallet_nodes, default_1000_blocks, default_400_blocks, self_hostname):
        full_nodes, wallets, bt = two_wallet_nodes
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
    async def test_wallet_reorg_sync(self, two_wallet_nodes, default_400_blocks, self_hostname):
        num_blocks = 5
        full_nodes, wallets, bt = two_wallet_nodes
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
            await time_out_assert(20, wallet.get_confirmed_balance, funds)
            await time_out_assert(20, get_tx_count, 2 * (num_blocks - 1), wallet_node.wallet_state_manager, 1)

        # Reorg blocks that carry reward
        num_blocks = 30
        blocks_reorg = bt.get_consecutive_blocks(num_blocks, block_list_input=default_400_blocks[:-5])

        for block in blocks_reorg[-30:]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        for wallet_node, wallet_server in wallets:
            wallet = wallet_node.wallet_state_manager.main_wallet
            await time_out_assert(20, get_tx_count, 0, wallet_node.wallet_state_manager, 1)
            await time_out_assert(20, wallet.get_confirmed_balance, 0)

    @pytest.mark.asyncio
    async def test_wallet_reorg_get_coinbase(self, two_wallet_nodes, default_400_blocks, self_hostname):
        full_nodes, wallets, bt = two_wallet_nodes
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
            await time_out_assert(30, get_tx_count, 0, wallet_node.wallet_state_manager, 1)
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

    @pytest.mark.asyncio
    async def test_request_additions_errors(self, wallet_node_sim_and_wallet, self_hostname):
        full_nodes, wallets, _ = wallet_node_sim_and_wallet
        wallet_node, wallet_server = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        full_node_api = full_nodes[0]
        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None)

        for i in range(2):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(20, wallet_is_synced, True, wallet_node, full_node_api)

        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None

        # Invalid height
        with pytest.raises(ValueError):
            await full_node_api.request_additions(RequestAdditions(uint64(100), last_block.header_hash, [ph]))

        # Invalid header hash
        with pytest.raises(ValueError):
            await full_node_api.request_additions(RequestAdditions(last_block.height, std_hash(b""), [ph]))

        # No results
        res1: Optional[Message] = await full_node_api.request_additions(
            RequestAdditions(last_block.height, last_block.header_hash, [std_hash(b"")])
        )
        assert res1 is not None
        response = RespondAdditions.from_bytes(res1.data)
        assert response.height == last_block.height
        assert response.header_hash == last_block.header_hash
        assert len(response.proofs) == 1
        assert len(response.coins) == 1

        assert response.proofs[0][0] == std_hash(b"")
        assert response.proofs[0][1] is not None
        assert response.proofs[0][2] is None

    @pytest.mark.asyncio
    async def test_request_additions_success(self, wallet_node_sim_and_wallet, self_hostname):
        full_nodes, wallets, _ = wallet_node_sim_and_wallet
        wallet_node, wallet_server = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        full_node_api = full_nodes[0]
        await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None)

        for i in range(2):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(20, wallet_is_synced, True, wallet_node, full_node_api)

        payees: List[AmountWithPuzzlehash] = []
        for i in range(10):
            payee_ph = await wallet.get_new_puzzlehash()
            payees.append({"amount": uint64(i + 100), "puzzlehash": payee_ph, "memos": []})
            payees.append({"amount": uint64(i + 200), "puzzlehash": payee_ph, "memos": []})

        tx: TransactionRecord = await wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(20, wallet_is_synced, True, wallet_node, full_node_api)
        res2: Optional[Message] = await full_node_api.request_additions(
            RequestAdditions(
                last_block.height,
                None,
                [payees[0]["puzzlehash"], payees[2]["puzzlehash"], std_hash(b"1")],
            )
        )

        assert res2 is not None
        response = RespondAdditions.from_bytes(res2.data)
        assert response.height == last_block.height
        assert response.header_hash == last_block.header_hash
        assert len(response.proofs) == 3

        # First two PHs are included
        for i in range(2):
            assert response.proofs[i][0] in {payees[j]["puzzlehash"] for j in (0, 2)}
            assert response.proofs[i][1] is not None
            assert response.proofs[i][2] is not None

        # Third PH is not included
        assert response.proofs[2][2] is None

        coin_list_dict = {p: coin_list for p, coin_list in response.coins}

        assert len(coin_list_dict) == 3
        for p, coin_list in coin_list_dict.items():
            if p == std_hash(b"1"):
                # this is the one that is not included
                assert len(coin_list) == 0
            else:
                for coin in coin_list:
                    assert coin.puzzle_hash == p
                # The other ones are included
                assert len(coin_list) == 2

        # None for puzzle hashes returns all coins and no proofs
        res3: Optional[Message] = await full_node_api.request_additions(
            RequestAdditions(last_block.height, last_block.header_hash, None)
        )

        assert res3 is not None
        response = RespondAdditions.from_bytes(res3.data)
        assert response.height == last_block.height
        assert response.header_hash == last_block.header_hash
        assert response.proofs is None
        assert len(response.coins) == 12
        assert sum([len(c_list) for _, c_list in response.coins]) == 24

        # [] for puzzle hashes returns nothing
        res4: Optional[Message] = await full_node_api.request_additions(
            RequestAdditions(last_block.height, last_block.header_hash, [])
        )
        assert res4 is not None
        response = RespondAdditions.from_bytes(res4.data)
        assert response.proofs == []
        assert len(response.coins) == 0

    @pytest.mark.asyncio
    async def test_get_wp_fork_point(self, default_10000_blocks):
        blocks = default_10000_blocks
        header_cache, height_to_hash, sub_blocks, summaries = await load_blocks_dont_validate(blocks)
        wpf = WeightProofHandler(test_constants, BlockCache(sub_blocks, header_cache, height_to_hash, summaries))
        wp1 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(9000)]].header_hash)
        wp2 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(9030)]].header_hash)
        wp3 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(7500)]].header_hash)
        wp4 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(8700)]].header_hash)
        wp5 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(9700)]].header_hash)
        fork12 = get_wp_fork_point(test_constants, wp1, wp2)
        fork13 = get_wp_fork_point(test_constants, wp3, wp1)
        fork14 = get_wp_fork_point(test_constants, wp4, wp1)
        fork23 = get_wp_fork_point(test_constants, wp3, wp2)
        fork24 = get_wp_fork_point(test_constants, wp4, wp2)
        fork34 = get_wp_fork_point(test_constants, wp3, wp4)
        fork45 = get_wp_fork_point(test_constants, wp4, wp5)
        assert fork14 == 8700
        assert fork24 == 8700
        assert fork12 == 9000
        assert fork13 in summaries.keys()
        assert fork23 in summaries.keys()
        assert fork34 in summaries.keys()
        assert fork45 in summaries.keys()
