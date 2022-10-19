import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from blspy import AugSchemeMPL, G1Element, G2Element
from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.protocols.full_node_protocol import RespondBlock
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.server.server import ChiaServer
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import AmountWithPuzzlehash
from chia.wallet.wallet_node import WalletNode, get_wallet_db_path
from chia.wallet.wallet_state_manager import WalletStateManager
from chia.simulator.block_tools import BlockTools
from chia.simulator.time_out_assert import time_out_assert, time_out_assert_not_none
from tests.util.wallet_is_synced import wallet_is_synced
from tests.wallet.cat_wallet.test_cat_wallet import tx_in_pool


class TestWalletSimulator:
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_coinbase(
        self,
        wallet_node_sim_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 10
        full_nodes, wallets, _ = wallet_node_sim_and_wallet
        full_node_api = full_nodes[0]
        server_1: ChiaServer = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 2)
            ]
        )

        async def check_tx_are_pool_farm_rewards() -> bool:
            wsm: WalletStateManager = wallet_node.wallet_state_manager
            all_txs = await wsm.get_all_transactions(1)
            expected_count = (num_blocks + 1) * 2
            if len(all_txs) != expected_count:
                return False
            pool_rewards = 0
            farm_rewards = 0

            for tx in all_txs:
                if TransactionType(tx.type) == TransactionType.COINBASE_REWARD:
                    pool_rewards += 1
                elif TransactionType(tx.type) == TransactionType.FEE_REWARD:
                    farm_rewards += 1

            if pool_rewards != expected_count / 2:
                return False
            if farm_rewards != expected_count / 2:
                return False
            return True

        await time_out_assert(20, check_tx_are_pool_farm_rewards, True)
        await time_out_assert(20, wallet.get_confirmed_balance, funds)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        await time_out_assert(20, wallet.get_unconfirmed_balance, funds)

        tx = await wallet.generate_signed_transaction(
            uint64(10),
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(0),
        )
        await wallet.push_transaction(tx)

        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        await time_out_assert(20, wallet.get_unconfirmed_balance, funds - 10)
        await time_out_assert(20, full_node_api.full_node.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        new_funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, (2 * num_blocks))
            ]
        )

        await time_out_assert(30, wallet.get_confirmed_balance, new_funds - 10)
        await time_out_assert(30, wallet.get_unconfirmed_balance, new_funds - 10)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_coinbase_reorg(
        self,
        wallet_node_sim_and_wallet: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = wallet_node_sim_and_wallet
        full_node_api = full_nodes[0]
        fn_server = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {fn_server.node_id.hex(): fn_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        await asyncio.sleep(5)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(25, wallet.get_confirmed_balance, funds)

        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(2), uint32(num_blocks + 6), bytes32(32 * b"0"), None)
        )

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 2)
            ]
        )

        await time_out_assert(20, wallet.get_confirmed_balance, funds)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_send_to_three_peers(
        self,
        three_sim_two_wallets: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 10
        full_nodes, wallets, _ = three_sim_two_wallets

        wallet_0, wallet_server_0 = wallets[0]

        full_node_api_0 = full_nodes[0]
        full_node_api_1 = full_nodes[1]
        full_node_api_2 = full_nodes[2]

        full_node_0 = full_node_api_0.full_node
        full_node_1 = full_node_api_1.full_node
        full_node_2 = full_node_api_2.full_node

        server_0 = full_node_0.server
        server_1 = full_node_1.server
        server_2 = full_node_2.server

        ph = await wallet_0.wallet_state_manager.main_wallet.get_new_puzzlehash()
        if trusted:
            wallet_0.config["trusted_peers"] = {
                server_0.node_id.hex(): server_0.node_id.hex(),
                server_1.node_id.hex(): server_1.node_id.hex(),
                server_2.node_id.hex(): server_2.node_id.hex(),
            }

        else:
            wallet_0.config["trusted_peers"] = {}

        # wallet0 <-> sever0
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)

        for i in range(0, num_blocks):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        all_blocks = await full_node_api_0.get_all_full_blocks()

        for block in all_blocks:
            await full_node_1.respond_block(RespondBlock(block))
            await full_node_2.respond_block(RespondBlock(block))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(20, wallet_0.wallet_state_manager.main_wallet.get_confirmed_balance, funds)

        tx = await wallet_0.wallet_state_manager.main_wallet.generate_signed_transaction(
            uint64(10), bytes32(32 * b"0"), uint64(0)
        )
        assert tx.spend_bundle is not None
        await wallet_0.wallet_state_manager.main_wallet.push_transaction(tx)

        await time_out_assert_not_none(20, full_node_0.mempool_manager.get_spendbundle, tx.spend_bundle.name())

        # wallet0 <-> sever1
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_1._port)), wallet_0.on_connect)

        await time_out_assert_not_none(20, full_node_1.mempool_manager.get_spendbundle, tx.spend_bundle.name())

        # wallet0 <-> sever2
        await wallet_server_0.start_client(PeerInfo(self_hostname, uint16(server_2._port)), wallet_0.on_connect)

        await time_out_assert_not_none(20, full_node_2.mempool_manager.get_spendbundle, tx.spend_bundle.name())

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction_hop(
        self,
        two_wallet_nodes_five_freeze: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 10
        full_nodes, wallets, _ = two_wallet_nodes_five_freeze
        full_node_api_0 = full_nodes[0]
        full_node_0 = full_node_api_0.full_node
        server_0 = full_node_0.server

        wallet_node_0, wallet_0_server = wallets[0]
        wallet_node_1, wallet_1_server = wallets[1]

        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
        ph = await wallet_0.get_new_puzzlehash()
        if trusted:
            wallet_node_0.config["trusted_peers"] = {server_0.node_id.hex(): server_0.node_id.hex()}
            wallet_node_1.config["trusted_peers"] = {server_0.node_id.hex(): server_0.node_id.hex()}
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}
        await wallet_0_server.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)

        await wallet_1_server.start_client(PeerInfo(self_hostname, uint16(server_0._port)), None)

        for i in range(0, num_blocks):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        await time_out_assert(90, wallet_is_synced, True, wallet_node_0, full_node_api_0)
        await time_out_assert(20, wallet_0.get_confirmed_balance, funds)
        await time_out_assert(20, wallet_0.get_unconfirmed_balance, funds)

        assert await wallet_0.get_confirmed_balance() == funds
        assert await wallet_0.get_unconfirmed_balance() == funds

        tx = await wallet_0.generate_signed_transaction(
            uint64(10),
            await wallet_node_1.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(0),
        )

        await wallet_0.push_transaction(tx)

        await time_out_assert(20, full_node_0.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)
        # Full node height 11, wallet height 9
        await time_out_assert(20, wallet_0.get_confirmed_balance, funds)
        await time_out_assert(20, wallet_0.get_unconfirmed_balance, funds - 10)

        for i in range(0, 4):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))

        # here it's num_blocks + 1 because our last reward is included in the first block that we just farmed
        new_funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        # Full node height 17, wallet height 15
        await time_out_assert(20, wallet_0.get_confirmed_balance, new_funds - 10)
        await time_out_assert(20, wallet_0.get_unconfirmed_balance, new_funds - 10)
        await time_out_assert(20, wallet_1.get_confirmed_balance, 10)

        tx = await wallet_1.generate_signed_transaction(uint64(5), await wallet_0.get_new_puzzlehash(), uint64(0))
        await wallet_1.push_transaction(tx)
        await time_out_assert(20, full_node_0.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)

        for i in range(0, 4):
            await full_node_api_0.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))

        await wallet_0.get_confirmed_balance()
        await wallet_0.get_unconfirmed_balance()
        await wallet_1.get_confirmed_balance()

        await time_out_assert(20, wallet_0.get_confirmed_balance, new_funds - 5)
        await time_out_assert(20, wallet_0.get_unconfirmed_balance, new_funds - 5)
        await time_out_assert(20, wallet_1.get_confirmed_balance, 5)

    # @pytest.mark.asyncio
    # async def test_wallet_finds_full_node(self):
    #     node_iters = [
    #         setup_full_node(
    #             test_constants,
    #             "blockchain_test.db",
    #             11234,
    #             introducer_port=11236,
    #             simulator=False,
    #         ),
    #         setup_wallet_node(
    #             11235,
    #             test_constants,
    #             None,
    #             introducer_port=11236,
    #         ),
    #         setup_introducer(11236),
    #     ]
    #
    #     full_node_api = await node_iters[0].__anext__()
    #     wallet, wallet_server = await node_iters[1].__anext__()
    #     introducer, introducer_server = await node_iters[2].__anext__()
    #
    #     async def has_full_node():
    #         outbound: List[WSChiaConnection] = wallet.server.get_outgoing_connections()
    #         for connection in outbound:
    #             if connection.connection_type is NodeType.FULL_NODE:
    #                 return True
    #         return False
    #
    #     await time_out_assert(
    #         2 * 60,
    #         has_full_node,
    #         True,
    #     )
    #     await _teardown_nodes(node_iters)
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_make_transaction_with_fee(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_1 = full_nodes[0]

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        await time_out_assert(20, wallet.get_unconfirmed_balance, funds)

        assert await wallet.get_confirmed_balance() == funds
        assert await wallet.get_unconfirmed_balance() == funds
        tx_amount = 3200000000000
        tx_fee = 10
        tx = await wallet.generate_signed_transaction(
            uint64(tx_amount),
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(tx_fee),
        )
        assert tx.spend_bundle is not None

        fees = tx.spend_bundle.fees()
        assert fees == tx_fee

        await wallet.push_transaction(tx)
        await time_out_assert(20, full_node_1.full_node.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)

        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        await time_out_assert(20, wallet.get_unconfirmed_balance, funds - tx_amount - tx_fee)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))

        new_funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        await time_out_assert(20, wallet.get_confirmed_balance, new_funds - tx_amount - tx_fee)
        await time_out_assert(20, wallet.get_unconfirmed_balance, new_funds - tx_amount - tx_fee)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_create_hit_max_send_amount(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_1 = full_nodes[0]

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(20, wallet.get_confirmed_balance, funds)

        primaries: List[AmountWithPuzzlehash] = []
        for i in range(0, 60):
            primaries.append({"puzzlehash": ph, "amount": uint64(1000000000 + i), "memos": []})

        tx_split_coins = await wallet.generate_signed_transaction(uint64(1), ph, uint64(0), primaries=primaries)
        assert tx_split_coins.spend_bundle is not None

        await wallet.push_transaction(tx_split_coins)
        await time_out_assert(
            15, tx_in_pool, True, full_node_1.full_node.mempool_manager, tx_split_coins.spend_bundle.name()
        )
        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        await time_out_assert(90, wallet.get_confirmed_balance, funds)
        max_sent_amount = await wallet.get_max_send_amount()

        # 1) Generate transaction that is under the limit
        under_limit_tx = None
        try:
            under_limit_tx = await wallet.generate_signed_transaction(
                uint64(max_sent_amount - 1),
                ph,
                uint64(0),
            )
        except ValueError:
            assert ValueError

        assert under_limit_tx is not None

        # 2) Generate transaction that is equal to limit
        at_limit_tx = None
        try:
            at_limit_tx = await wallet.generate_signed_transaction(
                uint64(max_sent_amount),
                ph,
                uint64(0),
            )
        except ValueError:
            assert ValueError

        assert at_limit_tx is not None

        # 3) Generate transaction that is greater than limit
        above_limit_tx = None
        try:
            above_limit_tx = await wallet.generate_signed_transaction(
                uint64(max_sent_amount + 1),
                ph,
                uint64(0),
            )
        except ValueError:
            pass

        assert above_limit_tx is None

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_prevent_fee_theft(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_1 = full_nodes[0]

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_1.full_node.server.node_id.hex(): full_node_1.full_node.server.node_id.hex()
            }
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_1.full_node.server._port)), None)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )

        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        await time_out_assert(20, wallet.get_unconfirmed_balance, funds)

        assert await wallet.get_confirmed_balance() == funds
        assert await wallet.get_unconfirmed_balance() == funds
        tx_amount = 3200000000000
        tx_fee = 300000000000
        tx = await wallet.generate_signed_transaction(
            uint64(tx_amount),
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(tx_fee),
        )
        assert tx.spend_bundle is not None

        # extract coin_spend from generated spend_bundle
        for cs in tx.spend_bundle.coin_spends:
            if cs.additions() == []:
                stolen_cs = cs
        # get a legit signature
        stolen_sb = await wallet.sign_transaction([stolen_cs])
        now = uint64(int(time.time()))
        add_list = list(stolen_sb.additions())
        rem_list = list(stolen_sb.removals())
        name = stolen_sb.name()
        stolen_tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=now,
            to_puzzle_hash=bytes32(32 * b"0"),
            amount=uint64(0),
            fee_amount=uint64(stolen_cs.coin.amount),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=stolen_sb,
            additions=add_list,
            removals=rem_list,
            wallet_id=wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=name,
            memos=list(compute_memos(stolen_sb).items()),
        )
        await wallet.push_transaction(stolen_tx)

        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        await time_out_assert(20, wallet.get_unconfirmed_balance, funds - stolen_cs.coin.amount)

        for i in range(0, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))

        # Funds have not decreased because stolen_tx was rejected
        outstanding_coinbase_rewards = 2000000000000
        await time_out_assert(20, wallet.get_confirmed_balance, funds + outstanding_coinbase_rewards)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_tx_reorg(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        fn_server = full_node_api.full_node.server

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        ph2 = await wallet_2.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {fn_server.node_id.hex(): fn_server.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {fn_server.node_id.hex(): fn_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        await server_3.start_client(PeerInfo(self_hostname, uint16(fn_server._port)), None)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i)) for i in range(1, num_blocks)]
        )
        # Waits a few seconds to receive rewards
        all_blocks = await full_node_api.get_all_full_blocks()

        # Ensure that we use a coin that we will not reorg out
        coin = list(all_blocks[-3].get_included_reward_coins())[0]
        await asyncio.sleep(5)

        tx = await wallet.generate_signed_transaction(uint64(1000), ph2, coins={coin})
        assert tx.spend_bundle is not None
        await wallet.push_transaction(tx)
        await full_node_api.full_node.respond_transaction(tx.spend_bundle, tx.name)
        await time_out_assert(20, full_node_api.full_node.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)
        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        for i in range(0, 2):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))
        await time_out_assert(20, wallet_2.get_confirmed_balance, 1000)
        funds -= 1000

        await time_out_assert(20, wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to, 7)
        peak = full_node_api.full_node.blockchain.get_peak()
        assert peak is not None
        peak_height = peak.height
        print(peak_height)

        # Perform a reorg, which will revert the transaction in the full node and wallet, and cause wallet to resubmit
        await full_node_api.reorg_from_index_to_new_index(
            ReorgProtocol(uint32(peak_height - 3), uint32(peak_height + 3), bytes32(32 * b"0"), None)
        )

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, peak_height - 2)
            ]
        )

        await time_out_assert(20, full_node_api.full_node.blockchain.get_peak_height, peak_height + 3)
        await time_out_assert(20, wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to, peak_height + 3)

        # Farm a few blocks so we can confirm the resubmitted transaction
        for i in range(0, num_blocks):
            await asyncio.sleep(1)
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))

        # By this point, the transaction should be confirmed
        await time_out_assert(20, wallet.get_confirmed_balance, funds - 1000)

        unconfirmed = await wallet_node.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(int(wallet.id()))
        assert len(unconfirmed) == 0
        tx_record = await wallet_node.wallet_state_manager.tx_store.get_transaction_record(tx.name)
        assert tx_record is not None
        removed = tx_record.removals[0]
        added = tx_record.additions[0]
        added_1 = tx_record.additions[1]
        wallet_coin_record_rem = await wallet_node.wallet_state_manager.coin_store.get_coin_record(removed.name())
        assert wallet_coin_record_rem is not None
        assert wallet_coin_record_rem.spent

        coin_record_full_node = await full_node_api.full_node.coin_store.get_coin_record(removed.name())
        assert coin_record_full_node is not None
        assert coin_record_full_node.spent
        add_1_coin_record_full_node = await full_node_api.full_node.coin_store.get_coin_record(added.name())
        assert add_1_coin_record_full_node is not None
        assert add_1_coin_record_full_node.confirmed_block_index > 0
        add_2_coin_record_full_node = await full_node_api.full_node.coin_store.get_coin_record(added_1.name())
        assert add_2_coin_record_full_node is not None
        assert add_2_coin_record_full_node.confirmed_block_index > 0

    @pytest.mark.parametrize(
        "trusted",
        [False],
    )
    @pytest.mark.asyncio
    async def test_address_sliding_window(
        self,
        wallet_node_100_pk: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        full_nodes, wallets, _ = wallet_node_100_pk
        full_node_api = full_nodes[0]
        server_1: ChiaServer = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
        wallet = wallet_node.wallet_state_manager.main_wallet

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        puzzle_hashes = []
        for i in range(211):
            pubkey = master_sk_to_wallet_sk(wallet_node.wallet_state_manager.private_key, uint32(i)).get_g1()
            puzzle: Program = wallet.puzzle_for_pk(pubkey)
            puzzle_hash: bytes32 = puzzle.get_tree_hash()
            puzzle_hashes.append(puzzle_hash)

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[0]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[210]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[114]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))

        await time_out_assert(60, wallet.get_confirmed_balance, 2 * 10**12)

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[50]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))

        await time_out_assert(60, wallet.get_confirmed_balance, 8 * 10**12)

        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[113]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hashes[209]))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32(32 * b"0")))
        await time_out_assert(60, wallet.get_confirmed_balance, 12 * 10**12)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_sign_message(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        api_0 = WalletRpcApi(wallet_node)
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        message = "Hello World"
        response = await api_0.sign_message_by_address({"address": encode_puzzle_hash(ph, "xch"), "message": message})
        puzzle: Program = Program.to(("Chia Signed Message", message))

        assert AugSchemeMPL.verify(
            G1Element.from_bytes(bytes.fromhex(response["pubkey"])),
            puzzle.get_tree_hash(),
            G2Element.from_bytes(bytes.fromhex(response["signature"])),
        )

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_wallet_transaction_options(
        self,
        two_wallet_nodes: Tuple[List[FullNodeSimulator], List[Tuple[WalletNode, ChiaServer]], BlockTools],
        trusted: bool,
        self_hostname: str,
    ) -> None:
        num_blocks = 5
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        server_1 = full_node_api.full_node.server

        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]

        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
            wallet_node_2.config["trusted_peers"] = {server_1.node_id.hex(): server_1.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        await time_out_assert(20, wallet.get_unconfirmed_balance, funds)

        AMOUNT_TO_SEND = 4000000000000
        coins = await wallet.select_coins(uint64(AMOUNT_TO_SEND))
        coin_list = list(coins)

        tx = await wallet.generate_signed_transaction(
            uint64(AMOUNT_TO_SEND),
            await wallet_node_2.wallet_state_manager.main_wallet.get_new_puzzlehash(),
            uint64(0),
            coins=coins,
            origin_id=coin_list[2].name(),
        )
        assert tx.spend_bundle is not None
        paid_coin = [coin for coin in tx.spend_bundle.additions() if coin.amount == AMOUNT_TO_SEND][0]
        assert paid_coin.parent_coin_info == coin_list[2].name()
        await wallet.push_transaction(tx)

        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        await time_out_assert(20, wallet.get_unconfirmed_balance, funds - AMOUNT_TO_SEND)
        await time_out_assert(20, full_node_api.full_node.mempool_manager.get_spendbundle, tx.spend_bundle, tx.name)

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32([0] * 32)))

        await time_out_assert(20, wallet.get_confirmed_balance, funds - AMOUNT_TO_SEND)
        await time_out_assert(20, wallet.get_unconfirmed_balance, funds - AMOUNT_TO_SEND)


