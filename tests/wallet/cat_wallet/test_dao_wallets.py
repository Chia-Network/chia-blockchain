import asyncio
from typing import List

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_info import LegacyCATInfo
from chia.wallet.cat_wallet.cat_utils import construct_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.dao_wallet.dao_wallet import DAOWallet
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.wallet_info import WalletInfo
from chia.simulator.time_out_assert import time_out_assert
from tests.util.wallet_is_synced import wallet_is_synced


class TestDAOWallet:
    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_dao_creation(self, self_hostname, two_wallet_nodes, trusted):
        num_blocks = 3
        full_nodes, wallets, _ = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks + 1)
            ]
        )

        await time_out_assert(20, wallet.get_confirmed_balance, funds)
        await time_out_assert(20, wallet_is_synced, True, wallet_node, full_node_api)

        dao_wallet = await DAOWallet.create_new_dao_and_wallet(
            wallet_node.wallet_state_manager,
            wallet,
            200,
        )
        breakpoint()
        assert dao_wallet is not None
