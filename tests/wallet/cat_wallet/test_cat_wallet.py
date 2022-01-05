import asyncio
from typing import List

import pytest

from chia.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from chia.full_node.mempool_manager import MempoolManager
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.cat_wallet.cat_utils import construct_cat_puzzle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.transaction_record import TransactionRecord
from tests.setup_nodes import setup_simulators_and_wallets
from tests.time_out_assert import time_out_assert


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


async def tx_in_pool(mempool: MempoolManager, tx_id: bytes32):
    tx = mempool.get_spendbundle(tx_id)
    if tx is None:
        return False
    return True


class TestCATWallet:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 3, {}):
            yield _

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_cat_creation(self, two_wallet_nodes, trusted):
        num_blocks = 3
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
        else:
            wallet_node.config["trusted_peers"] = {}

        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        async with wallet_node.wallet_state_manager.lock:
            cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node.wallet_state_manager, wallet, {"identifier": "genesis_by_id"}, uint64(100)
            )
            # The next 2 lines are basically a noop, it just adds test coverage
            cat_wallet = await CATWallet.create(wallet_node.wallet_state_manager, wallet, cat_wallet.wallet_info)
            await wallet_node.wallet_state_manager.add_new_wallet(cat_wallet, cat_wallet.id())

        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet.get_spendable_balance, 100)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 100)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_cat_spend(self, two_wallet_nodes, trusted):
        num_blocks = 3
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
            wallet_node_2.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        async with wallet_node.wallet_state_manager.lock:
            cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node.wallet_state_manager, wallet, {"identifier": "genesis_by_id"}, uint64(100)
            )
        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 100)

        assert cat_wallet.cat_info.limitations_program_hash is not None
        asset_id = cat_wallet.get_asset_id()

        cat_wallet_2: CATWallet = await CATWallet.create_wallet_for_cat(
            wallet_node_2.wallet_state_manager, wallet2, asset_id
        )

        assert cat_wallet.cat_info.limitations_program_hash == cat_wallet_2.cat_info.limitations_program_hash

        cat_2_hash = await cat_wallet_2.get_new_inner_hash()
        tx_records = await cat_wallet.generate_signed_transaction([uint64(60)], [cat_2_hash], fee=uint64(1))
        for tx_record in tx_records:
            await wallet.wallet_state_manager.add_pending_transaction(tx_record)
            if tx_record.spend_bundle is not None:
                await time_out_assert(
                    15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
                )

        await time_out_assert(15, cat_wallet.get_pending_change_balance, 40)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(30, wallet.get_confirmed_balance, funds * 2 - 101)

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 40)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 40)

        await time_out_assert(30, cat_wallet_2.get_confirmed_balance, 60)
        await time_out_assert(30, cat_wallet_2.get_unconfirmed_balance, 60)

        cat_hash = await cat_wallet.get_new_inner_hash()
        tx_records = await cat_wallet_2.generate_signed_transaction([uint64(15)], [cat_hash])
        for tx_record in tx_records:
            await wallet.wallet_state_manager.add_pending_transaction(tx_record)
            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 55)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 55)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_get_wallet_for_asset_id(self, two_wallet_nodes, trusted):
        num_blocks = 3
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
        else:
            wallet_node.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        async with wallet_node.wallet_state_manager.lock:
            cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node.wallet_state_manager, wallet, {"identifier": "genesis_by_id"}, uint64(100)
            )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        asset_id = cat_wallet.get_asset_id()
        await cat_wallet.set_tail_program(bytes(cat_wallet.cat_info.my_tail).hex())
        assert await wallet_node.wallet_state_manager.get_wallet_for_asset_id(asset_id) == cat_wallet

        # Test that the a default CAT will initialize correctly
        asset = DEFAULT_CATS[next(iter(DEFAULT_CATS))]
        asset_id = asset["asset_id"]
        cat_wallet_2 = await CATWallet.create_wallet_for_cat(wallet_node.wallet_state_manager, wallet, asset_id)
        assert await cat_wallet_2.get_name() == asset["name"]
        await cat_wallet_2.set_name("Test Name")
        assert await cat_wallet_2.get_name() == "Test Name"

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_cat_doesnt_see_eve(self, two_wallet_nodes, trusted):
        num_blocks = 3
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
            wallet_node_2.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        async with wallet_node.wallet_state_manager.lock:
            cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node.wallet_state_manager, wallet, {"identifier": "genesis_by_id"}, uint64(100)
            )
        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 100)

        assert cat_wallet.cat_info.limitations_program_hash is not None
        asset_id = cat_wallet.get_asset_id()

        cat_wallet_2: CATWallet = await CATWallet.create_wallet_for_cat(
            wallet_node_2.wallet_state_manager, wallet2, asset_id
        )

        assert cat_wallet.cat_info.limitations_program_hash == cat_wallet_2.cat_info.limitations_program_hash

        cat_2_hash = await cat_wallet_2.get_new_inner_hash()
        tx_records = await cat_wallet.generate_signed_transaction([uint64(60)], [cat_2_hash])
        for tx_record in tx_records:
            await wallet.wallet_state_manager.add_pending_transaction(tx_record)
            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 40)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 40)

        await time_out_assert(15, cat_wallet_2.get_confirmed_balance, 60)
        await time_out_assert(15, cat_wallet_2.get_unconfirmed_balance, 60)

        cc2_ph = await cat_wallet_2.get_new_cat_puzzle_hash()
        tx_record = await wallet.wallet_state_manager.main_wallet.generate_signed_transaction(10, cc2_ph, 0)
        await wallet.wallet_state_manager.add_pending_transaction(tx_record)
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )
        for i in range(0, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        id = cat_wallet_2.id()
        wsm = cat_wallet_2.wallet_state_manager

        async def query_and_assert_transactions(wsm, id):
            all_txs = await wsm.tx_store.get_all_transactions_for_wallet(id)
            return len(list(filter(lambda tx: tx.amount == 10, all_txs)))

        await time_out_assert(15, query_and_assert_transactions, 0, wsm, id)
        await time_out_assert(15, wsm.get_confirmed_balance_for_wallet, 60, id)
        await time_out_assert(15, cat_wallet_2.get_confirmed_balance, 60)
        await time_out_assert(15, cat_wallet_2.get_unconfirmed_balance, 60)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_cat_spend_multiple(self, three_wallet_nodes, trusted):
        num_blocks = 3
        full_nodes, wallets = three_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, wallet_server_0 = wallets[0]
        wallet_node_1, wallet_server_1 = wallets[1]
        wallet_node_2, wallet_server_2 = wallets[2]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
        wallet_2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet_0.get_new_puzzlehash()
        if trusted:
            wallet_node_0.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
            wallet_node_1.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
            wallet_node_2.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await wallet_server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await wallet_server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await wallet_server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet_0.get_confirmed_balance, funds)

        async with wallet_node_0.wallet_state_manager.lock:
            cat_wallet_0: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node_0.wallet_state_manager, wallet_0, {"identifier": "genesis_by_id"}, uint64(100)
            )
        tx_queue: List[TransactionRecord] = await wallet_node_0.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cat_wallet_0.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet_0.get_unconfirmed_balance, 100)

        assert cat_wallet_0.cat_info.limitations_program_hash is not None
        asset_id = cat_wallet_0.get_asset_id()

        cat_wallet_1: CATWallet = await CATWallet.create_wallet_for_cat(
            wallet_node_1.wallet_state_manager, wallet_1, asset_id
        )

        cat_wallet_2: CATWallet = await CATWallet.create_wallet_for_cat(
            wallet_node_2.wallet_state_manager, wallet_2, asset_id
        )

        assert cat_wallet_0.cat_info.limitations_program_hash == cat_wallet_1.cat_info.limitations_program_hash
        assert cat_wallet_0.cat_info.limitations_program_hash == cat_wallet_2.cat_info.limitations_program_hash

        cat_1_hash = await cat_wallet_1.get_new_inner_hash()
        cat_2_hash = await cat_wallet_2.get_new_inner_hash()

        tx_records = await cat_wallet_0.generate_signed_transaction([uint64(60), uint64(20)], [cat_1_hash, cat_2_hash])
        for tx_record in tx_records:
            await wallet_0.wallet_state_manager.add_pending_transaction(tx_record)
            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cat_wallet_0.get_confirmed_balance, 20)
        await time_out_assert(15, cat_wallet_0.get_unconfirmed_balance, 20)

        await time_out_assert(30, cat_wallet_1.get_confirmed_balance, 60)
        await time_out_assert(30, cat_wallet_1.get_unconfirmed_balance, 60)

        await time_out_assert(30, cat_wallet_2.get_confirmed_balance, 20)
        await time_out_assert(30, cat_wallet_2.get_unconfirmed_balance, 20)

        cat_hash = await cat_wallet_0.get_new_inner_hash()

        tx_records = await cat_wallet_1.generate_signed_transaction([uint64(15)], [cat_hash])
        for tx_record in tx_records:
            await wallet_1.wallet_state_manager.add_pending_transaction(tx_record)
            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )

        tx_records_2 = await cat_wallet_2.generate_signed_transaction([uint64(20)], [cat_hash])
        for tx_record in tx_records_2:
            await wallet_2.wallet_state_manager.add_pending_transaction(tx_record)
            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cat_wallet_0.get_confirmed_balance, 55)
        await time_out_assert(15, cat_wallet_0.get_unconfirmed_balance, 55)

        await time_out_assert(30, cat_wallet_1.get_confirmed_balance, 45)
        await time_out_assert(30, cat_wallet_1.get_unconfirmed_balance, 45)

        await time_out_assert(30, cat_wallet_2.get_confirmed_balance, 0)
        await time_out_assert(30, cat_wallet_2.get_unconfirmed_balance, 0)

        txs = await wallet_1.wallet_state_manager.tx_store.get_transactions_between(cat_wallet_1.id(), 0, 100000)
        print(len(txs))
        # Test with Memo
        tx_records_3: TransactionRecord = await cat_wallet_1.generate_signed_transaction(
            [uint64(30)], [cat_hash], memos=[[b"Markus Walburg"]]
        )
        with pytest.raises(ValueError):
            await cat_wallet_1.generate_signed_transaction(
                [uint64(30)], [cat_hash], memos=[[b"too"], [b"many"], [b"memos"]]
            )

        for tx_record in tx_records_3:
            await wallet_1.wallet_state_manager.add_pending_transaction(tx_record)
            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )
        txs = await wallet_1.wallet_state_manager.tx_store.get_transactions_between(cat_wallet_1.id(), 0, 100000)
        for tx in txs:
            if tx.amount == 30:
                memos = tx.get_memos()
                assert len(memos) == 1
                assert b"Markus Walburg" in [v for v_list in memos.values() for v in v_list]
                assert list(memos.keys())[0] in [a.name() for a in tx.spend_bundle.additions()]

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_cat_max_amount_send(self, two_wallet_nodes, trusted):
        num_blocks = 3
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
            wallet_node_2.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        async with wallet_node.wallet_state_manager.lock:
            cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node.wallet_state_manager, wallet, {"identifier": "genesis_by_id"}, uint64(100000)
            )
        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 100000)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 100000)

        assert cat_wallet.cat_info.limitations_program_hash is not None

        cat_2 = await cat_wallet.get_new_inner_puzzle()
        cat_2_hash = cat_2.get_tree_hash()
        amounts = []
        puzzle_hashes = []
        for i in range(1, 50):
            amounts.append(uint64(i))
            puzzle_hashes.append(cat_2_hash)
        spent_coint = (await cat_wallet.get_cat_spendable_coins())[0].coin
        tx_records = await cat_wallet.generate_signed_transaction(amounts, puzzle_hashes, coins={spent_coint})
        for tx_record in tx_records:
            await wallet.wallet_state_manager.add_pending_transaction(tx_record)
            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await asyncio.sleep(2)

        async def check_all_there():
            spendable = await cat_wallet.get_cat_spendable_coins()
            spendable_name_set = set()
            for record in spendable:
                spendable_name_set.add(record.coin.name())
            puzzle_hash = construct_cat_puzzle(
                CAT_MOD, cat_wallet.cat_info.limitations_program_hash, cat_2
            ).get_tree_hash()
            for i in range(1, 50):
                coin = Coin(spent_coint.name(), puzzle_hash, i)
                if coin.name() not in spendable_name_set:
                    return False
            return True

        await time_out_assert(15, check_all_there, True)
        await asyncio.sleep(5)
        max_sent_amount = await cat_wallet.get_max_send_amount()

        # 1) Generate transaction that is under the limit
        under_limit_txs = None
        try:
            under_limit_txs = await cat_wallet.generate_signed_transaction(
                [max_sent_amount - 1],
                [ph],
            )
        except ValueError:
            assert ValueError

        assert under_limit_txs is not None

        # 2) Generate transaction that is equal to limit
        at_limit_txs = None
        try:
            at_limit_txs = await cat_wallet.generate_signed_transaction(
                [max_sent_amount],
                [ph],
            )
        except ValueError:
            assert ValueError

        assert at_limit_txs is not None

        # 3) Generate transaction that is greater than limit
        above_limit_txs = None
        try:
            above_limit_txs = await cat_wallet.generate_signed_transaction(
                [max_sent_amount + 1],
                [ph],
            )
        except ValueError:
            pass

        assert above_limit_txs is None

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_cat_hint(self, two_wallet_nodes, trusted):
        num_blocks = 3
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()
        if trusted:
            wallet_node.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
            wallet_node_2.config["trusted_peers"] = {full_node_server.node_id: full_node_server.node_id}
        else:
            wallet_node.config["trusted_peers"] = {}
            wallet_node_2.config["trusted_peers"] = {}
        await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        async with wallet_node.wallet_state_manager.lock:
            cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
                wallet_node.wallet_state_manager, wallet, {"identifier": "genesis_by_id"}, uint64(100)
            )
        tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
        tx_record = tx_queue[0]
        await time_out_assert(
            15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
        )
        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 100)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 100)
        assert cat_wallet.cat_info.limitations_program_hash is not None

        cat_2_hash = await wallet2.get_new_puzzlehash()
        tx_records = await cat_wallet.generate_signed_transaction([uint64(60)], [cat_2_hash], memos=[[cat_2_hash]])

        for tx_record in tx_records:
            await wallet.wallet_state_manager.add_pending_transaction(tx_record)

            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 40)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 40)

        # First we test that no wallet was created
        asyncio.sleep(10)
        assert len(wallet_node_2.wallet_state_manager.wallets.keys()) == 1

        # Then we update the wallet's default CATs
        wallet_node_2.wallet_state_manager.default_cats = {
            cat_wallet.cat_info.limitations_program_hash.hex(): {
                "asset_id": cat_wallet.cat_info.limitations_program_hash.hex(),
                "name": "Test",
                "symbol": "TST",
            }
        }

        # Then we send another transaction
        tx_records = await cat_wallet.generate_signed_transaction([uint64(10)], [cat_2_hash], memos=[[cat_2_hash]])

        for tx_record in tx_records:
            await wallet.wallet_state_manager.add_pending_transaction(tx_record)

            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 30)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 30)

        # Now we check that another wallet WAS created
        async def check_wallets(wallet_node):
            return len(wallet_node.wallet_state_manager.wallets.keys())

        await time_out_assert(10, check_wallets, 2, wallet_node_2)
        cat_wallet_2 = wallet_node_2.wallet_state_manager.wallets[2]

        await time_out_assert(30, cat_wallet_2.get_confirmed_balance, 10)
        await time_out_assert(30, cat_wallet_2.get_unconfirmed_balance, 10)

        cat_hash = await cat_wallet.get_new_inner_hash()
        tx_records = await cat_wallet_2.generate_signed_transaction([uint64(5)], [cat_hash])
        for tx_record in tx_records:
            await wallet.wallet_state_manager.add_pending_transaction(tx_record)

            await time_out_assert(
                15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
            )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, cat_wallet.get_confirmed_balance, 35)
        await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 35)

        # @pytest.mark.asyncio

    # async def test_cat_melt_and_mint(self, two_wallet_nodes):
    #     num_blocks = 3
    #     full_nodes, wallets = two_wallet_nodes
    #     full_node_api = full_nodes[0]
    #     full_node_server = full_node_api.server
    #     wallet_node, server_2 = wallets[0]
    #     wallet_node_2, server_3 = wallets[1]
    #     wallet = wallet_node.wallet_state_manager.main_wallet
    #
    #     ph = await wallet.get_new_puzzlehash()
    #
    #     await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    #     await server_3.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    #
    #     for i in range(1, num_blocks):
    #         await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
    #
    #     funds = sum(
    #         [
    #             calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
    #             for i in range(1, num_blocks - 1)
    #         ]
    #     )
    #
    #     await time_out_assert(15, wallet.get_confirmed_balance, funds)
    #
    #     async with wallet_node.wallet_state_manager.lock:
    #         cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
    #             wallet_node.wallet_state_manager, wallet, {"identifier": "genesis_by_id"}, uint64(100000)
    #         )
    #     tx_queue: List[TransactionRecord] = await wallet_node.wallet_state_manager.tx_store.get_not_sent()
    #     tx_record = tx_queue[0]
    #     await time_out_assert(
    #         15, tx_in_pool, True, full_node_api.full_node.mempool_manager, tx_record.spend_bundle.name()
    #     )
    #     for i in range(1, num_blocks):
    #         await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(32 * b"0"))
    #
    #     await time_out_assert(15, cat_wallet.get_confirmed_balance, 100000)
    #     await time_out_assert(15, cat_wallet.get_unconfirmed_balance, 100000)
