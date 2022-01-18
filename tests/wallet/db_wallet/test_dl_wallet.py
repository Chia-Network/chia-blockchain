import asyncio
import pytest
import time
from typing import AsyncIterator, Iterator

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16, uint32, uint64
from tests.setup_nodes import setup_simulators_and_wallets
from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.wallet.dlo_wallet.dlo_wallet import DLOWallet
from chia.types.blockchain_format.program import Program
from chia.types.spend_bundle import SpendBundle
from tests.time_out_assert import time_out_assert
from chia.wallet.util.merkle_tree import MerkleTree
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType

from tests.setup_nodes import SimulatorsAndWallets

pytestmark = pytest.mark.data_layer


@pytest.fixture(scope="module")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.get_event_loop()
    yield loop


class TestDLWallet:
    @pytest.fixture(scope="function")
    async def wallet_node(self) -> AsyncIterator[SimulatorsAndWallets]:
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self) -> AsyncIterator[SimulatorsAndWallets]:
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def three_wallet_nodes(self) -> AsyncIterator[SimulatorsAndWallets]:
        async for _ in setup_simulators_and_wallets(1, 3, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes_five_freeze(self) -> AsyncIterator[SimulatorsAndWallets]:
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def three_sim_two_wallets(self) -> AsyncIterator[SimulatorsAndWallets]:
        async for _ in setup_simulators_and_wallets(3, 2, {}):
            yield _

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_initial_creation(self, wallet_node: SimulatorsAndWallets, trusted: bool) -> None:
        full_nodes, wallets = wallet_node
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        assert wallet_node_0.wallet_state_manager is not None
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        funds = await full_node_api.farm_blocks(count=2, wallet=wallet_0)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        async with wallet_node_0.wallet_state_manager.lock:
            dl_wallet = await DataLayerWallet.create_new_dl_wallet(wallet_node_0.wallet_state_manager, wallet_0)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        async def is_singleton_confirmed(lid: bytes32) -> bool:
            rec = await dl_wallet.get_latest_singleton(lid)
            if rec is None:
                return False
            return rec.confirmed

        for i in range(0, 2):
            dl_record, std_record, launcher_id = await dl_wallet.generate_new_reporter(
                current_root, fee=uint64(1999999999999)
            )

            assert await dl_wallet.get_latest_singleton(launcher_id) is not None

            await wallet_node_0.wallet_state_manager.add_pending_transaction(dl_record)
            await wallet_node_0.wallet_state_manager.add_pending_transaction(std_record)
            await full_node_api.process_transaction_records(records=[dl_record, std_record])

            await time_out_assert(15, is_singleton_confirmed, True, launcher_id)
            await asyncio.sleep(0.5)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, 0)
        await time_out_assert(10, wallet_0.get_confirmed_balance, 0)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_tracking_non_owned(self, two_wallet_nodes: SimulatorsAndWallets, trusted: bool) -> None:
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        wallet_node_1, server_1 = wallets[1]
        assert wallet_node_0.wallet_state_manager is not None
        assert wallet_node_1.wallet_state_manager is not None
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
            wallet_node_1.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node_0.config["trusted_peers"] = {}
            wallet_node_1.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
        await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        funds = await full_node_api.farm_blocks(count=2, wallet=wallet_0)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        async with wallet_node_0.wallet_state_manager.lock:
            dl_wallet_0 = await DataLayerWallet.create_new_dl_wallet(wallet_node_0.wallet_state_manager, wallet_0)

        async with wallet_node_1.wallet_state_manager.lock:
            dl_wallet_1 = await DataLayerWallet.create_new_dl_wallet(wallet_node_1.wallet_state_manager, wallet_1)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        async def is_singleton_confirmed(wallet: DataLayerWallet, lid: bytes32) -> bool:
            latest_singleton = await wallet.get_latest_singleton(lid)
            if latest_singleton is None:
                return False
            return latest_singleton.confirmed

        dl_record, std_record, launcher_id = await dl_wallet_0.generate_new_reporter(current_root)

        assert await dl_wallet_0.get_latest_singleton(launcher_id) is not None

        await wallet_node_0.wallet_state_manager.add_pending_transaction(dl_record)
        await wallet_node_0.wallet_state_manager.add_pending_transaction(std_record)
        await full_node_api.process_transaction_records(records=[dl_record, std_record])

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_0, launcher_id)
        await asyncio.sleep(0.5)

        await dl_wallet_1.track_new_launcher_id(launcher_id)
        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_1, launcher_id)
        current_record = await dl_wallet_1.get_latest_singleton(launcher_id)
        await asyncio.sleep(0.5)

        new_root = MerkleTree([Program.to("root").get_tree_hash()]).calculate_root()
        dl_tx = await dl_wallet_0.create_update_state_spend(launcher_id, new_root)

        await wallet_node_0.wallet_state_manager.add_pending_transaction(dl_tx)
        await full_node_api.process_transaction_records(records=[dl_tx])

        await time_out_assert(15, is_singleton_confirmed, True, dl_wallet_0, launcher_id)
        await asyncio.sleep(0.5)

        async def is_tip_updated() -> bool:
            latest_singleton = await dl_wallet_1.get_latest_singleton(launcher_id)
            return latest_singleton != current_record

        await time_out_assert(15, is_tip_updated, True)

    @pytest.mark.parametrize(
        "trusted",
        [True, False],
    )
    @pytest.mark.asyncio
    async def test_lifecycle(self, wallet_node: SimulatorsAndWallets, trusted: bool) -> None:
        full_nodes, wallets = wallet_node
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_0 = wallets[0]
        assert wallet_node_0.wallet_state_manager is not None
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet

        if trusted:
            wallet_node_0.config["trusted_peers"] = {full_node_server.node_id.hex(): full_node_server.node_id.hex()}
        else:
            wallet_node_0.config["trusted_peers"] = {}

        await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)

        funds = await full_node_api.farm_blocks(count=2, wallet=wallet_0)

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        async with wallet_node_0.wallet_state_manager.lock:
            dl_wallet = await DataLayerWallet.create_new_dl_wallet(wallet_node_0.wallet_state_manager, wallet_0)

        nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
        current_tree = MerkleTree(nodes)
        current_root = current_tree.calculate_root()

        async def is_singleton_confirmed(lid: bytes32) -> bool:
            latest_singleton = await dl_wallet.get_latest_singleton(lid)
            if latest_singleton is None:
                return False
            return latest_singleton.confirmed

        dl_record, std_record, launcher_id = await dl_wallet.generate_new_reporter(current_root)

        assert await dl_wallet.get_latest_singleton(launcher_id) is not None

        await wallet_node_0.wallet_state_manager.add_pending_transaction(dl_record)
        await wallet_node_0.wallet_state_manager.add_pending_transaction(std_record)
        await full_node_api.process_transaction_records(records=[dl_record, std_record])

        await time_out_assert(15, is_singleton_confirmed, True, launcher_id)
        await asyncio.sleep(0.5)

        previous_record = await dl_wallet.get_latest_singleton(launcher_id)

        new_root = MerkleTree([Program.to("root").get_tree_hash()]).calculate_root()
        dl_tx = await dl_wallet.create_update_state_spend(launcher_id, new_root)
        new_record = await dl_wallet.get_latest_singleton(launcher_id)
        assert new_record is not None
        assert new_record != previous_record
        assert not new_record.confirmed

        await wallet_node_0.wallet_state_manager.add_pending_transaction(dl_tx)
        await full_node_api.process_transaction_records(records=[dl_tx])

        await time_out_assert(15, is_singleton_confirmed, True, launcher_id)
        await asyncio.sleep(0.5)

        for _ in range(0, 2):
            current_record = await dl_wallet.get_latest_singleton(launcher_id)
            dl_tx, _ = await dl_wallet.create_report_spend(launcher_id)
            new_record = await dl_wallet.get_latest_singleton(launcher_id)
            assert new_record is not None
            assert new_record != current_record
            assert not new_record.confirmed

            await wallet_node_0.wallet_state_manager.add_pending_transaction(dl_tx)
            await full_node_api.process_transaction_records(records=[dl_tx])

            await time_out_assert(15, is_singleton_confirmed, True, launcher_id)
            await asyncio.sleep(0.5)

        previous_record = await dl_wallet.get_latest_singleton(launcher_id)

        new_root = MerkleTree([Program.to("new root").get_tree_hash()]).calculate_root()
        dl_tx = await dl_wallet.create_update_state_spend(launcher_id, new_root)
        new_record = await dl_wallet.get_latest_singleton(launcher_id)
        assert new_record is not None
        assert new_record != previous_record
        assert not new_record.confirmed

        await wallet_node_0.wallet_state_manager.add_pending_transaction(dl_tx)
        await full_node_api.process_transaction_records(records=[dl_tx])

        await time_out_assert(15, is_singleton_confirmed, True, launcher_id)
        await asyncio.sleep(0.5)

    # @pytest.mark.skip(reason="DLO Wallet is not supported yet")
    # @pytest.mark.asyncio
    # async def test_dlo_wallet(self, three_wallet_nodes: SimulatorsAndWallets) -> None:
    #     raise  # for ignoring mypy :)
    #     time_lock = uint64(10)
    #     full_nodes, wallets = three_wallet_nodes
    #     full_node_api = full_nodes[0]
    #     full_node_api.time_per_block = 2 * time_lock
    #     full_node_server = full_node_api.server
    #     wallet_node_0, server_0 = wallets[0]
    #     wallet_node_1, server_1 = wallets[1]
    #     wallet_node_2, server_2 = wallets[2]
    #     assert wallet_node_0.wallet_state_manager is not None
    #     assert wallet_node_1.wallet_state_manager is not None
    #     assert wallet_node_2.wallet_state_manager is not None
    #     wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    #     wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    #     wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
    #
    #     ph2 = await wallet_2.get_new_puzzlehash()
    #
    #     await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    #     await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    #     await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    #
    #     funds = await full_node_api.farm_blocks(count=1, wallet=wallet_0)
    #
    #     await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
    #     await time_out_assert(10, wallet_0.get_confirmed_balance, funds)
    #
    #     nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
    #     current_tree = MerkleTree(nodes)
    #     current_root = current_tree.calculate_root()
    #
    #     # Wallet1 sets up DLWallet1
    #     async with wallet_node_0.wallet_state_manager.lock:
    #         creation_record = await DataLayerWallet.create_new_dl_wallet(
    #             wallet_node_0.wallet_state_manager, wallet_0, uint64(101), current_root
    #         )
    #
    #     dl_wallet_0: DataLayerWallet = creation_record.item
    #
    #     await full_node_api.process_transaction_records(records=creation_record.transaction_records)
    #
    #     await time_out_assert(15, dl_wallet_0.get_confirmed_balance, 101)
    #     await time_out_assert(15, dl_wallet_0.get_unconfirmed_balance, 101)
    #
    #     # Wallet1 sets up DLOWallet1
    #     async with wallet_node_1.wallet_state_manager.lock:
    #         dlo_wallet_1: DLOWallet = await DLOWallet.create_new_dlo_wallet(
    #             wallet_node_1.wallet_state_manager,
    #             wallet_1,
    #         )
    #
    #     await full_node_api.farm_blocks(count=2, wallet=wallet_1)
    #
    #     await time_out_assert(15, dlo_wallet_1.get_confirmed_balance, 0)
    #     await time_out_assert(15, dlo_wallet_1.get_unconfirmed_balance, 0)
    #     assert dl_wallet_0.dl_info.origin_coin is not None
    #     tr = await dlo_wallet_1.generate_datalayer_offer_spend(
    #         amount=uint64(201),
    #         leaf_reveal=Program.to("thing").get_tree_hash(),
    #         host_genesis_id=dl_wallet_0.dl_info.origin_coin.name(),
    #         claim_target=await wallet_2.get_new_puzzlehash(),
    #         recovery_target=await wallet_1.get_new_puzzlehash(),
    #         recovery_timelock=time_lock,
    #     )
    #     await wallet_1.push_transaction(tr)
    #     await full_node_api.process_transaction_records(records=[tr])
    #
    #     await time_out_assert(15, dlo_wallet_1.get_confirmed_balance, 201)
    #     await time_out_assert(15, dlo_wallet_1.get_unconfirmed_balance, 201)
    #
    #     # create a second DLO Wallet and claim the coin
    #     async with wallet_node_2.wallet_state_manager.lock:
    #         dlo_wallet_2: DLOWallet = await DLOWallet.create_new_dlo_wallet(
    #             wallet_node_2.wallet_state_manager,
    #             wallet_2,
    #         )
    #
    #     offer_coin = await dlo_wallet_1.get_coin()
    #     offer_full_puzzle = dlo_wallet_1.puzzle_for_pk(0x00)
    #     db_puzzle, db_innerpuz, current_root = await dl_wallet_0.get_info_for_offer_claim()
    #     inclusion_proof = current_tree.generate_proof(Program.to("thing").get_tree_hash())
    #     assert db_innerpuz is not None
    #     sb2 = await dlo_wallet_2.claim_dl_offer(
    #         offer_coin,
    #         offer_full_puzzle,
    #         db_innerpuz.get_tree_hash(),
    #         current_root,
    #         inclusion_proof,
    #     )
    #     sb = await dl_wallet_0.create_report_spend()
    #     sb = SpendBundle.aggregate([sb2, sb])
    #     tr = TransactionRecord(
    #         confirmed_at_height=uint32(0),
    #         created_at_time=uint64(int(time.time())),
    #         to_puzzle_hash=ph2,
    #         amount=uint64(201),
    #         fee_amount=uint64(0),
    #         confirmed=False,
    #         sent=uint32(0),
    #         spend_bundle=sb,
    #         additions=sb.additions(),
    #         removals=sb.removals(),
    #         memos=list(sb.get_memos().items()),
    #         wallet_id=dl_wallet_0.id(),
    #         sent_to=[],
    #         trade_id=None,
    #         type=uint32(TransactionType.OUTGOING_TX.value),
    #         name=sb.name(),
    #     )
    #     await wallet_2.push_transaction(tr)
    #     await full_node_api.process_transaction_records(records=[tr])
    #
    #     await time_out_assert(15, wallet_2.get_confirmed_balance, 201)
    #     await time_out_assert(15, wallet_2.get_unconfirmed_balance, 201)
    #
    # @pytest.mark.skip(reason="DLO wallet is not supported yet")
    # @pytest.mark.asyncio
    # async def test_dlo_wallet_reclaim(self, three_wallet_nodes: SimulatorsAndWallets) -> None:
    #     raise  # for ignoring mypy :)
    #     time_lock = uint64(10)
    #
    #     full_nodes, wallets = three_wallet_nodes
    #     full_node_api = full_nodes[0]
    #     full_node_api.time_per_block = 2 * time_lock
    #     full_node_server = full_node_api.server
    #     wallet_node_0, server_0 = wallets[0]
    #     wallet_node_1, server_1 = wallets[1]
    #     wallet_node_2, server_2 = wallets[2]
    #     assert wallet_node_0.wallet_state_manager is not None
    #     assert wallet_node_1.wallet_state_manager is not None
    #     assert wallet_node_2.wallet_state_manager is not None
    #     wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
    #     wallet_1 = wallet_node_1.wallet_state_manager.main_wallet
    #     wallet_2 = wallet_node_2.wallet_state_manager.main_wallet
    #
    #     await server_0.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    #     await server_1.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    #     await server_2.start_client(PeerInfo("localhost", uint16(full_node_server._port)), None)
    #
    #     funds = await full_node_api.farm_blocks(count=1, wallet=wallet_0)
    #
    #     await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
    #     await time_out_assert(10, wallet_0.get_confirmed_balance, funds)
    #
    #     nodes = [Program.to("thing").get_tree_hash(), Program.to([8]).get_tree_hash()]
    #     current_tree = MerkleTree(nodes)
    #     current_root = current_tree.calculate_root()
    #
    #     # Wallet1 sets up DLWallet1
    #     async with wallet_node_0.wallet_state_manager.lock:
    #         creation_record = await DataLayerWallet.create_new_dl_wallet(
    #             wallet_node_0.wallet_state_manager, wallet_0, uint64(101), current_root
    #         )
    #
    #     dl_wallet_0: DataLayerWallet = creation_record.item
    #
    #     await full_node_api.process_transaction_records(records=creation_record.transaction_records)
    #
    #     await time_out_assert(15, dl_wallet_0.get_confirmed_balance, 101)
    #     await time_out_assert(15, dl_wallet_0.get_unconfirmed_balance, 101)
    #
    #     # Wallet1 sets up DLOWallet1
    #     async with wallet_node_1.wallet_state_manager.lock:
    #         dlo_wallet_1: DLOWallet = await DLOWallet.create_new_dlo_wallet(
    #             wallet_node_1.wallet_state_manager,
    #             wallet_1,
    #         )
    #
    #     wallet_1_funds = await full_node_api.farm_blocks(count=1, wallet=wallet_1)
    #     offer_amount = 201
    #
    #     await time_out_assert(15, dlo_wallet_1.get_confirmed_balance, 0)
    #     await time_out_assert(15, dlo_wallet_1.get_unconfirmed_balance, 0)
    #     assert dl_wallet_0.dl_info.origin_coin is not None
    #     tr = await dlo_wallet_1.generate_datalayer_offer_spend(
    #         amount=uint64(offer_amount),
    #         leaf_reveal=Program.to("thing").get_tree_hash(),
    #         host_genesis_id=dl_wallet_0.dl_info.origin_coin.name(),
    #         claim_target=await wallet_2.get_new_puzzlehash(),
    #         recovery_target=await wallet_1.get_new_puzzlehash(),
    #         recovery_timelock=time_lock,
    #     )
    #     await wallet_1.push_transaction(tr)
    #     await full_node_api.process_transaction_records(records=[tr])
    #
    #     await time_out_assert(15, dlo_wallet_1.get_confirmed_balance, offer_amount)
    #     await time_out_assert(15, dlo_wallet_1.get_unconfirmed_balance, offer_amount)
    #     wallet_1_funds -= offer_amount
    #
    #     await time_out_assert(15, wallet_1.get_confirmed_balance, wallet_1_funds)
    #     await time_out_assert(15, wallet_1.get_unconfirmed_balance, wallet_1_funds)
    #
    #     transaction_record = await dlo_wallet_1.create_recover_dl_offer_spend()
    #     # Process a block to make sure the time lock for the offer has passed
    #     await full_node_api.process_blocks(count=1)
    #
    #     await full_node_api.process_transaction_records(records=[transaction_record])
    #
    #     wallet_1_funds += offer_amount
    #
    #     await time_out_assert(15, dlo_wallet_1.get_confirmed_balance, 0)
    #     await time_out_assert(15, dlo_wallet_1.get_unconfirmed_balance, 0)
    #     await time_out_assert(15, wallet_1.get_confirmed_balance, wallet_1_funds)
    #     await time_out_assert(15, wallet_1.get_unconfirmed_balance, wallet_1_funds)
