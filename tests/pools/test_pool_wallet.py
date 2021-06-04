import asyncio
import logging
import pytest

from secrets import token_bytes
from typing import Any, Callable, Dict, List, Optional, Set
from collections import defaultdict
from blspy import G1Element

from chia.pools.pool_wallet import PoolWallet
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

# from chia.wallet.transaction_record import TransactionRecord
# from chia.wallet.util.transaction_type import TransactionType
# from chia.wallet.wallet_state_manager import WalletStateManager
# from clvm_tools import binutils

# from tests.setup_nodes import self_hostname, setup_simulators_and_wallets
# from tests.time_out_assert import time_out_assert, time_out_assert_not_none
# from tests.wallet.cc_wallet.test_cc_wallet import tx_in_pool
from chia.pools.pool_puzzles import POOL_MEMBER_HASH, P2_SINGLETON_HASH, POOL_WAITINGROOM_INNER_HASH
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
            POOL_WAITINGROOM_INNER_HASH: Coin(escaping_parent, POOL_WAITINGROOM_INNER_HASH, 1),
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
