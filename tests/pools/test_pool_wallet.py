import asyncio
import logging
import pytest

from secrets import token_bytes
from typing import Any, Callable, Dict, List, Optional, Set
from collections import defaultdict
from blspy import G1Element
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin

# from chia.util.wallet_tools import WalletTool
# import time
# from secrets import token_bytes
# from blspy import AugSchemeMPL
# from chia.consensus.block_rewards import (
#    calculate_base_farmer_reward,
#    calculate_pool_reward,
# )

# from chia.protocols.full_node_protocol import RespondBlock

# from chia.server.server import ChiaServer
# from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
from chia.types.blockchain_format.program import Program

# from chia.types.coin_solution import CoinSolution
# from chia.types.peer_info import PeerInfo
# from chia.types.spend_bundle import SpendBundle
# from chia.util.ints import uint16, uint32, uint64
# from chia.wallet.derivation_record import DerivationRecord
# from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.pools.pool_wallet import PoolWallet

# from chia.wallet.transaction_record import TransactionRecord
# from chia.wallet.util.transaction_type import TransactionType
# from chia.wallet.wallet_state_manager import WalletStateManager
# from clvm_tools import binutils

# from tests.setup_nodes import self_hostname, setup_simulators_and_wallets
# from tests.time_out_assert import time_out_assert, time_out_assert_not_none
# from tests.wallet.cc_wallet.test_cc_wallet import tx_in_pool
from chia.pools.pool_puzzles import POOL_MEMBER_HASH, P2_SINGLETON_HASH, POOL_ESCAPING_INNER_HASH
from chia.pools.pool_wallet_info import PoolSingletonState, create_pool_state
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_info import WalletInfo

# from tests.core.full_node.test_conditions import


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class MockWallet:
    # wallet_tool: WalletTool
    wallet_state_manager: Any
    log: logging.Logger
    wallet_id: uint32
    # secret_key_store: SecretKeyStore
    cost_of_single_tx: Optional[int]

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = None,
    ):
        from chia.wallet.wallet import Wallet

        self = Wallet()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_id = info.id
        # self.secret_key_store = SecretKeyStore()
        self.cost_of_single_tx = None
        self.generate_signed_transaction = Wallet.generate_signed_transaction
        return self

    def __init__(self, wallet_state_manager: Any, wallet_info: WalletInfo):
        # w = await Wallet.create(wallet_state_manager, wallet_info)

        self.wallet_state_manager = wallet_state_manager
        self.wallet_id = wallet_info.id

    async def id(self):
        return 7

    async def get_new_puzzlehash(self) -> bytes32:
        return Program.to(["test_hash"]).get_tree_hash()

    async def get_confirmed_balance(self, unspent_records=None) -> uint128:
        # return await self.wallet_state_manager.get_confirmed_balance_for_wallet(self.id(), unspent_records)
        return 700

    async def select_coins(self, amount, exclude: List[Coin] = None) -> Set[Coin]:
        return set([Coin(token_bytes(32), token_bytes(32), uint64(9999999999))])


class MockWalletUserStore:
    def __init__(self):
        self.wallet_store = {}
        self._next_available_wallet_id = 1
        self.create_wallet(1, "Standard Wallet", WalletType.STANDARD_WALLET, None)

    def _get_next_id(self):
        self._next_available_wallet_id += 1
        return self._next_available_wallet_id - 1

    async def create_wallet(
        self, name: str, wallet_type: int, data: str, id: Optional[int] = None
    ) -> Optional[WalletInfo]:
        if id is None:
            id = self._get_next_id()
        else:
            if id in self.wallet_store.keys():
                raise AssertionError("Trying to create wallet id {id} that already exists")
        if wallet_type not in (v.value for v in WalletType):
            raise AssertionError("Trying to create wallet with invalid wallet type {wallet_type}")
        new_wallet_info = WalletInfo(id, name, wallet_type, data)
        self.wallet_store[id] = new_wallet_info
        return new_wallet_info
        # return WalletInfo(77 if id is None else id, name, wallet_type, data)


