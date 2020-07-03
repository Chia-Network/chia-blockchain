import asyncio
from pathlib import Path

import pytest

from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.types.peer_info import PeerInfo
from src.util.ints import uint16, uint32, uint64
from tests.setup_nodes import setup_simulators_and_wallets
from src.consensus.block_rewards import calculate_base_fee, calculate_block_reward
from src.wallet.cc_wallet.cc_wallet import CCWallet
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestCCWalletBackup:
    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(
            1, 2, {"COINBASE_FREEZE_PERIOD": 0}
        ):
            yield _

    @pytest.mark.asyncio
    async def test_coin_backup(self, two_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1, server_1 = full_nodes[0]
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, 4):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_base_fee(uint32(i)) + calculate_block_reward(uint32(i))
                for i in range(1, 4 - 2)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        cc_wallet: CCWallet = await CCWallet.create_new_cc(
            wallet_node.wallet_state_manager, wallet, uint64(100)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)

        # Write backup to file
        file_path = Path("backup_file")
        await wallet_node.wallet_state_manager.create_wallet_backup(file_path)

        # Close wallet and restart
        wallet_node._close()
        await wallet_node._await_closed()

        wallet_node.wallet_state_manager.db_path.unlink()

        await wallet_node._start(backup_file=file_path)
        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        all_wallets = wallet_node.wallet_state_manager.wallets
        assert len(all_wallets) == 2

        cc_wallet_from_backup = wallet_node.wallet_state_manager.wallets[2]

        await time_out_assert(15, cc_wallet_from_backup.get_confirmed_balance, 100)