def test_get_wallet_db_path_v2_r1() -> None:
    root_path: Path = Path("/x/y/z/.chia/mainnet").resolve()
    config: Dict[str, Any] = {
        "database_path": "wallet/db/blockchain_wallet_v2_r1_CHALLENGE_KEY.sqlite",
        "selected_network": "mainnet",
    }
    fingerprint: str = "1234567890"
    wallet_db_path: Path = get_wallet_db_path(root_path, config, fingerprint)

    assert wallet_db_path == root_path.joinpath("wallet/db/blockchain_wallet_v2_r1_mainnet_1234567890.sqlite")


def test_get_wallet_db_path_v2() -> None:
    root_path: Path = Path("/x/y/z/.chia/mainnet").resolve()
    config: Dict[str, Any] = {
        "database_path": "wallet/db/blockchain_wallet_v2_CHALLENGE_KEY.sqlite",
        "selected_network": "mainnet",
    }
    fingerprint: str = "1234567890"
    wallet_db_path: Path = get_wallet_db_path(root_path, config, fingerprint)

    assert wallet_db_path == root_path.joinpath("wallet/db/blockchain_wallet_v2_r1_mainnet_1234567890.sqlite")


def test_get_wallet_db_path_v1() -> None:
    root_path: Path = Path("/x/y/z/.chia/mainnet").resolve()
    config: Dict[str, Any] = {
        "database_path": "wallet/db/blockchain_wallet_v1_CHALLENGE_KEY.sqlite",
        "selected_network": "mainnet",
    }
    fingerprint: str = "1234567890"
    wallet_db_path: Path = get_wallet_db_path(root_path, config, fingerprint)

    assert wallet_db_path == root_path.joinpath("wallet/db/blockchain_wallet_v2_r1_mainnet_1234567890.sqlite")


def test_get_wallet_db_path_testnet() -> None:
    root_path: Path = Path("/x/y/z/.chia/testnet").resolve()
    config: Dict[str, Any] = {
        "database_path": "wallet/db/blockchain_wallet_v2_CHALLENGE_KEY.sqlite",
        "selected_network": "testnet",
    }
    fingerprint: str = "1234567890"
    wallet_db_path: Path = get_wallet_db_path(root_path, config, fingerprint)

    assert wallet_db_path == root_path.joinpath("wallet/db/blockchain_wallet_v2_r1_testnet_1234567890.sqlite")