class MockWalletStateManager:
    from blspy import AugSchemeMPL, G1Element, PrivateKey

    private_key: PrivateKey
    puzzle_hash_created_callbacks: Dict = defaultdict(lambda *x: None)

    def _fake_farm(self):
        escaping_parent = token_bytes(32)
        fake_coins_by_puzzle_hash = {
            POOL_ESCAPING_INNER_HASH: Coin(escaping_parent, POOL_ESCAPING_INNER_HASH, 1),
            POOL_MEMBER_HASH: Coin(escaping_parent, POOL_MEMBER_HASH, 1),
            P2_SINGLETON_HASH: Coin(escaping_parent, P2_SINGLETON_HASH, 1),
        }
        for puzzlehash, callbacks in self.puzzle_hash_created_callbacks.items():
            for callback in callbacks:
                if puzzlehash in fake_coins_by_puzzle_hash:
                    coin = fake_coins_by_puzzle_hash[puzzlehash]
                    callback(coin)

    def __init__(self, wallet_user_store, sk: PrivateKey = AugSchemeMPL.key_gen(bytes([2] * 32))):
        self.user_store = wallet_user_store
        self.private_key = sk

    def get_public_key(self, index: uint32) -> G1Element:
        from chia.wallet.derive_keys import master_sk_to_wallet_sk

        return master_sk_to_wallet_sk(self.private_key, index).get_g1()

    def set_coin_with_puzzlehash_created_callback(self, puzzlehash, callback: Callable):
        """
        Callback to be called when new coin is seen with specified puzzlehash
        """
        self.puzzle_hash_created_callbacks[puzzlehash] = callback

    async def get_unused_derivation_record(self, wallet_id: uint32) -> DerivationRecord:
        from chia.wallet.util.wallet_types import WalletType

        index = 1
        puzzlehash = bytes32(b"\x03" * 32)
        pubkey: G1Element = self.get_public_key(uint32(index))
        # puzzle: Program = target_wallet.puzzle_for_pk(bytes(pubkey))
        puzzle = Program.to(1)
        puzzlehash: bytes32 = puzzle.get_tree_hash()
        wallet_type = WalletType.STANDARD_WALLET  # target_wallet.wallet_info.type,
        wallet_id = uint32(99)  # target_wallet.wallet_info.id),

        return DerivationRecord(uint32(index), puzzlehash, pubkey, wallet_type, wallet_id)


def pool_state():
    pass


async def create_pool_wallet():
    wallet = MockWallet()
    # wallet = WalletTool(test_constants)
    wallet_user_store = MockWalletUserStore()
    wallet_state_manager = MockWalletStateManager(wallet_user_store)

    current_state = PoolSingletonState.PENDING_CREATION
    target_state = PoolSingletonState.FARMING_TO_POOL
    rewards_puzzlehash = bytes32(b"\x01" * 32)
    pool_url = "https://pool.example.org/"
    relative_lock_height = 10
    pool_puzzlehash = bytes32(b"\x02" * 32)
    owner_pubkey = 0xFADEDDAB

    initial_pending_state = create_pool_state(PoolSingletonState.PENDING_CREATION, rewards_puzzlehash, None, 0)
    initial_pooling_state = create_pool_state(
        PoolSingletonState.FARMING_TO_POOL, pool_puzzlehash, pool_url, relative_lock_height
    )
    initial_self_pooling_state = create_pool_state(PoolSingletonState.SELF_POOLING, rewards_puzzlehash, None, 0)
    # owner_pubkey, pool_puzzlehash
    pool_wallet: PoolWallet = await PoolWallet.create_new_pool_wallet(
        wallet_state_manager, wallet, initial_pooling_state
    )

    return pool_wallet


async def setup_sim():

    wallet_user_store = MockWalletUserStore()
    wallet_state_manager = MockWalletStateManager(wallet_user_store)

    wallet_info2 = WalletInfo(2, "Pool Wallet A", WalletType.POOLING_WALLET, None)
    wallet = await MockWallet.create(wallet_state_manager, wallet_info2)
    # wallet = MockWallet(wallet_state_manager, wallet_info2)
    # wallet = WalletTool(test_constants, wallet_info2)

    return wallet, wallet_user_store, wallet_state_manager


