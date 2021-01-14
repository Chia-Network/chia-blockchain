# import asyncio
# from typing import List
#
# import pytest
#
# from src.simulator.simulator_protocol import FarmNewBlockProtocol
# from src.types.peer_info import PeerInfo
# from src.util.ints import uint16, uint32, uint64
# from src.wallet.wallet_coin_record import WalletCoinRecord
# from tests.setup_nodes import setup_simulators_and_wallets
# from src.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
# from src.wallet.cc_wallet.cc_wallet import CCWallet
# from tests.time_out_assert import time_out_assert
#
#
# @pytest.fixture(scope="module")
# def event_loop():
#     loop = asyncio.get_event_loop()
#     yield loop
#
#
# class TestCCWallet:
#     @pytest.fixture(scope="function")
#     async def wallet_node(self):
#         async for _ in setup_simulators_and_wallets(1, 1, {}):
#             yield _
#
#     @pytest.fixture(scope="function")
#     async def two_wallet_nodes(self):
#         async for _ in setup_simulators_and_wallets(1, 2, {}):
#             yield _
#
#     @pytest.fixture(scope="function")
#     async def three_wallet_nodes(self):
#         async for _ in setup_simulators_and_wallets(1, 3, {}):
#             yield _
#
#     @pytest.mark.asyncio
#     async def test_colour_creation(self, two_wallet_nodes):
#         num_blocks = 3
#         full_nodes, wallets = two_wallet_nodes
#         full_node__api = full_nodes[0]
#         full_node_server = full_node__api.server
#         wallet_node, server_2 = wallets[0]
#         wallet = wallet_node.wallet_state_manager.main_wallet
#
#         ph = await wallet.get_new_puzzlehash()
#
#         await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#         for i in range(1, num_blocks):
#             await full_node__api.farm_new_block(FarmNewBlockProtocol(ph))
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
#             await full_node__api.farm_new_block(FarmNewBlockProtocol(32 * b"0"))
#
#         await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
#         await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)
#
#     @pytest.mark.asyncio
#     async def test_cc_spend(self, two_wallet_nodes):
#         num_blocks = 3
#         full_nodes, wallets = two_wallet_nodes
#         full_node_api = full_nodes[0]
#         full_node_server = full_node_api.server
#         wallet_node, server_2 = wallets[0]
#         wallet_node_2, server_3 = wallets[1]
#         wallet = wallet_node.wallet_state_manager.main_wallet
#         wallet2 = wallet_node_2.wallet_state_manager.main_wallet
#
#         ph = await wallet.get_new_puzzlehash()
#
#         await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#         await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
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
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(32 * b"0"))
#
#         await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
#         await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)
#
#         assert cc_wallet.cc_info.my_genesis_checker is not None
#         colour = cc_wallet.get_colour()
#
#         cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(wallet_node_2.wallet_state_manager, wallet2,
#         colour)
#
#         assert cc_wallet.cc_info.my_genesis_checker == cc_wallet_2.cc_info.my_genesis_checker
#
#         cc_2_hash = await cc_wallet_2.get_new_inner_hash()
#         tx_record = await cc_wallet.generate_signed_transaction([uint64(60)], [cc_2_hash])
#         await wallet.wallet_state_manager.add_pending_transaction(tx_record)
#
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
#
#         await time_out_assert(15, cc_wallet.get_confirmed_balance, 40)
#         await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 40)
#
#         await time_out_assert(30, cc_wallet_2.get_confirmed_balance, 60)
#         await time_out_assert(30, cc_wallet_2.get_unconfirmed_balance, 60)
#
#         cc_hash = await cc_wallet.get_new_inner_hash()
#         tx_record = await cc_wallet_2.generate_signed_transaction([uint64(15)], [cc_hash])
#
#         await wallet.wallet_state_manager.add_pending_transaction(tx_record)
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
#
#         await time_out_assert(15, cc_wallet.get_confirmed_balance, 55)
#         await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 55)
#
#     @pytest.mark.asyncio
#     async def test_get_wallet_for_colour(self, two_wallet_nodes):
#         num_blocks = 3
#         full_nodes, wallets = two_wallet_nodes
#         full_node_api = full_nodes[0]
#         full_node_server = full_node_api.server
#         wallet_node, server_2 = wallets[0]
#         wallet = wallet_node.wallet_state_manager.main_wallet
#
#         ph = await wallet.get_new_puzzlehash()
#
#         await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
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
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(32 * b"0"))
#
#         colour = cc_wallet.get_colour()
#         assert await wallet_node.wallet_state_manager.get_wallet_for_colour(colour) == cc_wallet
#
#     @pytest.mark.asyncio
#     async def test_generate_zero_val(self, two_wallet_nodes):
#         num_blocks = 4
#         full_nodes, wallets = two_wallet_nodes
#         full_node_api = full_nodes[0]
#         full_node_server = full_node_api.server
#         wallet_node, server_2 = wallets[0]
#         wallet_node_2, server_3 = wallets[1]
#         wallet = wallet_node.wallet_state_manager.main_wallet
#         wallet2 = wallet_node_2.wallet_state_manager.main_wallet
#
#         ph = await wallet.get_new_puzzlehash()
#
#         await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#         await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
#
#         funds = sum(
#             [
#                 calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
#                 for i in range(1, num_blocks - 1)
#             ]
#         )
#         await time_out_assert(15, wallet.get_confirmed_balance, funds)
#
#         cc_wallet: CCWallet = await CCWallet.create_new_cc(wallet_node.wallet_state_manager, wallet, uint64(100))
#
#         ph = await wallet2.get_new_puzzlehash()
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
#
#         await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
#         await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)
#
#         assert cc_wallet.cc_info.my_genesis_checker is not None
#         colour = cc_wallet.get_colour()
#
#         cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(wallet_node_2.wallet_state_manager, wallet2,
#         colour)
#
#         assert cc_wallet.cc_info.my_genesis_checker == cc_wallet_2.cc_info.my_genesis_checker
#
#         await cc_wallet_2.generate_zero_val_coin()
#
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
#
#         unspent: List[WalletCoinRecord] = list(
#             await cc_wallet_2.wallet_state_manager.get_spendable_coins_for_wallet(cc_wallet_2.id())
#         )
#
#         assert len(unspent) == 1
#         assert unspent.pop().coin.amount == 0
#
#     @pytest.mark.asyncio
#     async def test_cc_spend_uncoloured(self, two_wallet_nodes):
#         num_blocks = 3
#         full_nodes, wallets = two_wallet_nodes
#         full_node_api = full_nodes[0]
#         full_node_server = full_node_api.server
#         wallet_node, server_2 = wallets[0]
#         wallet_node_2, server_3 = wallets[1]
#         wallet = wallet_node.wallet_state_manager.main_wallet
#         wallet2 = wallet_node_2.wallet_state_manager.main_wallet
#
#         ph = await wallet.get_new_puzzlehash()
#
#         await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#         await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
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
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(32 * b"0"))
#
#         await time_out_assert(15, cc_wallet.get_confirmed_balance, 100)
#         await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 100)
#
#         assert cc_wallet.cc_info.my_genesis_checker is not None
#         colour = cc_wallet.get_colour()
#
#         cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(wallet_node_2.wallet_state_manager, wallet2,
#         colour)
#
#         assert cc_wallet.cc_info.my_genesis_checker == cc_wallet_2.cc_info.my_genesis_checker
#
#         cc_2_hash = await cc_wallet_2.get_new_inner_hash()
#         tx_record = await cc_wallet.generate_signed_transaction([uint64(60)], [cc_2_hash])
#         await wallet.wallet_state_manager.add_pending_transaction(tx_record)
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(32 * b"0"))
#
#         await time_out_assert(15, cc_wallet.get_confirmed_balance, 40)
#         await time_out_assert(15, cc_wallet.get_unconfirmed_balance, 40)
#
#         await time_out_assert(15, cc_wallet_2.get_confirmed_balance, 60)
#         await time_out_assert(15, cc_wallet_2.get_unconfirmed_balance, 60)
#
#         cc2_ph = await cc_wallet_2.get_new_cc_puzzle_hash()
#         tx_record = await wallet.wallet_state_manager.main_wallet.generate_signed_transaction(10, cc2_ph, 0)
#         await wallet.wallet_state_manager.add_pending_transaction(tx_record)
#
#         for i in range(0, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(32 * b"0"))
#
#         id = cc_wallet_2.id()
#         wsm = cc_wallet_2.wallet_state_manager
#         await time_out_assert(15, wsm.get_confirmed_balance_for_wallet, 70, id)
#         await time_out_assert(15, cc_wallet_2.get_confirmed_balance, 60)
#         await time_out_assert(15, cc_wallet_2.get_unconfirmed_balance, 60)
#
#     @pytest.mark.asyncio
#     async def test_cc_spend_multiple(self, three_wallet_nodes):
#         num_blocks = 3
#         full_nodes, wallets = three_wallet_nodes
#         full_node_api = full_nodes[0]
#         full_node_server = full_node_api.server
#         wallet_node_0, wallet_server_0 = wallets[0]
#         wallet_node_1, wallet_server_1 = wallets[1]
#         wallet_node_2, wallet_server_2 = wallets[2]
#         wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
#         wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
#         wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
#
#         ph = await wallet_0.get_new_puzzlehash()
#
#         await wallet_server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#         await wallet_server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#         await wallet_server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
#
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(ph))
#
#         funds = sum(
#             [
#                 calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
#                 for i in range(1, num_blocks - 1)
#             ]
#         )
#
#         await time_out_assert(15, wallet_0.get_confirmed_balance, funds)
#
#         cc_wallet_0: CCWallet = await CCWallet.create_new_cc(wallet_node_0.wallet_state_manager, wallet_0,
#         uint64(100))
#
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(32 * b"0"))
#
#         await time_out_assert(15, cc_wallet_0.get_confirmed_balance, 100)
#         await time_out_assert(15, cc_wallet_0.get_unconfirmed_balance, 100)
#
#         assert cc_wallet_0.cc_info.my_genesis_checker is not None
#         colour = cc_wallet_0.get_colour()
#
#         cc_wallet_1: CCWallet = await CCWallet.create_wallet_for_cc(
#             wallet_node_1.wallet_state_manager, wallet_1, colour
#         )
#
#         cc_wallet_2: CCWallet = await CCWallet.create_wallet_for_cc(
#             wallet_node_2.wallet_state_manager, wallet_2, colour
#         )
#
#         assert cc_wallet_0.cc_info.my_genesis_checker == cc_wallet_1.cc_info.my_genesis_checker
#         assert cc_wallet_0.cc_info.my_genesis_checker == cc_wallet_2.cc_info.my_genesis_checker
#
#         cc_1_hash = await cc_wallet_1.get_new_inner_hash()
#         cc_2_hash = await cc_wallet_2.get_new_inner_hash()
#
#         tx_record = await cc_wallet_0.generate_signed_transaction([uint64(60), uint64(20)], [cc_1_hash, cc_2_hash])
#         await wallet_0.wallet_state_manager.add_pending_transaction(tx_record)
#
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(32 * b"0"))
#
#         await time_out_assert(15, cc_wallet_0.get_confirmed_balance, 20)
#         await time_out_assert(15, cc_wallet_0.get_unconfirmed_balance, 20)
#
#         await time_out_assert(30, cc_wallet_1.get_confirmed_balance, 60)
#         await time_out_assert(30, cc_wallet_1.get_unconfirmed_balance, 60)
#
#         await time_out_assert(30, cc_wallet_2.get_confirmed_balance, 20)
#         await time_out_assert(30, cc_wallet_2.get_unconfirmed_balance, 20)
#
#         cc_hash = await cc_wallet_0.get_new_inner_hash()
#
#         tx_record = await cc_wallet_1.generate_signed_transaction([uint64(15)], [cc_hash])
#         await wallet_1.wallet_state_manager.add_pending_transaction(tx_record)
#
#         tx_record_2 = await cc_wallet_2.generate_signed_transaction([uint64(20)], [cc_hash])
#         await wallet_2.wallet_state_manager.add_pending_transaction(tx_record_2)
#
#         for i in range(1, num_blocks):
#             await full_node_api.farm_new_block(FarmNewBlockProtocol(32 * b"0"))
#
#         await time_out_assert(15, cc_wallet_0.get_confirmed_balance, 55)
#         await time_out_assert(15, cc_wallet_0.get_unconfirmed_balance, 55)
#
#         await time_out_assert(30, cc_wallet_1.get_confirmed_balance, 45)
#         await time_out_assert(30, cc_wallet_1.get_unconfirmed_balance, 45)
#
#         await time_out_assert(30, cc_wallet_2.get_confirmed_balance, 0)
#         await time_out_assert(30, cc_wallet_2.get_unconfirmed_balance, 0)
