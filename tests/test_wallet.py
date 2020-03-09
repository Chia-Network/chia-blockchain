# import asyncio

# import pytest
# from blspy import ExtendedPrivateKey

# from src.wallet.wallet_node import WalletNode
# from src.protocols import full_node_protocol
# from tests.setup_nodes import setup_node_and_wallet, test_constants, bt


# @pytest.fixture(scope="module")
# def event_loop():
#     loop = asyncio.get_event_loop()
#     yield loop


# class TestWallet:
#     @pytest.fixture(scope="function")
#     async def wallet_node(self):
#         async for _ in setup_node_and_wallet():
#             yield _

#     @pytest.mark.asyncio
#     async def test_wallet_receive_body(self, wallet_node):
#         num_blocks = 10
#         full_node_1, wallet_node, server_1, server_2 = wallet_node
#         wallet = wallet_node.wallet
#         ph = await wallet.get_new_puzzlehash()
#         blocks = bt.get_consecutive_blocks(
#             test_constants, num_blocks, [], 10, reward_puzzlehash=ph,
#         )
#         for i in range(1, len(blocks)):
#             async for _ in full_node_1.respond_block(
#                 full_node_protocol.RespondBlock(blocks[i])
#             ):
#                 pass
#         await asyncio.sleep(50)

#         assert await wallet.get_confirmed_balance() == 144000000000000

#         await wallet_node.wallet_store.close()
#         await wallet_node.tx_store.close()

#     @pytest.mark.asyncio
#     async def test_wallet_make_transaction(self, two_nodes):
#         sk = bytes(ExtendedPrivateKey.from_seed(b"")).hex()
#         sk_b = bytes(ExtendedPrivateKey.from_seed(b"b")).hex()
#         key_config = {"wallet_sk": sk}
#         key_config_b = {"wallet_sk": sk_b}

#         wallet_node = await WalletNode.create({}, key_config)
#         wallet = wallet_node.wallet
#         await wallet_node.wallet_store._clear_database()
#         await wallet_node.tx_store._clear_database()

#         wallet_node_b = await WalletNode.create({}, key_config_b)
#         wallet_b = wallet_node_b.wallet
#         await wallet_node_b.wallet_store._clear_database()
#         await wallet_node_b.tx_store._clear_database()

#         num_blocks = 10
#         ph = await wallet.get_new_puzzlehash()
#         blocks = bt.get_consecutive_blocks(
#             test_constants, num_blocks, [], 10, reward_puzzlehash=ph,
#         )

#         for i in range(1, num_blocks):
#             a = RespondBody(
#                 blocks[i].header, blocks[i].transactions_generator, blocks[i].height
#             )
#             await wallet_node.received_body(a)

#         assert await wallet.get_confirmed_balance() == 144000000000000

#         spend_bundle = await wallet.generate_signed_transaction(
#             10, await wallet_b.get_new_puzzlehash(), 0
#         )
#         await wallet.push_transaction(spend_bundle)

#         confirmed_balance = await wallet.get_confirmed_balance()
#         unconfirmed_balance = await wallet.get_unconfirmed_balance()

#         assert confirmed_balance == 144000000000000
#         assert unconfirmed_balance == confirmed_balance - 10

#         await wallet_node.wallet_store.close()
#         await wallet_node.tx_store.close()

#         await wallet_node_b.wallet_store.close()
#         await wallet_node_b.tx_store.close()