class TestPoolWallet:
    @pytest.mark.asyncio
    async def test_initial_state_verification(self):
        wallet, wallet_user_store, wallet_state_manager = setup_sim()
        current_state = PoolSingletonState.PENDING_CREATION
        target_state = PoolSingletonState.FARMING_TO_POOL
        rewards_puzzlehash = bytes(0x1 * 32)
        pool_url = "https://pool.example.org/"
        relative_lock_height = 10
        pool_puzzlehash = bytes(0x2 * 32)

        owner_pubkey = 0xFADEDDAB

        initial_pool_state = create_pool_state(current_state, rewards_puzzlehash, pool_url, relative_lock_height)
        with pytest.raises(ValueError):
            pool_wallet: PoolWallet = await PoolWallet.create_new_pool_wallet(
                wallet_state_manager, wallet, initial_pool_state
            )

    @pytest.mark.asyncio
    async def test_invalid_states(self):
        good_puzzlehash = bytes32(b"\x01" * 32)
        good_pool_url = "https://pool.example.org/"
        good_relative_lock_height = 10
        bad_relative_lock_height = None

        short_puzzlehash = b"\x01"
        long_puzzlehash = b"\x01" * 33
        bad_states = [
            [PoolSingletonState.PENDING_CREATION, short_puzzlehash, None, None],  # bad relative_lock_height
            [PoolSingletonState.PENDING_CREATION, short_puzzlehash, None, good_relative_lock_height],  # bad puzzlehash
            [PoolSingletonState.PENDING_CREATION, long_puzzlehash, None, good_relative_lock_height],  # bad puzzlehash
            [0, good_puzzlehash, None, good_relative_lock_height],  # state out of bounds
            [0, good_puzzlehash, None, good_relative_lock_height],  # state out of bounds
            # self pooling should not have a pool_url set, and relative_lock_height should be zero
            # [PoolSingletonState.SELF_POOLING, good_puzzlehash, good_pool_url, None],
            # [PoolSingletonState.SELF_POOLING, good_puzzlehash, None, good_relative_lock_height],
            # [PoolSingletonState.SELF_POOLING, good_puzzlehash, good_pool_url, good_relative_lock_height],
            # [PoolSingletonState.LEAVING_POOL, good_puzzlehash, None, None],
            # [PoolSingletonState.FARMING_TO_POOL, good_puzzlehash, None, None],
        ]
        for s in bad_states:
            with pytest.raises(AssertionError):
                bad_state = create_pool_state(s[0], s[1], s[2], s[3])

    @pytest.mark.asyncio
    async def test_valid_states(self):
        good_puzzlehash = bytes32(b"\x01" * 32)
        pool_url = "https://pool.example.org/"
        relative_lock_height = 10
        states = [
            [PoolSingletonState.PENDING_CREATION, good_puzzlehash, None, relative_lock_height],
            [PoolSingletonState.SELF_POOLING, good_puzzlehash, None, relative_lock_height],
            [PoolSingletonState.LEAVING_POOL, good_puzzlehash, pool_url, 10],
            [PoolSingletonState.FARMING_TO_POOL, good_puzzlehash, pool_url, 11],
        ]
        for s in states:
            good_state = create_pool_state(s[0], s[1], s[2], s[3])
            print(good_state)

    @pytest.mark.asyncio
    async def test_reject_empty_rewards_puzhash(self):
        with pytest.raises(TypeError):
            # rewards_puzhash = await self.standard_wallet.get_new_puzzlehash()
            rewards_puzhash = bytes32(
                hexstr_to_bytes("8c44f7253baaf9ab424e105f71ea6448d7bc5501a8d2b4ae3079844bfcd0f596")
            )
            state = create_pool_state(PoolSingletonState.PENDING_CREATION, None, None, None)

    @pytest.mark.asyncio
    async def test_accept_valid_rewards_puzhash(self):
        # Accept valid puzhash
        rewards_puzhash = bytes32(hexstr_to_bytes("8c44f7253baaf9ab424e105f71ea6448d7bc5501a8d2b4ae3079844bfcd0f596"))
        state = create_pool_state(PoolSingletonState.PENDING_CREATION, rewards_puzhash, None, 0)

    @pytest.mark.asyncio
    async def test_wallet_creation(self):
        wallet, wallet_user_store, wallet_state_manager = setup_sim()

        current_state = PoolSingletonState.PENDING_CREATION
        target_state = PoolSingletonState.FARMING_TO_POOL
        rewards_puzzlehash = bytes32(b"\x01" * 32)
        pool_url = "https://pool.example.org/"
        relative_lock_height = 10
        pool_puzzlehash = bytes32(b"\x02" * 32)
        owner_pubkey = 0xFADEDDAB

        initial_pending_state = create_pool_state(PoolSingletonState.PENDING_CREATION, rewards_puzzlehash, None, 0)
        initial_pooling_state = create_pool_state(
            PoolSingletonState.FARMING_TO_POOL, pool_puzzlehash, pool_url, relative_lock_height
        )
        initial_self_pooling_state = create_pool_state(PoolSingletonState.SELF_POOLING, rewards_puzzlehash, None, 0)
        # owner_pubkey, pool_puzzlehash
        pool_wallet: PoolWallet = await PoolWallet.create_new_pool_wallet(
            wallet_state_manager, wallet, initial_pooling_state
        )

    @pytest.mark.asyncio
    async def test_join_pool(self):
        wallet, wallet_user_store, wallet_state_manager = await setup_sim()

        current_state = PoolSingletonState.PENDING_CREATION
        target_state = PoolSingletonState.FARMING_TO_POOL
        rewards_puzzlehash = bytes32(b"\x01" * 32)
        pool_url = "https://pool.example.org/"
        relative_lock_height = 10
        pool_puzzlehash = bytes32(b"\x02" * 32)
        owner_pubkey = 0xFADEDDAB
        fee = 1

        self_pooling_state = create_pool_state(PoolSingletonState.SELF_POOLING, rewards_puzzlehash, None, 0)
        pooling_state = create_pool_state(
            PoolSingletonState.FARMING_TO_POOL, pool_puzzlehash, pool_url, relative_lock_height
        )
        # owner_pubkey, pool_puzzlehash
        pool_wallet: PoolWallet = await PoolWallet.create_new_pool_wallet(
            wallet_state_manager, wallet, self_pooling_state
        )

        # could test that rewards puzhash is not ours
        await pool_wallet.join_pool(pool_url, rewards_puzzlehash, relative_lock_height, fee)


