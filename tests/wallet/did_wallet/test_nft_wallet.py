import asyncio
from typing import List

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.nft_wallet.nft_info import NFTInfo
from chia.wallet.nft_wallet.nft_puzzles import get_nft_info_from_puzzle
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.transaction_record import TransactionRecord
from tests.time_out_assert import time_out_assert, time_out_assert_not_none

# pytestmark = pytest.mark.skip("TODO: Fix tests")


async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32):
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


class TestNFTWallet:
    @pytest.mark.parametrize(
        "trusted",
        [True],
    )
    @pytest.mark.asyncio
    async def test_nft_wallet_trade_chia_and_cat(self, three_wallet_nodes, trusted):
        num_blocks = 5
        full_nodes, wallets = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]
        wallet_node_2, server_2 = wallets[2]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
        wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet_0.get_new_puzzlehash()
        ph1 = await wallet_1.get_new_puzzlehash()
        ph2 = await wallet_2.get_new_puzzlehash()

        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_1.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        # Wallet1 sets up DIDWallet1 without any backup set
        async with wallet_node_0.wallet_state_manager.lock:
            did_wallet_0: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_0.wallet_state_manager, wallet_0, uint64(101)
            )

        spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(wallet_0.id())

        spend_bundle = spend_bundle_list[0].spend_bundle
        await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, did_wallet_0.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_unconfirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_pending_change_balance, 0)

        nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, did_wallet_0.id()
        )
        metadata = Program.to(
            [
                ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
                ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
            ]
        )
        tr = await nft_wallet_0.generate_new_nft(metadata, uint64(2000), ph)

        await time_out_assert_not_none(
            5, full_node_api.full_node.mempool_manager.get_spendbundle, tr.spend_bundle.name()
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await asyncio.sleep(3)
        coins = nft_wallet_0.nft_wallet_info.my_nft_coins
        assert len(coins) == 1

        # Wallet2 sets up DIDWallet2 without any backup set
        async with wallet_node_1.wallet_state_manager.lock:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_1.wallet_state_manager, wallet_1, uint64(201)
            )

        spend_bundle_list = await wallet_node_1.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(wallet_1.id())

        spend_bundle = spend_bundle_list[0].spend_bundle
        await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 201)
        await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 201)

        async with wallet_node_1.wallet_state_manager.lock:
            cat_wallet_1: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_1.wallet_state_manager, wallet_1, {"identifier": "genesis_by_id"}, uint64(100)
            )
        tx_queue: List[TransactionRecord] = await wallet_node_1.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cat_wallet_1.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet_1.get_unconfirmed_balance, 100)

        assert cat_wallet_1.cat_info.limitations_program_hash is not None
        asset_id = cat_wallet_1.get_asset_id()

        cat_wallet_0: CATWallet = await CATWallet.create_wallet_for_cat(
            wallet_node_0.wallet_state_manager, wallet_0, asset_id
        )

        assert cat_wallet_1.cat_info.limitations_program_hash == cat_wallet_0.cat_info.limitations_program_hash

        nft_wallet_1 = await NFTWallet.create_new_nft_wallet(
            wallet_node_1.wallet_state_manager, wallet_1, did_wallet_1.id()
        )
        # nft_coin_info: NFTCoinInfo,
        # new_did,
        # new_did_parent,
        # new_did_inner_hash,
        # new_did_amount,
        # trade_price_list,
        did_coin_threeple = await did_wallet_1.get_info_for_recovery()
        trade_price_list = [[10], [20, bytes.fromhex(asset_id)]]
        # trade_price_list = [[10]]

        sb = await nft_wallet_0.transfer_nft(
            coins[0].coin.name(),
            nft_wallet_1.nft_wallet_info.my_did,
            did_coin_threeple[1],
            trade_price_list,
        )
        assert sb is not None

        full_sb = await nft_wallet_1.receive_nft(sb)
        assert full_sb is not None
        # await nft_wallet_0.receive_nft(sb)

        # from chia.wallet.util.debug_spend_bundle import debug_spend_bundle
        # debug_spend_bundle(full_sb)
        # breakpoint()
        await asyncio.sleep(3)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
        await asyncio.sleep(10)

        coins = nft_wallet_0.nft_wallet_info.my_nft_coins
        assert len(coins) == 0
        coins = nft_wallet_1.nft_wallet_info.my_nft_coins
        assert len(coins) == 1

        await time_out_assert(15, cat_wallet_0.get_confirmed_balance, 4)
        await time_out_assert(15, cat_wallet_0.get_unconfirmed_balance, 4)

        # Send it back to original owner
        did_coin_threeple = await did_wallet_0.get_info_for_recovery()
        trade_price_list = [[10]]

        await asyncio.sleep(10)

        nsb = await nft_wallet_1.transfer_nft(
            coins[0].coin.name(),
            nft_wallet_0.nft_wallet_info.my_did,
            did_coin_threeple[1],
            trade_price_list,
        )
        assert sb is not None

        full_sb = await nft_wallet_0.receive_nft(nsb)

        assert full_sb is not None
        await asyncio.sleep(5)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await asyncio.sleep(10)
        coins = nft_wallet_0.nft_wallet_info.my_nft_coins
        assert len(coins) == 1

        nft_info: NFTInfo = get_nft_info_from_puzzle(coins[0].full_puzzle, coins[0].coin)
        assert nft_info.data_uris[0] == "https://www.chia.net/img/branding/chia-logo.svg"

        coins = nft_wallet_1.nft_wallet_info.my_nft_coins
        assert len(coins) == 0

    @pytest.mark.parametrize(
        "trusted",
        [True],
    )
    @pytest.mark.asyncio
    async def test_nft_wallet_creation_no_trade_price(self, three_wallet_nodes, trusted):
        num_blocks = 5
        full_nodes, wallets = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]
        wallet_node_2, server_2 = wallets[2]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
        wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet_0.get_new_puzzlehash()
        ph1 = await wallet_1.get_new_puzzlehash()
        ph2 = await wallet_2.get_new_puzzlehash()

        if trusted:
            wallet_node_0.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_1.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
            wallet_node_2.config["trusted_peers"] = {
                full_node_api.full_node.server.node_id.hex(): full_node_api.full_node.server.node_id.hex()
            }
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        # Wallet1 sets up DIDWallet1 without any backup set
        async with wallet_node_0.wallet_state_manager.lock:
            did_wallet_0: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_0.wallet_state_manager, wallet_0, uint64(101)
            )

        spend_bundle_list = await wallet_node_0.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(wallet_0.id())

        spend_bundle = spend_bundle_list[0].spend_bundle
        await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, did_wallet_0.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_unconfirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_pending_change_balance, 0)

        nft_wallet_0 = await NFTWallet.create_new_nft_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, did_wallet_0.id()
        )
        metadata = Program.to(
            [
                ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
                ("h", "0xD4584AD463139FA8C0D9F68F4B59F185"),
            ]
        )
        tr = await nft_wallet_0.generate_new_nft(metadata, 2000, ph)

        await time_out_assert_not_none(
            5, full_node_api.full_node.mempool_manager.get_spendbundle, tr.spend_bundle.name()
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await asyncio.sleep(3)
        coins = nft_wallet_0.nft_wallet_info.my_nft_coins
        assert len(coins) == 1

        # Wallet2 sets up DIDWallet2 without any backup set
        async with wallet_node_1.wallet_state_manager.lock:
            did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
                wallet_node_1.wallet_state_manager, wallet_1, uint64(201)
            )

        spend_bundle_list = await wallet_node_1.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(wallet_1.id())

        spend_bundle = spend_bundle_list[0].spend_bundle
        await time_out_assert_not_none(5, full_node_api.full_node.mempool_manager.get_spendbundle, spend_bundle.name())

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 201)
        await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 201)
        nft_wallet_1 = await NFTWallet.create_new_nft_wallet(
            wallet_node_1.wallet_state_manager, wallet_1, did_wallet_1.id()
        )
        # nft_coin_info: NFTCoinInfo,
        # new_did,
        # new_did_parent,
        # new_did_inner_hash,
        # new_did_amount,
        # trade_price_list,
        did_coin_threeple = await did_wallet_1.get_info_for_recovery()
        trade_price_list = 0

        sb = await nft_wallet_0.transfer_nft(
            coins[0].coin.name(),
            nft_wallet_1.nft_wallet_info.my_did,
            did_coin_threeple[1],
            trade_price_list,
        )
        assert sb is not None

        # full_sb = await nft_wallet_1.receive_nft(sb)
        # await nft_wallet_1.receive_nft(sb)
        assert sb is not None
        await asyncio.sleep(5)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))
        await asyncio.sleep(5)

        coins = nft_wallet_0.nft_wallet_info.my_nft_coins
        assert len(coins) == 0
        coins = nft_wallet_1.nft_wallet_info.my_nft_coins
        assert len(coins) == 1

        # Send it back to original owner
        did_coin_threeple = await did_wallet_0.get_info_for_recovery()
        trade_price_list = 0

        await asyncio.sleep(3)

        nsb = await nft_wallet_1.transfer_nft(
            coins[0].coin.name(),
            nft_wallet_0.nft_wallet_info.my_did,
            did_coin_threeple[1],
            trade_price_list,
        )
        assert sb is not None

        # full_sb = await nft_wallet_0.receive_nft(nsb)
        # await nft_wallet_0.receive_nft(nsb)
        assert nsb is not None
        await asyncio.sleep(5)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph1))

        await asyncio.sleep(5)
        coins = nft_wallet_0.nft_wallet_info.my_nft_coins
        assert len(coins) == 1

        coins = nft_wallet_1.nft_wallet_info.my_nft_coins
        assert len(coins) == 0
