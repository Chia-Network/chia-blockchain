# import asyncio
# from pathlib import Path
# from secrets import token_bytes
#
# import pytest
#
# from chia.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
# from chia.simulator.simulator_protocol import FarmNewBlockProtocol
# from chia.types.peer_info import PeerInfo
# from chia.util.ints import uint16, uint32, uint64
# from tests.setup_nodes import setup_simulators_and_wallets
# from chia.wallet.cc_wallet.cc_wallet import CCWallet
# from tests.time_out_assert import time_out_assert
#
#
# @pytest.fixture(scope="module")
# def event_loop():
#     loop = asyncio.get_event_loop()
#     yield loop
#
#
# class TestCCWalletBackup:
#     @pytest.fixture(scope="function")
#     async def two_wallet_nodes(self):
#         async for _ in setup_simulators_and_wallets(1, 1, {}):
#             yield _
#
#     @pytest.mark.asyncio
#     async def test_coin_backup(self, two_wallet_nodes):
#         num_blocks = 3
#         full_nodes, wallets = two_wallet_nodes
#         full_node_api = full_nodes[0]
#         full_node_server = full_node_api.full_node.server
#         wallet_node, server_2 = wallets[0]
#         wallet = wallet_node.wallet_state_manager.main_wallet
#
#         ph = await wallet.get_new_puzzlehash()
#
#         await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
#
#         funds = sum(
#             [
#                 calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
#                 for i in range(1, num_blocks - 1)
#             ]
#         )
#
#         await time_out_assert(15, wallet.get_confirmed_balance, funds)
#
#         cc_wallet: CCWallet = await CCWallet.create_new_cc(wallet_node.wallet_state_manager, wallet, uint64(100))
#
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
#
#         await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
#         await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)
#
#         # Write backup to file
#         filename = f"test-backup-{token_bytes(16).hex()}"
#         file_path = Path(filename)
#         await wallet_node.wallet_state_manager.create_wallet_backup(file_path)
#
#         # Close wallet and restart
#         db_path = wallet_node.wallet_state_manager.db_path
#         wallet_node._close()
#         await wallet_node._await_closed()
#
#         db_path.unlink()
#
#         started = await wallet_node._start()
#         assert started is False
#
#         await wallet_node._start(backup_file=file_path)
#
#         await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), wallet_node.on_connect)
#
#         all_wallets = wallet_node.wallet_state_manager.wallets
#         assert len(all_wallets) == 2
#
#         cc_wallet_from_backup = wallet_node.wallet_state_manager.wallets[2]
#
#         await time_out_assert(15, cc_wallet_from_backup.get_confirmed_balance, 100)
#         if file_path.exists():
#             file_path.unlink()