"""
        # Wallet1 sets up DIDWallet1 without any backup set
        did_wallet_0: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, uint64(101)
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, did_wallet_0.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_unconfirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_pending_change_balance, 0)
        # Wallet1 sets up DIDWallet_1 with DIDWallet_0 as backup
        backup_ids = [bytes.fromhex(did_wallet_0.get_my_DID())]
        did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, uint64(201), backup_ids
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 201)
        await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 201)
        await time_out_assert(15, did_wallet_1.get_pending_change_balance, 0)

        filename = "test.backup"
        did_wallet_1.create_backup(filename)

        # Wallet2 recovers DIDWallet2 to a new set of keys
        did_wallet_2 = await DIDWallet.create_new_did_wallet_from_recovery(
            wallet_node_1.wallet_state_manager, wallet_1, filename
        )
        coins = await did_wallet_1.select_coins(1)
        coin = coins.copy().pop()
        assert did_wallet_2.did_info.temp_coin == coin
        newpuz = await did_wallet_2.get_new_puzzle()
        newpuzhash = newpuz.get_tree_hash()
        pubkey = bytes(
            (await did_wallet_2.wallet_state_manager.get_unused_derivation_record(did_wallet_2.wallet_info.id)).pubkey
        )
        message_spend_bundle = await did_wallet_0.create_attestment(
            did_wallet_2.did_info.temp_coin.name(), newpuzhash, pubkey, "test.attest"
        )
        print(f"pubkey: {pubkey}")

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        (
            test_info_list,
            test_message_spend_bundle,
        ) = await did_wallet_2.load_attest_files_for_recovery_spend(["test.attest"])
        assert message_spend_bundle == test_message_spend_bundle

        await did_wallet_2.recovery_spend(
            did_wallet_2.did_info.temp_coin,
            newpuzhash,
            test_info_list,
            pubkey,
            test_message_spend_bundle,
        )
        print(f"pubkey: {did_wallet_2}")

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(45, did_wallet_2.get_confirmed_balance, 201)
        await time_out_assert(45, did_wallet_2.get_unconfirmed_balance, 201)

        # DIDWallet3 spends the money back to itself
        ph2 = await wallet_1.get_new_puzzlehash()
        await did_wallet_2.create_spend(ph2)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, wallet_1.get_confirmed_balance, 201)
        await time_out_assert(15, wallet_1.get_unconfirmed_balance, 201)
        pass

    #@pytest.mark.asyncio
    #async def test_creation_of_singleton(self, two_wallet_nodes):
    #    pass


    async def test_creation_of_singleton_failure(self, two_wallet_nodes):
        pass

    async def test_sync_from_blockchain_pooling(self, two_wallet_nodes):
        pass

    async def test_sync_from_blockchain_self_pooling(self, two_wallet_nodes):
        pass

    async def test_leave_pool(self, two_wallet_nodes):
        pass

    async def test_enter_pool_with_unclaimed_rewards(self, two_wallet_nodes):
        pass


class TestDIDWallet:
    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def two_wallet_nodes_five_freeze(self):
        async for _ in setup_simulators_and_wallets(1, 2, {}):
            yield _

    @pytest.fixture(scope="function")
    async def three_sim_two_wallets(self):
        async for _ in setup_simulators_and_wallets(3, 2, {}):
            yield _

    @pytest.mark.asyncio
    async def test_creation_from_backup_file(self, two_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.server
        wallet_node_0, server_2 = wallets[0]
        wallet_node_1, server_3 = wallets[1]
        wallet_0 = wallet_node_0.wallet_state_manager.main_wallet
        wallet_1 = wallet_node_1.wallet_state_manager.main_wallet

        ph = await wallet_0.get_new_puzzlehash()

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

        await time_out_assert(10, wallet_0.get_unconfirmed_balance, funds)
        await time_out_assert(10, wallet_0.get_confirmed_balance, funds)

        # Wallet1 sets up DIDWallet1 without any backup set
        did_wallet_0: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, uint64(101)
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, did_wallet_0.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_unconfirmed_balance, 101)
        await time_out_assert(15, did_wallet_0.get_pending_change_balance, 0)
        # Wallet1 sets up DIDWallet_1 with DIDWallet_0 as backup
        backup_ids = [bytes.fromhex(did_wallet_0.get_my_DID())]
        did_wallet_1: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_0.wallet_state_manager, wallet_0, uint64(201), backup_ids
        )

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, did_wallet_1.get_confirmed_balance, 201)
        await time_out_assert(15, did_wallet_1.get_unconfirmed_balance, 201)
        await time_out_assert(15, did_wallet_1.get_pending_change_balance, 0)

        filename = "test.backup"
        did_wallet_1.create_backup(filename)

        # Wallet2 recovers DIDWallet2 to a new set of keys
        did_wallet_2 = await DIDWallet.create_new_did_wallet_from_recovery(
            wallet_node_1.wallet_state_manager, wallet_1, filename
        )
        coins = await did_wallet_1.select_coins(1)
        coin = coins.copy().pop()
        assert did_wallet_2.did_info.temp_coin == coin
        newpuz = await did_wallet_2.get_new_puzzle()
        newpuzhash = newpuz.get_tree_hash()
        pubkey = bytes(
            (await did_wallet_2.wallet_state_manager.get_unused_derivation_record(did_wallet_2.wallet_info.id)).pubkey
        )
        message_spend_bundle = await did_wallet_0.create_attestment(
            did_wallet_2.did_info.temp_coin.name(), newpuzhash, pubkey, "test.attest"
        )
        print(f"pubkey: {pubkey}")

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        (
            test_info_list,
            test_message_spend_bundle,
        ) = await did_wallet_2.load_attest_files_for_recovery_spend(["test.attest"])
        assert message_spend_bundle == test_message_spend_bundle

        await did_wallet_2.recovery_spend(
            did_wallet_2.did_info.temp_coin,
            newpuzhash,
            test_info_list,
            pubkey,
            test_message_spend_bundle,
        )
        print(f"pubkey: {did_wallet_2}")

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(45, did_wallet_2.get_confirmed_balance, 201)
        await time_out_assert(45, did_wallet_2.get_unconfirmed_balance, 201)

        # DIDWallet3 spends the money back to itself
        ph2 = await wallet_1.get_new_puzzlehash()
        await did_wallet_2.create_spend(ph2)

        for i in range(1, num_blocks):
            await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, wallet_1.get_confirmed_balance, 201)
        await time_out_assert(15, wallet_1.get_unconfirmed_balance, 201)

    @pytest.mark.asyncio
    async def test_did_recovery_with_multiple_backup_dids(self, two_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1 = full_nodes[0]
        server_1 = full_node_1.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(101)
        )

        ph = await wallet2.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)

        recovery_list = [bytes.fromhex(did_wallet.get_my_DID())]

        did_wallet_2: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_2.wallet_state_manager, wallet2, uint64(101), recovery_list
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, did_wallet_2.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_2.get_unconfirmed_balance, 101)

        assert did_wallet_2.did_info.backup_ids == recovery_list

        recovery_list.append(bytes.fromhex(did_wallet_2.get_my_DID()))

        did_wallet_3: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_2.wallet_state_manager, wallet2, uint64(201), recovery_list
        )

        ph2 = await wallet.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        assert did_wallet_3.did_info.backup_ids == recovery_list
        await time_out_assert(15, did_wallet_3.get_confirmed_balance, 201)
        await time_out_assert(15, did_wallet_3.get_unconfirmed_balance, 201)
        coins = await did_wallet_3.select_coins(1)
        coin = coins.pop()
        pubkey = (
            await did_wallet_2.wallet_state_manager.get_unused_derivation_record(did_wallet_2.wallet_info.id)
        ).pubkey
        message_spend_bundle = await did_wallet.create_attestment(coin.name(), ph, pubkey, "test1.attest")
        message_spend_bundle2 = await did_wallet_2.create_attestment(coin.name(), ph, pubkey, "test2.attest")
        message_spend_bundle = message_spend_bundle.aggregate([message_spend_bundle, message_spend_bundle2])

        (
            test_info_list,
            test_message_spend_bundle,
        ) = await did_wallet_3.load_attest_files_for_recovery_spend(["test1.attest", "test2.attest"])
        assert message_spend_bundle == test_message_spend_bundle

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        await did_wallet_3.recovery_spend(coin, ph, test_info_list, pubkey, message_spend_bundle)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph2))
        # ends in 899 so it got the 201 back
        await time_out_assert(15, wallet2.get_confirmed_balance, 15999999999899)
        await time_out_assert(15, wallet2.get_unconfirmed_balance, 15999999999899)
        await time_out_assert(15, did_wallet_3.get_confirmed_balance, 0)
        await time_out_assert(15, did_wallet_3.get_unconfirmed_balance, 0)

    @pytest.mark.asyncio
    async def test_did_recovery_with_empty_set(self, two_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1 = full_nodes[0]
        server_1 = full_node_1.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet

        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(101)
        )

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)
        coins = await did_wallet.select_coins(1)
        coin = coins.pop()
        info = Program.to([])
        pubkey = (await did_wallet.wallet_state_manager.get_unused_derivation_record(did_wallet.wallet_info.id)).pubkey
        spend_bundle = await did_wallet.recovery_spend(
            coin, ph, info, pubkey, SpendBundle([], AugSchemeMPL.aggregate([]))
        )
        additions = spend_bundle.additions()
        assert additions == []

    @pytest.mark.asyncio
    async def test_did_attest_after_recovery(self, two_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1 = full_nodes[0]
        server_1 = full_node_1.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(101)
        )

        ph2 = await wallet2.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)
        recovery_list = [bytes.fromhex(did_wallet.get_my_DID())]

        did_wallet_2: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node_2.wallet_state_manager, wallet2, uint64(101), recovery_list
        )
        ph = await wallet.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(15, did_wallet_2.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_2.get_unconfirmed_balance, 101)
        assert did_wallet_2.did_info.backup_ids == recovery_list

        # Update coin with new ID info
        recovery_list = [bytes.fromhex(did_wallet_2.get_my_DID())]
        await did_wallet.update_recovery_list(recovery_list, uint64(1))
        assert did_wallet.did_info.backup_ids == recovery_list
        updated_puz = await did_wallet.get_new_puzzle()
        await did_wallet.create_spend(updated_puz.get_tree_hash())

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)

        # DID Wallet 2 recovers into itself with new innerpuz
        new_puz = await did_wallet_2.get_new_puzzle()
        new_ph = new_puz.get_tree_hash()
        coins = await did_wallet_2.select_coins(1)
        coin = coins.pop()
        pubkey = (
            await did_wallet_2.wallet_state_manager.get_unused_derivation_record(did_wallet_2.wallet_info.id)
        ).pubkey
        message_spend_bundle = await did_wallet.create_attestment(coin.name(), new_ph, pubkey, "test.attest")
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        (
            info,
            message_spend_bundle,
        ) = await did_wallet_2.load_attest_files_for_recovery_spend(["test.attest"])
        await did_wallet_2.recovery_spend(coin, new_ph, info, pubkey, message_spend_bundle)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, did_wallet_2.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet_2.get_unconfirmed_balance, 101)

        # Recovery spend
        coins = await did_wallet.select_coins(1)
        coin = coins.pop()

        pubkey = (await did_wallet.wallet_state_manager.get_unused_derivation_record(did_wallet.wallet_info.id)).pubkey
        await did_wallet_2.create_attestment(coin.name(), ph, pubkey, "test.attest")
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph2))
        (
            test_info_list,
            test_message_spend_bundle,
        ) = await did_wallet.load_attest_files_for_recovery_spend(["test.attest"])
        await did_wallet.recovery_spend(coin, ph, test_info_list, pubkey, test_message_spend_bundle)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, wallet.get_confirmed_balance, 30000000000000)
        await time_out_assert(15, wallet.get_unconfirmed_balance, 30000000000000)
        await time_out_assert(15, did_wallet.get_confirmed_balance, 0)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 0)

    @pytest.mark.asyncio
    async def test_make_double_output(self, two_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1 = full_nodes[0]
        server_1 = full_node_1.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(101)
        )
        ph2 = await wallet2.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_spendable_balance, 101)

        # Lock up with non DID innerpuz so that we can create two outputs
        # Innerpuz will output the innersol, so we just pass in ((51 0xMyPuz 49) (51 0xMyPuz 51))
        innerpuz = Program.to(binutils.assemble("1"))
        innerpuzhash = innerpuz.get_tree_hash()

        puz = did_wallet_puzzles.create_fullpuz(
            innerpuzhash,
            did_wallet.did_info.origin_coin.puzzle_hash,
        )

        # Add the hacked puzzle to the puzzle store so that it is recognised as "our" puzzle
        old_devrec = await did_wallet.wallet_state_manager.get_unused_derivation_record(did_wallet.wallet_info.id)
        devrec = DerivationRecord(
            old_devrec.index,
            puz.get_tree_hash(),
            old_devrec.pubkey,
            old_devrec.wallet_type,
            old_devrec.wallet_id,
        )
        await did_wallet.wallet_state_manager.puzzle_store.add_derivation_paths([devrec])
        await did_wallet.create_spend(puz.get_tree_hash())

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph2))

        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_spendable_balance, 101)

        # Create spend by hand so that we can use the weird innersol
        coins = await did_wallet.select_coins(1)
        coin = coins.pop()
        # innerpuz is our desired output
        innersol = Program.to([[51, coin.puzzle_hash, 45], [51, coin.puzzle_hash, 56]])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        parent_info = await did_wallet.get_parent_for_coin(coin)
        fullsol = Program.to(
            [
                [did_wallet.did_info.origin_coin.parent_coin_info, did_wallet.did_info.origin_coin.amount],
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        try:
            cost, result = puz.run_with_cost(DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM, fullsol)
        except Exception as e:
            assert e.args == ("path into atom",)
        else:
            assert False

    @pytest.mark.asyncio
    async def test_make_fake_coin(self, two_wallet_nodes):
        num_blocks = 5
        full_nodes, wallets = two_wallet_nodes
        full_node_1 = full_nodes[0]
        server_1 = full_node_1.server
        wallet_node, server_2 = wallets[0]
        wallet_node_2, server_3 = wallets[1]
        await server_2.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        wallet = wallet_node.wallet_state_manager.main_wallet
        wallet2 = wallet_node_2.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()

        await server_3.start_client(PeerInfo("localhost", uint16(server_1._port)), None)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        funds = sum(
            [
                calculate_pool_reward(uint32(i)) + calculate_base_farmer_reward(uint32(i))
                for i in range(1, num_blocks - 1)
            ]
        )

        await time_out_assert(15, wallet.get_confirmed_balance, funds)

        did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
            wallet_node.wallet_state_manager, wallet, uint64(101)
        )
        ph2 = await wallet2.get_new_puzzlehash()
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph2))
        await time_out_assert(15, did_wallet.get_confirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 101)
        await time_out_assert(15, did_wallet.get_spendable_balance, 101)

        coins = await did_wallet.select_coins(1)
        coin = coins.pop()

        # copy info for later
        parent_info = await did_wallet.get_parent_for_coin(coin)
        id_puzhash = coin.puzzle_hash

        await did_wallet.create_spend(ph)
        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await time_out_assert(15, did_wallet.get_confirmed_balance, 0)
        await time_out_assert(15, did_wallet.get_unconfirmed_balance, 0)

        tx_record = await wallet.generate_signed_transaction(101, id_puzhash)
        await wallet.push_transaction(tx_record)

        for i in range(1, num_blocks):
            await full_node_1.farm_new_transaction_block(FarmNewBlockProtocol(ph))

        await time_out_assert(15, wallet.get_confirmed_balance, 21999999999899)
        await time_out_assert(15, wallet.get_unconfirmed_balance, 21999999999899)

        coins = await did_wallet.select_coins(1)
        assert len(coins) >= 1

        coin = coins.pop()

        # Write spend by hand
        # innerpuz solution is (mode amount new_puz identity my_puz)
        innersol = Program.to([0, coin.amount, ph, coin.name(), coin.puzzle_hash])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz = did_wallet.did_info.current_inner
        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
            innerpuz,
            did_wallet.did_info.origin_coin.puzzle_hash,
        )
        fullsol = Program.to(
            [
                [did_wallet.did_info.origin_coin.parent_coin_info, did_wallet.did_info.origin_coin.amount],
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )

        list_of_solutions = [CoinSolution(coin, full_puzzle, fullsol)]
        # sign for AGG_SIG_ME
        message = coin.puzzle_hash + coin.name() + did_wallet.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
        pubkey = did_wallet_puzzles.get_pubkey_from_innerpuz(innerpuz)
        index = await did_wallet.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        private = master_sk_to_wallet_sk(did_wallet.wallet_state_manager.private_key, index)
        signature = AugSchemeMPL.sign(private, message)
        sigs = [signature]
        aggsig = AugSchemeMPL.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)

        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=ph,
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=did_wallet.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=token_bytes(),
        )

        await did_wallet.standard_wallet.push_transaction(did_record)

        await time_out_assert(15, wallet.get_confirmed_balance, 21999999999899)
        await time_out_assert(15, wallet.get_unconfirmed_balance, 21999999999899)
        ph2 = Program.to(binutils.assemble("()")).get_tree_hash()
        for i in range(1, num_blocks + 3):
            await full_node_1.farm_new_block(FarmNewBlockProtocol(ph2))
        # It ends in 900 so it's not gone through
        # Assert coin ID is failing
        await time_out_assert(15, wallet.get_confirmed_balance, 23999999999899)
        await time_out_assert(15, wallet.get_unconfirmed_balance, 23999999999899)
"""
