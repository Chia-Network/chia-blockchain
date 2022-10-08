from __future__ import annotations

from typing import List, Optional, Set

import pytest
from aiosqlite import Error as AIOSqliteError
from colorlog import getLogger

from chia.consensus.block_record import BlockRecord
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.full_node_api import FullNodeAPI
from chia.full_node.mempool_manager import MempoolManager
from chia.full_node.weight_proof import WeightProofHandler
from chia.protocols import full_node_protocol, wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability
from chia.protocols.wallet_protocol import RequestAdditions, RespondAdditions, RespondBlockHeaders, SendTransaction
from chia.server.outbound_message import Message
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.block_cache import BlockCache
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.wallet_sync_utils import PeerRequestException
from chia.wallet.util.wallet_types import AmountWithPuzzlehash
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_weight_proof_handler import get_wp_fork_point
from tests.connection_utils import disconnect_all, disconnect_all_and_reconnect
from tests.setup_nodes import test_constants
from tests.util.wallet_is_synced import wallet_is_synced
from tests.weight_proof.test_weight_proof import load_blocks_dont_validate


async def wallet_height_at_least(wallet_node, h):
    height = await wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to()
    if height == h:
        return True
    return False


async def get_nft_count(wallet: NFTWallet) -> int:
    return await wallet.get_nft_count()


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

            log.info(
                f"wallet node height is {await wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to()}"
            )
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
            await time_out_assert(60, wallet.get_confirmed_balance, funds)
            await time_out_assert(60, get_tx_count, 2 * (num_blocks - 1), wallet_node.wallet_state_manager, 1)

        # Reorg blocks that carry reward
        num_blocks = 30
        blocks_reorg = bt.get_consecutive_blocks(num_blocks, block_list_input=default_400_blocks[:-5])

        for block in blocks_reorg[-30:]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        for wallet_node, wallet_server in wallets:
            wallet = wallet_node.wallet_state_manager.main_wallet
            await time_out_assert(60, get_tx_count, 0, wallet_node.wallet_state_manager, 1)
            await time_out_assert(60, wallet.get_confirmed_balance, 0)

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
        wp6 = await wpf.get_proof_of_weight(header_cache[height_to_hash[uint32(9010)]].header_hash)
        fork12 = get_wp_fork_point(test_constants, wp1, wp2)
        fork13 = get_wp_fork_point(test_constants, wp3, wp1)
        fork14 = get_wp_fork_point(test_constants, wp4, wp1)
        fork23 = get_wp_fork_point(test_constants, wp3, wp2)
        fork24 = get_wp_fork_point(test_constants, wp4, wp2)
        fork34 = get_wp_fork_point(test_constants, wp3, wp4)
        fork45 = get_wp_fork_point(test_constants, wp4, wp5)
        fork16 = get_wp_fork_point(test_constants, wp1, wp6)

        # overlap between recent chain in wps, fork point is the tip of the shorter wp
        assert fork12 == wp1.recent_chain_data[-1].height
        assert fork16 == wp1.recent_chain_data[-1].height

        # if there is an overlap between the recent chains we can find the exact fork point
        # if not we should get the latest block with a sub epoch summary that exists in both wp's
        # this can happen in fork24 and fork14 since they are not very far and also not very close

        if wp2.recent_chain_data[0].height > wp4.recent_chain_data[-1].height:
            assert fork24 in summaries.keys()
            assert fork24 < wp4.recent_chain_data[-1].height
        else:
            assert fork24 == wp4.recent_chain_data[-1].height

        if wp1.recent_chain_data[0].height > wp4.recent_chain_data[-1].height:
            assert fork14 in summaries.keys()
            assert fork14 < wp4.recent_chain_data[-1].height
        else:
            assert fork14 == wp4.recent_chain_data[-1].height

        # no overlap between recent chain in wps, fork point
        # is the latest block with a sub epoch summary that exists in both wp's
        assert fork13 in summaries.keys()
        assert fork13 < wp3.recent_chain_data[-1].height
        assert fork23 in summaries.keys()
        assert fork23 < wp3.recent_chain_data[-1].height
        assert fork34 in summaries.keys()
        assert fork23 < wp3.recent_chain_data[-1].height
        assert fork45 in summaries.keys()
        assert fork45 < wp4.recent_chain_data[-1].height

    """
    This tests that a wallet filters out the dust properly.
    It runs in seven phases:
    1. Create a single dust coin.
       Typically (though there are edge cases), this coin will not be filtered.
    2. Create dust coins until the filter threshold has been reached.
       At this point, none of the dust should be filtered.
    3. Create 10 coins that are exactly the size of the filter threshold.
       These should not be filtered because they are not dust.
    4. Create one more dust coin. This coin should be filtered.
    5. Create 5 coins below the threshold and 5 at or above.
       Those below the threshold should get filtered, and those above should not.
    6. Clear all coins from the dust wallet.
       Send to the dust wallet "spam_filter_after_n_txs" coins that are equal in value to "xch_spam_amount".
       Send 1 mojo from the dust wallet. The dust wallet should receive a change coin valued at "xch_spam_amount-1".
    7: Create an NFT wallet for the farmer wallet, and generate an NFT in that wallet.
       Create an NFT wallet for the dust wallet.
       Send the NFT to the dust wallet. The NFT should not be filtered.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "spam_filter_after_n_txs, xch_spam_amount, dust_value",
        [
            # In the following tests, the filter is run right away:
            (0, 1, 1),  # nothing is filtered
            # In the following tests, 1 coin will be created in part 1, and 9 in part 2:
            (10, 10000000000, 1),  # everything is dust
            (10, 10000000000, 10000000000),  # max dust threshold, dust is same size so not filtered
            # Test with more coins
            (100, 1000000, 1),  # default filter level (1m mojos), default dust size (1)
        ],
    )
    async def test_dusted_wallet(
        self,
        self_hostname,
        two_wallet_nodes_custom_spam_filtering,
        spam_filter_after_n_txs,
        xch_spam_amount,
        dust_value,
    ):

        full_nodes, wallets, _ = two_wallet_nodes_custom_spam_filtering

        farm_wallet_node, farm_wallet_server = wallets[0]
        dust_wallet_node, dust_wallet_server = wallets[1]

        # Create two wallets, one for farming (not used for testing), and one for testing dust.
        farm_wallet = farm_wallet_node.wallet_state_manager.main_wallet
        dust_wallet = dust_wallet_node.wallet_state_manager.main_wallet
        ph = await farm_wallet.get_new_puzzlehash()

        full_node_api = full_nodes[0]

        # It's also possible to obtain the current settings for spam_filter_after_n_txs and xch_spam_amount
        # spam_filter_after_n_txs = wallets[0][0].config["spam_filter_after_n_txs"]
        # xch_spam_amount = wallets[0][0].config["xch_spam_amount"]
        # dust_value=1

        # Verify legal values for the settings to be tested
        # If spam_filter_after_n_txs is greater than 250, this test will take a long time to run.
        # Current max value for xch_spam_amount is 0.01 XCH.
        # If needed, this could be increased but we would need to farm more blocks.
        # The max dust_value could be increased, but would require farming more blocks.
        assert spam_filter_after_n_txs >= 0
        assert spam_filter_after_n_txs <= 250
        assert xch_spam_amount >= 1
        assert xch_spam_amount <= 10000000000
        assert dust_value >= 1
        assert dust_value <= 10000000000

        # start both clients
        await farm_wallet_server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )
        await dust_wallet_server.start_client(
            PeerInfo(self_hostname, uint16(full_node_api.full_node.server._port)), None
        )

        # Farm two blocks
        for i in range(2):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        # sync both nodes
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, dust_wallet_node, full_node_api)

        # Part 1: create a single dust coin
        payees: List[AmountWithPuzzlehash] = []
        payee_ph = await dust_wallet.get_new_puzzlehash()
        payees.append({"amount": uint64(dust_value), "puzzlehash": payee_ph, "memos": []})

        # construct and send tx
        tx: TransactionRecord = await farm_wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, dust_wallet_node, full_node_api)

        # The dust is only filtered at this point if spam_filter_after_n_txs is 0 and xch_spam_amount is > dust_value.
        if spam_filter_after_n_txs > 0:
            dust_coins = 1
            large_dust_coins = 0
            large_dust_balance = 0
        elif xch_spam_amount <= dust_value:
            dust_coins = 0
            large_dust_coins = 1
            large_dust_balance = dust_value
        else:
            dust_coins = 0
            large_dust_coins = 0
            large_dust_balance = 0

        # Obtain and log important values
        all_unspent: Set[
            WalletCoinRecord
        ] = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
        log.info(f"all_unspent is {all_unspent}")
        small_unspent_count = len([r for r in all_unspent if r.coin.amount < xch_spam_amount])
        balance: Optional[Message] = await dust_wallet.get_confirmed_balance()
        num_coins: Optional[Message] = len(await dust_wallet.select_coins(balance))

        log.info(f"Small coin count is {small_unspent_count}")
        log.info(f"Wallet balance is {balance}")
        log.info(f"Number of coins is {num_coins}")

        log.info(f"spam_filter_after_n_txs {spam_filter_after_n_txs}")
        log.info(f"xch_spam_amount {xch_spam_amount}")
        log.info(f"dust_value {dust_value}")

        # Verify balance and number of coins not filtered.
        assert balance == dust_coins * dust_value + large_dust_balance
        assert num_coins == dust_coins + large_dust_coins

        # Part 2: Create dust coins until the filter threshold has been reached.
        # Nothing should be filtered yet (unless spam_filter_after_n_txs is 0).
        payees: List[AmountWithPuzzlehash] = []

        # Determine how much dust to create, recalling that there already is one dust coin.
        new_dust = spam_filter_after_n_txs - 1
        dust_remaining = new_dust

        while dust_remaining > 0:
            payee_ph = await dust_wallet.get_new_puzzlehash()
            payees.append({"amount": uint64(dust_value), "puzzlehash": payee_ph, "memos": []})

            # After every 100 (at most) coins added, push the tx and advance the chain
            # This greatly speeds up the overall process
            if dust_remaining % 100 == 0 and dust_remaining != new_dust:
                # construct and send tx
                tx: TransactionRecord = await farm_wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
                await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
                last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
                assert last_block is not None
                # reset payees
                payees: List[AmountWithPuzzlehash] = []

            dust_remaining -= 1

        # Only need to create tx if there was new dust to be added
        if new_dust >= 1:
            # construct and send tx
            tx: TransactionRecord = await farm_wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
            await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

            # advance the chain and sync both wallets
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
            assert last_block is not None
            await time_out_assert(60, wallet_is_synced, True, farm_wallet_node, full_node_api)
            await time_out_assert(60, wallet_is_synced, True, dust_wallet_node, full_node_api)

        # Obtain and log important values
        all_unspent: Set[
            WalletCoinRecord
        ] = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
        small_unspent_count = len([r for r in all_unspent if r.coin.amount < xch_spam_amount])
        balance: Optional[Message] = await dust_wallet.get_confirmed_balance()
        # Selecting coins by using the wallet's coin selection algorithm won't work for large
        # numbers of coins, so we'll use the state manager for the rest of the test
        # num_coins: Optional[Message] = len(await dust_wallet.select_coins(balance))
        num_coins: Optional[Message] = len(
            list(await dust_wallet_node.wallet_state_manager.get_spendable_coins_for_wallet(1))
        )

        log.info(f"Small coin count is {small_unspent_count}")
        log.info(f"Wallet balance is {balance}")
        log.info(f"Number of coins is {num_coins}")

        # obtain the total expected coins (new_dust could be negative)
        if new_dust > 0:
            dust_coins += new_dust

        # Make sure the number of coins matches the expected number.
        # At this point, nothing should be getting filtered unless spam_filter_after_n_txs is 0.
        assert dust_coins == spam_filter_after_n_txs
        assert balance == dust_coins * dust_value + large_dust_balance
        assert num_coins == dust_coins + large_dust_coins

        # Part 3: Create 10 coins that are exactly the size of the filter threshold.
        # These should not get filtered.
        large_coins = 10

        payees: List[AmountWithPuzzlehash] = []

        for i in range(large_coins):
            payee_ph = await dust_wallet.get_new_puzzlehash()
            payees.append({"amount": uint64(xch_spam_amount), "puzzlehash": payee_ph, "memos": []})

        # construct and send tx
        tx: TransactionRecord = await farm_wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, dust_wallet_node, full_node_api)

        # Obtain and log important values
        all_unspent: Set[
            WalletCoinRecord
        ] = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
        small_unspent_count = len([r for r in all_unspent if r.coin.amount < xch_spam_amount])
        balance: Optional[Message] = await dust_wallet.get_confirmed_balance()
        num_coins: Optional[Message] = len(
            list(await dust_wallet_node.wallet_state_manager.get_spendable_coins_for_wallet(1))
        )

        log.info(f"Small coin count is {small_unspent_count}")
        log.info(f"Wallet balance is {balance}")
        log.info(f"Number of coins is {num_coins}")

        large_coin_balance = large_coins * xch_spam_amount

        # Determine whether the filter should have been activated.
        # Make sure the number of coins matches the expected number.
        # At this point, nothing should be getting filtered unless spam_filter_after_n_txs is 0.
        assert dust_coins == spam_filter_after_n_txs
        assert balance == dust_coins * dust_value + large_coins * xch_spam_amount + large_dust_balance
        assert num_coins == dust_coins + large_coins + large_dust_coins

        # Part 4: Create one more dust coin to test the threshold
        payees: List[AmountWithPuzzlehash] = []

        payee_ph = await dust_wallet.get_new_puzzlehash()
        payees.append({"amount": uint64(dust_value), "puzzlehash": payee_ph, "memos": []})

        # construct and send tx
        tx: TransactionRecord = await farm_wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, dust_wallet_node, full_node_api)

        # Obtain and log important values
        all_unspent: Set[
            WalletCoinRecord
        ] = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
        small_unspent_count = len([r for r in all_unspent if r.coin.amount < xch_spam_amount])
        balance: Optional[Message] = await dust_wallet.get_confirmed_balance()
        num_coins: Optional[Message] = len(
            list(await dust_wallet_node.wallet_state_manager.get_spendable_coins_for_wallet(1))
        )

        log.info(f"Small coin count is {small_unspent_count}")
        log.info(f"Wallet balance is {balance}")
        log.info(f"Number of coins is {num_coins}")

        # In the edge case where the new "dust" is larger than the threshold,
        # then it is actually a large dust coin that won't get filtered.
        if dust_value >= xch_spam_amount:
            large_dust_coins += 1
            large_dust_balance += dust_value

        assert dust_coins == spam_filter_after_n_txs
        assert balance == dust_coins * dust_value + large_coins * xch_spam_amount + large_dust_balance
        assert num_coins == dust_coins + large_dust_coins + large_coins

        # Part 5: Create 5 coins below the threshold and 5 at or above.
        # Those below the threshold should get filtered, and those above should not.
        payees: List[AmountWithPuzzlehash] = []

        for i in range(5):
            payee_ph = await dust_wallet.get_new_puzzlehash()

            # Create a large coin and add on the appropriate balance.
            payees.append({"amount": uint64(xch_spam_amount + i), "puzzlehash": payee_ph, "memos": []})
            large_coins += 1
            large_coin_balance += xch_spam_amount + i

            payee_ph = await dust_wallet.get_new_puzzlehash()

            # Make sure we are always creating coins with a positive value.
            if xch_spam_amount - dust_value - i > 0:
                payees.append({"amount": uint64(xch_spam_amount - dust_value - i), "puzzlehash": payee_ph, "memos": []})
            else:
                payees.append({"amount": uint64(dust_value), "puzzlehash": payee_ph, "memos": []})
            # In cases where xch_spam_amount is sufficiently low,
            # the new dust should be considered a large coina and not be filtered.
            if xch_spam_amount <= dust_value:
                large_dust_coins += 1
                large_dust_balance += dust_value

        # construct and send tx
        tx: TransactionRecord = await farm_wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, dust_wallet_node, full_node_api)

        # Obtain and log important values
        all_unspent: Set[
            WalletCoinRecord
        ] = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
        small_unspent_count = len([r for r in all_unspent if r.coin.amount < xch_spam_amount])
        balance: Optional[Message] = await dust_wallet.get_confirmed_balance()
        num_coins: Optional[Message] = len(
            list(await dust_wallet_node.wallet_state_manager.get_spendable_coins_for_wallet(1))
        )

        log.info(f"Small coin count is {small_unspent_count}")
        log.info(f"Wallet balance is {balance}")
        log.info(f"Number of coins is {num_coins}")

        # The filter should have automatically been activated by now, regardless of filter value
        assert dust_coins == spam_filter_after_n_txs
        assert balance == dust_coins * dust_value + large_coin_balance + large_dust_balance
        assert num_coins == dust_coins + large_dust_coins + large_coins

        # Part 6: Clear all coins from the dust wallet.
        # Send to the dust wallet "spam_filter_after_n_txs" coins that are equal in value to "xch_spam_amount".
        # Send 1 mojo from the dust wallet. The dust wallet should receive a change coin valued at "xch_spam_amount-1".

        payee_ph = await farm_wallet.get_new_puzzlehash()
        payees: List[AmountWithPuzzlehash] = [{"amount": uint64(balance), "puzzlehash": payee_ph, "memos": []}]

        # construct and send tx
        tx: TransactionRecord = await dust_wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, dust_wallet_node, full_node_api)

        # Obtain and log important values
        all_unspent: Set[
            WalletCoinRecord
        ] = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
        unspent_count = len([r for r in all_unspent])
        balance: Optional[Message] = await dust_wallet.get_confirmed_balance()

        # Make sure the dust wallet is empty
        assert unspent_count == 0
        assert balance == 0

        # create the same number of dust coins as the filter
        if spam_filter_after_n_txs > 0:
            coins_remaining = spam_filter_after_n_txs
        else:
            # in the edge case, create one coin
            coins_remaining = 1

        # The size of the coin to send the dust wallet is the same as xch_spam_amount
        if xch_spam_amount > 1:
            coin_value = xch_spam_amount
        else:
            # Handle the edge case to make sure the coin is at least 2 mojos
            # This is needed to receive change
            coin_value = 2

        while coins_remaining > 0:
            payee_ph = await dust_wallet.get_new_puzzlehash()
            payees.append({"amount": uint64(coin_value), "puzzlehash": payee_ph, "memos": []})

            # After every 100 (at most) coins added, push the tx and advance the chain
            # This greatly speeds up the overall process
            if coins_remaining % 100 == 0 and coins_remaining != spam_filter_after_n_txs:
                # construct and send tx
                tx: TransactionRecord = await farm_wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
                await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
                last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
                assert last_block is not None
                # reset payees
                payees: List[AmountWithPuzzlehash] = []

            coins_remaining -= 1

        # construct and send tx
        tx: TransactionRecord = await farm_wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(60, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(60, wallet_is_synced, True, dust_wallet_node, full_node_api)

        # Obtain and log important values
        all_unspent: Set[
            WalletCoinRecord
        ] = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
        unspent_count = len([r for r in all_unspent])
        balance: Optional[Message] = await dust_wallet.get_confirmed_balance()

        # Verify the number of coins and value
        if spam_filter_after_n_txs > 0:
            assert unspent_count == spam_filter_after_n_txs
        else:
            # in the edge case there should be 1 coin
            assert unspent_count == 1
        assert balance == unspent_count * coin_value

        # Send a 1 mojo coin from the dust wallet to the farm wallet
        payee_ph = await farm_wallet.get_new_puzzlehash()
        payees: List[AmountWithPuzzlehash] = [{"amount": uint64(1), "puzzlehash": payee_ph, "memos": []}]

        # construct and send tx
        tx: TransactionRecord = await dust_wallet.generate_signed_transaction(uint64(0), ph, primaries=payees)
        await full_node_api.send_transaction(SendTransaction(tx.spend_bundle))

        # advance the chain and sync both wallets
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        last_block: Optional[BlockRecord] = full_node_api.full_node.blockchain.get_peak()
        assert last_block is not None
        await time_out_assert(20, wallet_is_synced, True, farm_wallet_node, full_node_api)
        await time_out_assert(20, wallet_is_synced, True, dust_wallet_node, full_node_api)

        # Obtain and log important values
        all_unspent: Set[
            WalletCoinRecord
        ] = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
        unspent_count = len([r for r in all_unspent])
        balance: Optional[Message] = await dust_wallet.get_confirmed_balance()

        # Make sure the dust wallet received a change coin worth 1 mojo less than the original coin size
        if spam_filter_after_n_txs > 0:
            assert unspent_count == spam_filter_after_n_txs
        else:
            # in the edge case there should be 1 coin
            assert unspent_count == 1
        assert balance == (unspent_count * coin_value) - 1

        # Part 7: Create NFT wallets for the farmer and dust wallets.
        #         Generate an NFT in the farmer wallet.
        #         Send the NFT to the dust wallet, which already has enough coins to trigger the dust filter.
        #         The NFT should not be filtered.

        # Start with new puzzlehashes for each wallet
        farm_ph = await farm_wallet.get_new_puzzlehash()
        dust_ph = await dust_wallet.get_new_puzzlehash()

        # Create an NFT wallet for the farmer and dust wallet
        farm_nft_wallet = await NFTWallet.create_new_nft_wallet(
            farm_wallet_node.wallet_state_manager, farm_wallet, name="FARM NFT WALLET"
        )
        dust_nft_wallet = await NFTWallet.create_new_nft_wallet(
            dust_wallet_node.wallet_state_manager, dust_wallet, name="DUST NFT WALLET"
        )

        # Create a new NFT and send it to the farmer's NFT wallet
        metadata = Program.to(
            [
                ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
                ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
            ]
        )
        farm_sb = await farm_nft_wallet.generate_new_nft(metadata)
        assert farm_sb

        # ensure hints are generated
        assert compute_memos(farm_sb)
        await time_out_assert_not_none(15, full_node_api.full_node.mempool_manager.get_spendbundle, farm_sb.name())

        # Farm a new block
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(farm_ph))
        await time_out_assert(30, farm_wallet_node.wallet_state_manager.lock.locked, False)

        # Make sure the dust wallet has enough unspent coins in that the next coin would be filtered
        # if it were a normal dust coin (and not an NFT)
        all_unspent: Set[
            WalletCoinRecord
        ] = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
        unspent_count = len([r for r in all_unspent])
        assert unspent_count >= spam_filter_after_n_txs

        # Make sure the NFT is in the farmer's NFT wallet, and the dust NFT wallet is empty
        await time_out_assert(15, get_nft_count, 1, farm_nft_wallet)
        await time_out_assert(15, get_nft_count, 0, dust_nft_wallet)

        nft_coins = await farm_nft_wallet.get_current_nfts()
        # Send the NFT to the dust wallet
        txs = await farm_nft_wallet.generate_signed_transaction(
            [uint64(nft_coins[0].coin.amount)],
            [dust_ph],
            coins={nft_coins[0].coin},
        )
        assert len(txs) == 1
        assert txs[0].spend_bundle is not None
        await farm_wallet_node.wallet_state_manager.add_pending_transaction(txs[0])
        await time_out_assert_not_none(
            15, full_node_api.full_node.mempool_manager.get_spendbundle, txs[0].spend_bundle.name()
        )
        assert compute_memos(txs[0].spend_bundle)

        # Farm a new block.
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(farm_ph))

        # Make sure the dust wallet has enough unspent coins in that the next coin would be filtered
        # if it were a normal dust coin (and not an NFT)
        all_unspent: Set[
            WalletCoinRecord
        ] = await dust_wallet_node.wallet_state_manager.coin_store.get_all_unspent_coins()
        unspent_count = len([r for r in all_unspent])
        assert unspent_count >= spam_filter_after_n_txs

        # The dust wallet should now hold the NFT. It should not be filtered
        await time_out_assert(15, get_nft_count, 0, farm_nft_wallet)
        await time_out_assert(15, get_nft_count, 1, dust_nft_wallet)

    @pytest.mark.asyncio
    async def test_retry_store(self, two_wallet_nodes, self_hostname):
        full_nodes, wallets, bt = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))

        # Trusted node sync
        wallets[0][0].config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}

        # Untrusted node sync
        wallets[1][0].config["trusted_peers"] = {}

        def flaky_get_coin_state(node, func):
            async def new_func(*args, **kwargs):
                if node.coin_state_flaky:
                    node.coin_state_flaky = False
                    raise PeerRequestException()
                else:
                    return await func(*args, **kwargs)

            return new_func

        def flaky_fetch_puzzle_solution(node, func):
            async def new_func(*args, **kwargs):
                if node.puzzle_solution_flaky:
                    node.puzzle_solution_flaky = False
                    raise PeerRequestException()
                else:
                    return await func(*args, **kwargs)

            return new_func

        def flaky_fetch_children(node, func):
            async def new_func(*args, **kwargs):
                if node.fetch_children_flaky:
                    node.fetch_children_flaky = False
                    raise PeerRequestException()
                else:
                    return await func(*args, **kwargs)

            return new_func

        def flaky_get_timestamp(node, func):
            async def new_func(*args, **kwargs):
                if node.get_timestamp_flaky:
                    node.get_timestamp_flaky = False
                    raise PeerRequestException()
                else:
                    return await func(*args, **kwargs)

            return new_func

        def flaky_info_for_puzhash(node, func):
            async def new_func(*args, **kwargs):
                if node.db_flaky:
                    node.db_flaky = False
                    raise AIOSqliteError()
                else:
                    return await func(*args, **kwargs)

            return new_func

        for wallet_node, wallet_server in wallets:
            wallet_node.coin_state_flaky = True
            wallet_node.puzzle_solution_flaky = True
            wallet_node.fetch_children_flaky = True
            wallet_node.get_timestamp_flaky = True
            wallet_node.db_flaky = True

            wallet_node.get_coin_state = flaky_get_coin_state(wallet_node, wallet_node.get_coin_state)
            wallet_node.fetch_puzzle_solution = flaky_fetch_puzzle_solution(
                wallet_node, wallet_node.fetch_puzzle_solution
            )
            wallet_node.fetch_children = flaky_fetch_children(wallet_node, wallet_node.fetch_children)
            wallet_node.get_timestamp_for_height = flaky_get_timestamp(
                wallet_node, wallet_node.get_timestamp_for_height
            )
            wallet_node.wallet_state_manager.puzzle_store.wallet_info_for_puzzle_hash = flaky_info_for_puzhash(
                wallet_node, wallet_node.wallet_state_manager.puzzle_store.wallet_info_for_puzzle_hash
            )

            await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

            wallet = wallet_node.wallet_state_manager.main_wallet
            ph = await wallet.get_new_puzzlehash()
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))

            async def len_gt_0(func, *args):
                return len((await func(*args))) > 0

            await time_out_assert(
                15, len_gt_0, True, wallet_node.wallet_state_manager.retry_store.get_all_states_to_retry
            )
            await time_out_assert(
                30, len_gt_0, False, wallet_node.wallet_state_manager.retry_store.get_all_states_to_retry
            )

            await time_out_assert(30, wallet.get_confirmed_balance, 2_000_000_000_000)

            tx = await wallet.generate_signed_transaction(1_000_000_000_000, bytes32([0] * 32), memos=[ph])
            await wallet_node.wallet_state_manager.add_pending_transaction(tx)

            async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32):
                tx = mempool.get_spendbundle(tx_id)
                if tx is None:
                    return False
                return True

            await time_out_assert(15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx.name)
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))

            await time_out_assert(
                15, len_gt_0, True, wallet_node.wallet_state_manager.retry_store.get_all_states_to_retry
            )
            await time_out_assert(
                120, len_gt_0, False, wallet_node.wallet_state_manager.retry_store.get_all_states_to_retry
            )
            assert not wallet_node.coin_state_flaky
            assert not wallet_node.puzzle_solution_flaky
            assert not wallet_node.fetch_children_flaky
            assert not wallet_node.get_timestamp_flaky
            assert not wallet_node.db_flaky
            await time_out_assert(30, wallet.get_confirmed_balance, 1_000_000_000_000)
