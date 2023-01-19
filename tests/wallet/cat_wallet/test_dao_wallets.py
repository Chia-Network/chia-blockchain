import asyncio
from typing import List

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.peer_info import PeerInfo
from chia.types.blockchain_format.program import Program
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_info import LegacyCATInfo
from chia.wallet.cat_wallet.cat_utils import construct_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.dao_cat_wallet import DAOCATWallet
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.dao_wallet.dao_wallet import DAOWallet
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_info import WalletInfo
from chia.simulator.time_out_assert import time_out_assert
from tests.util.wallet_is_synced import wallet_is_synced
from chia.wallet.util.wallet_types import WalletType


class TestDAOWallet:
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_dao_creation(self, self_hostname, three_wallet_nodes, trusted):
        num_blocks = 3
        full_nodes, wallets, _ = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]
        wallet = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        ph_1 = await wallet_1.get_new_puzzlehash()

        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_1.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        await server_1.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)

        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph_1))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        await time_out_assert(20, wallet_is_synced, True, wallet_node_0, full_node_api)

        dao_wallet = await DAOWallet.create_new_dao_and_wallet(
            wallet_node_0.wallet_state_manager,
            wallet,
            200,
        )
        assert dao_wallet is not None
        treasury_id = dao_wallet.dao_info.treasury_id
        cat_tail_hash = dao_wallet.get_cat_tail_hash()

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        # await asyncio.sleep(20)
        await time_out_assert(
            60,
            dao_wallet.is_spend_retrievable,
            True,
            treasury_id,
        )

        # Create a cat wallet to test casting from CATWallet to DAOCATWallet in resync_treasury_state
        cat_wallet_1 = await CATWallet.get_or_create_wallet_for_cat(
            wallet_node_1.wallet_state_manager,
            wallet_1,
            cat_tail_hash.hex(),
        )

        dao_wallet_1 = await DAOWallet.create_new_dao_wallet_for_existing_dao(
            wallet_node_1.wallet_state_manager,
            wallet_1,
            treasury_id,
        )
        assert dao_wallet_1 is not None
        assert dao_wallet.dao_info.treasury_id == dao_wallet_1.dao_info.treasury_id
        cat_wallet_0 = None

        for wallet_id in wallet_node_0.wallet_state_manager.wallets:
            wal = wallet_node_0.wallet_state_manager.wallets[wallet_id]
            if wal.type() == WalletType.CAT:
                cat_wallet_0 = wal
        assert cat_wallet_0 is not None

        dao_cat_wallet_0 = await DAOCATWallet.get_or_create_wallet_for_cat(
            wallet_node_0.wallet_state_manager,
            wallet,
            bytes(cat_tail_hash).hex(),
        )
        vs_puz = await dao_cat_wallet_0.get_new_vote_state_puzzle()
        # breakpoint()
        cat_wallet_0.generate_signed_transaction([10], [vs_puz.get_tree_hash()])

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        fake_proposal_id = Program.to("proposal_id").get_tree_hash()
        spendable_coins = await dao_cat_wallet_0.wallet_state_manager.get_spendable_coins_for_wallet(
            dao_cat_wallet_0.id(), None
        )
        assert len(spendable_coins) > 0
        coins = await dao_cat_wallet_0.advanced_select_coins(1, fake_proposal_id)
        assert len(coins) > 0
