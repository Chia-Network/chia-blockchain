import json
import logging
import time

from dataclasses import dataclass
from secrets import token_bytes
from typing import Any, Optional, Set, Dict, Tuple, List

from blspy import AugSchemeMPL, G1Element, PrivateKey
from chia.pools.pool_wallet_info import (
    PoolWalletInfo,
    PoolSingletonState,
    PoolState,
    POOL_PROTOCOL_VERSION,
    create_pool_state,
    PENDING_CREATION,
    SELF_POOLING,
    LEAVING_POOL,
    FARMING_TO_POOL,
)

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.coin_solution import CoinSolution
from chia.types.spend_bundle import SpendBundle

from chia.pools.pool_puzzles import (
    create_escaping_inner_puzzle,
    create_full_puzzle,
    SINGLETON_LAUNCHER,
    P2_SINGLETON_MOD,
    SINGLETON_MOD,
    create_pooling_inner_puzzle,
)

from chia.util.ints import uint8, uint32, uint64
from chia.wallet.cc_wallet.ccparent import CCParent
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet

from chia.wallet.wallet_info import WalletInfo
from chia.wallet.util.transaction_type import TransactionType

# TODO Refactor Singleton Wallet Python code


"""
Messages in and out of this wallet

-> farmer
<- farmer

-> blockchain (via wallet): create singleton
<- blockchain (via wallet): 

TODO:
RPC Test: Why is main_wallet balance zero?
Notify GUI or RPC when state changes via WalletStateManager: state_changed
WalletStateManager.pending

"""

# TODO:
# * Check to see if we have any outstanding money to collect before leaving Self-pooling state
# * Ask Matt to switch to puzzlehash for self-pooling as well, or
#   use a pubkey address in the self-pooling case


@dataclass(frozen=True)
class JoinPoolResult:
    ok: bool
    key_fingerprint: int
    key_derivation_path: DerivationRecord


# Note: all puzzles in this wallet are parameterized to:
# * The genesis ID (permanently)
# * The current public key for the target payment address
# There are 3 on-chain inner puzzle states:
# * self-pooling (farming to our own wallet)
# * pool member (farming to a pool address)
# * leaving a pool
# (There is no "waiting to enter a pool" on-chain state, because the wait
# period to leave self-pooling is always zero when)
class PoolWallet:
    MINIMUM_INITIAL_BALANCE = 1
    MINIMUM_RELATIVE_LOCK_HEIGHT = 10

    wallet_state_manager: Any
    log: logging.Logger
    db_wallet_info: WalletInfo
    pool_info: PoolWalletInfo
    standard_wallet: Wallet
    # base_puzzle_program: Optional[bytes]
    # base_inner_puzzle_hash: Optional[bytes32]
    wallet_id: int
    # current_derivation_record: DerivationRecord  # Tracks singleton
    block_height_created: Optional[uint32]
    puzzle_hash_to_state: Dict[bytes32, PoolState]

    """
    From the user's perspective, this is not a wallet at all, but a way to control
    whether their pooling-enabled plots are being self-farmed, or farmed by a pool,
    and by which pool. Self-pooling and joint pooling rewards are swept into the
    users' regular wallet.

    If this wallet is in SELF_POOLING state, the coin ID associated with the current
    pool wallet contains the rewards gained while self-farming, so care must be taken
    to disallow joining a new pool while we still have money on the pooling singleton UTXO.

    Pools can be joined anonymously, without an account or prior signup.

    The ability to change the farm-to target prevents abuse from pools
    by giving the user the ability to quickly change pools, or self-farm.

    The pool is also protected, by not allowing members to cheat by quickly leaving a pool,
    and claiming a block that was pledged to the pool.

    The pooling protocol and smart coin prevents a user from quickly leaving a pool
    by enforcing a wait time when leaving the pool. A minimum number of blocks must pass
    after the user declares that they are leaving the pool, and before they can start to
    self-claim rewards again.

    Control of switching states is granted to the controller of the private key that
    corresponds to `self.pool_info.singleton_pubkey`, the user, in this case.

    We reveal the inner_puzzle to the pool during setup of the pooling protocol.
    The pool can prove to itself that the inner puzzle pays to the pooling address,
    and it can follow state changes in the pooling puzzle by tracing destruction and
    creation of coins associate with this pooling singleton (the singleton controlling
    this pool group).

    The user trusts the pool to send mining rewards to the <XXX address XXX>
    TODO: We should mark which address is receiving funds for our current state.

    If the pool misbehaves, it is the user's responsibility to leave the pool

    It is the Pool's responsibility to claim the rewards sent to the pool_puzzlehash.

    The timeout for leaving the pool is expressed in number of blocks from the time
    the user expresses their intent to leave.



    """

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.POOLING_WALLET)

    def id(self):
        return self.db_wallet_info.id

    def _verify_self_pooled(self, state) -> Optional[str]:
        err = ""
        if state.pool_url is not None:
            err += " Unneeded pool_url for self-pooling"

        if state.relative_lock_height != 0:
            err += " Incorrect relative_lock_height for self-pooling"

        return None if err == "" else err

    def _verify_pooling_state(self, state) -> Optional[str]:
        err = ""
        if state.relative_lock_height < self.MINIMUM_RELATIVE_LOCK_HEIGHT:
            err += (
                f" Pool relative_lock_height ({state.relative_lock_height})"
                f"is less than recommended minimum ({self.MINIMUM_RELATIVE_LOCK_HEIGHT})"
            )

        if state.pool_url in [None, ""]:
            err += " Empty pool url in pooling state"

        return None if err == "" else err

    def _verify_pool_state(self, state) -> Optional[str]:
        # PENDING_CREATION = 1
        # SELF_POOLING = 2
        # LEAVING_POOL = 3
        # FARMING_TO_POOL = 4
        if state.target_puzzle_hash is None:
            return "Invalid puzzle_hash"

        if state.version > POOL_PROTOCOL_VERSION:
            return (
                f"Detected pool protocol version {state.version}, which is "
                f"newer than this wallet's version ({POOL_PROTOCOL_VERSION}). Please upgrade "
                f"to use this pooling wallet"
            )

        if state.state == PoolSingletonState.PENDING_CREATION or state.state == PoolSingletonState.SELF_POOLING:
            return self._verify_self_pooled(state)
        elif state.state == PoolSingletonState.FARMING_TO_POOL or state.state == PoolSingletonState.LEAVING_POOL:
            return self._verify_pooling_state(state)
        else:
            return "Internal Error"

    def is_valid_pool_state(self, state: PoolState) -> bool:
        return self._verify_pool_state(state) is None

    # def _verify_initial_state(self, initial_state):
    #    assert self._verify_pool_state(initial_state)
    #    PoolSingletonState.PENDING_CREATION
    #    return True

    def _verify_initial_target_state(self, initial_target_state):
        err = self._verify_pool_state(initial_target_state)
        if err:
            raise ValueError(f"Invalid internal Pool State: {err}: {initial_target_state}")

    def _init_log(self, name):
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

    async def _get_new_standard_derivation_record(self) -> DerivationRecord:
        return await self.wallet_state_manager.get_unused_derivation_record(self.standard_wallet.id())

    async def _get_new_pool_derivation_record(self) -> DerivationRecord:
        return await self.wallet_state_manager.get_unused_derivation_record(self.db_wallet_info.id)

    async def _get_launcher_coin(self, amount):
        coins = await self.wallet_state_manager.main_wallet.select_coins(amount)
        if coins is None:
            return False

        launcher = coins.copy().pop()
        return launcher

    def _verify_transition(self, target_state):
        pass

    def transition(self, target_state):
        """Attempt to enter a new state"""
        pass

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = None,
    ):
        self = PoolWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.wallet_state_manager = wallet_state_manager
        self.puzzle_hash_to_state = {}
        self.wallet_state_manager = wallet_state_manager
        self.wallet_id = wallet_info.id
        self.standard_wallet = wallet
        self.db_wallet_info = wallet_info
        self._init_log(name)
        self.load_info(wallet_info)

        if self.pool_info.current.state == PENDING_CREATION.value:
            assert self.pool_info.target != PENDING_CREATION.value
            # TODO: use real genesis
            genesis_puzzle_hash = token_bytes(32)
            self.wallet_state_manager.set_coin_with_puzzlehash_created_callback(
                genesis_puzzle_hash, self.genesis_callback
            )

        # Always watch for self-pooling
        await self.watch_for_self_pooling_puz()
        await self.watch_p2_singleton_rewards()

        # Watch for new pool states as we acquire the needed parameters
        if self.pool_info.current.state == FARMING_TO_POOL.value:
            pool_puzzle_hash = self.pool_info.current.target_puzzle_hash
            relative_lock_height = self.pool_info.current.relative_lock_height
            pool_url = self.pool_info.current.pool_url
            await self.watch_for_pooling_puz(pool_puzzle_hash, relative_lock_height, pool_url)
            await self.watch_for_escaping_puz(pool_puzzle_hash, relative_lock_height, pool_url)
        elif self.pool_info.target.state == FARMING_TO_POOL.value:
            pool_puzzle_hash = self.pool_info.target.target_puzzle_hash
            relative_lock_height = self.pool_info.target.relative_lock_height
            pool_url = self.pool_info.target.pool_url
            await self.watch_for_pooling_puz(pool_puzzle_hash, relative_lock_height, pool_url)
            await self.watch_for_escaping_puz(pool_puzzle_hash, relative_lock_height, pool_url)
        return self

    @staticmethod
    # note: we can be created by a user action, or by recovering state
    # from the blockchain
    async def create_new_pool_wallet(
        wallet_state_manager: Any,
        main_wallet: Wallet,
        initial_target_state: PoolState,
        owner_pubkey: G1Element,
        owner_puzzle_hash: bytes32,
        fee: uint64 = uint64(0),
        name: str = None,
    ):
        """
        A "plot group" represents the idea of a set of plots that all pay to
        the same pooling puzzle. This puzzle is a `chia singleton` that is
        parameterized with a public key controlled by the user's wallet
        (a `smart coin`). It contains an inner puzzle that can switch between
        paying block rewards to a pool, or to a user's own wallet.

        Call under the wallet state manger lock
        `fee` is the mempool fee
        `amount` is the initial value of the singleton
        """
        amount = 1
        self = PoolWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = main_wallet
        self.wallet_state_manager = wallet_state_manager
        self.puzzle_hash_to_state = {}

        unspent_records = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(
            self.standard_wallet.wallet_id
        )
        balance = await self.standard_wallet.get_confirmed_balance(unspent_records)
        if balance < self.MINIMUM_INITIAL_BALANCE:
            raise ValueError("Not enough balance in main wallet to create a managed plotting pool.")
        if balance < fee:
            raise ValueError("Not enough balance in main wallet to create a managed plotting pool with fee {fee}.")

        self._init_log(name)

        # Verify Parameters - raise if invalid
        self._verify_initial_target_state(initial_target_state)

        current_state = create_pool_state(PENDING_CREATION, owner_puzzle_hash, owner_pubkey, None, uint32(0))
        self._verify_pool_state(current_state)

        # TODO: Check genesis_puzzle_hash is correct, check if launcher_coin is launcher, or eve
        target_puzzle_hash = initial_target_state.target_puzzle_hash
        relative_lock_height = initial_target_state.relative_lock_height
        spend_bundle, parents, singleton_puzzle_hash, launcher_coin = await self.generate_new_pool_wallet_id(
            uint64(1), owner_pubkey, owner_puzzle_hash, target_puzzle_hash, relative_lock_height
        )

        if spend_bundle is None:
            raise ValueError("failed to generate ID for wallet")

        assert launcher_coin is not None

        # TODO choose initial puzzle state

        # Bit of order-of operation issue: we need the new wallet ID to send
        # the transaction, but we only want to save this information if the transaction is valid
        self.pool_info = PoolWalletInfo(
            current_state,
            initial_target_state,
            pending_transaction=None,
            launcher_coin=launcher_coin,
            launcher_id=launcher_coin.name(),
            parent_list=parents,
            current_inner=None,
            self_pooled_reward_list=[],
            owner_pubkey=owner_pubkey,
            owner_target_puzzle_hash=owner_puzzle_hash,
        )
        info_as_string = json.dumps(self.pool_info.to_json_dict())

        self.db_wallet_info = await wallet_state_manager.user_store.create_wallet(
            "Pooling Wallet", WalletType.POOLING_WALLET.value, info_as_string
        )
        if self.db_wallet_info is None:
            raise ValueError("Internal Wallet Error")

        self.wallet_id = self.db_wallet_info.id

        # self.wallet_state_manager.add_new_wallet() calls back into us via
        # puzzle_for_pk. Because puzzle_for_pk is currently a mandatory part of
        # the external wallet API, we must inspect all external calls to puzzle_for_pk,
        # and determine if they mean to create the puzzle for the current state, or
        # the target state.
        await self.wallet_state_manager.add_new_wallet(self, self.db_wallet_info.id)
        # END Create Wallet

        self.wallet_state_manager.set_coin_with_puzzlehash_created_callback(
            singleton_puzzle_hash, self.genesis_callback
        )

        # Create TransactionRecord
        pool_wallet_incoming_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=singleton_puzzle_hash,
            amount=uint64(amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(10),  # xxx what is "sent = 10" ?
            spend_bundle=None,
            additions=spend_bundle.additions(),  # spend_bundle.additions() is calling run_with_cost
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=spend_bundle.name(),
        )
        standard_wallet_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=singleton_puzzle_hash,
            amount=uint64(amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_state_manager.main_wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
        )

        await self.standard_wallet.push_transaction(pool_wallet_incoming_record)
        await self.standard_wallet.push_transaction(standard_wallet_record)

        await self.set_pending_transaction(standard_wallet_record, False)

        # Always watch for self-pooling
        await self.watch_for_self_pooling_puz()
        await self.watch_p2_singleton_rewards()

        # Watch for new pool states as we acquire the needed parameters
        if initial_target_state.state == FARMING_TO_POOL:
            pool_puzzle_hash = initial_target_state.target_puzzle_hash
            relative_lock_height = initial_target_state.relative_lock_height
            pool_url = initial_target_state.pool_url
            await self.watch_for_pooling_puz(pool_puzzle_hash, relative_lock_height, pool_url)
            await self.watch_for_escaping_puz(pool_puzzle_hash, relative_lock_height, pool_url)

        return self

    async def watch_p2_singleton_rewards(self):
        singleton_mod_hash = SINGLETON_MOD.get_tree_hash()
        launcher_id = self.pool_info.launcher_coin.name()
        p2_singleton_full = P2_SINGLETON_MOD.curry(
            singleton_mod_hash, Program.to(singleton_mod_hash).get_tree_hash(), launcher_id
        )
        p2_singleton_puzzle_hash = p2_singleton_full.get_tree_hash()
        self.wallet_state_manager.set_coin_with_puzzlehash_created_callback(
            p2_singleton_puzzle_hash, self.p2_singleton_callback
        )

    async def watch_for_pooling_puz(self, pool_puzzle_hash: bytes32, relative_lock_height: uint32, pool_url: str):
        launcher_id: bytes32 = self.pool_info.launcher_coin.name()
        assert self.pool_info.owner_pubkey is not None
        owner_pubkey: G1Element = self.pool_info.owner_pubkey

        escaping_inner_puzzle_hash: bytes32 = create_escaping_inner_puzzle(
            pool_puzzle_hash, relative_lock_height, owner_pubkey
        ).get_tree_hash()
        pooling_inner: Program = create_pooling_inner_puzzle(pool_puzzle_hash, escaping_inner_puzzle_hash, owner_pubkey)
        pooling_full: Program = create_full_puzzle(pooling_inner, launcher_id)
        pooling_puzzle_hash: bytes32 = pooling_full.get_tree_hash()
        self.wallet_state_manager.set_coin_with_puzzlehash_created_callback(
            pooling_puzzle_hash, self.pooling_state_callback
        )
        self.puzzle_hash_to_state[pooling_puzzle_hash] = create_pool_state(
            FARMING_TO_POOL, pool_puzzle_hash, owner_pubkey, pool_url, relative_lock_height
        )

    async def watch_for_self_pooling_puz(self):
        launcher_id: bytes32 = self.pool_info.launcher_coin.name()
        assert self.pool_info.owner_pubkey is not None
        owner_pubkey: G1Element = self.pool_info.owner_pubkey
        target_puzzle_hash: bytes32 = self.pool_info.owner_target_puzzle_hash
        escaping_inner_puzzle_hash: bytes32 = create_escaping_inner_puzzle(
            target_puzzle_hash, uint32(0), owner_pubkey
        ).get_tree_hash()
        pooling_inner: Program = create_pooling_inner_puzzle(
            target_puzzle_hash, escaping_inner_puzzle_hash, owner_pubkey
        )
        pooling_full: Program = create_full_puzzle(pooling_inner, launcher_id)
        pooling_puzzle_hash: bytes32 = pooling_full.get_tree_hash()
        self.wallet_state_manager.set_coin_with_puzzlehash_created_callback(
            pooling_puzzle_hash, self.pooling_state_callback
        )
        self.puzzle_hash_to_state[pooling_puzzle_hash] = create_pool_state(
            SELF_POOLING, target_puzzle_hash, owner_pubkey, None, uint32(0)
        )

    async def watch_for_escaping_puz(self, pool_puzzle_hash: bytes32, relative_lock_height: uint32, pool_url: str):
        launcher_id: bytes32 = self.pool_info.launcher_coin.name()
        assert self.pool_info.owner_pubkey is not None
        owner_pubkey: G1Element = self.pool_info.owner_pubkey
        pooling_inner: Program = create_escaping_inner_puzzle(pool_puzzle_hash, relative_lock_height, owner_pubkey)
        pooling_full: Program = create_full_puzzle(pooling_inner, launcher_id)
        pooling_puzzle_hash: bytes32 = pooling_full.get_tree_hash()
        self.wallet_state_manager.set_coin_with_puzzlehash_created_callback(
            pooling_puzzle_hash, self.pooling_state_callback
        )
        self.puzzle_hash_to_state[pooling_puzzle_hash] = create_pool_state(
            LEAVING_POOL, pool_puzzle_hash, owner_pubkey, pool_url, relative_lock_height
        )

    async def pooling_state_callback(self, coin: Coin):
        new_pool_state = self.puzzle_hash_to_state[coin.puzzle_hash]
        await self.set_current_state(new_pool_state)

    async def p2_singleton_callback(self, coin: Coin):
        # @mariano @yostra is in_transaction True for every callback from wallet_state_manager?
        await self.add_self_pooled_reward(coin, True)

    """
    async def update_current_state(self, inner_puzzle: Program):
        # Note: We can update our state from extended data in the blockchain, once the feature is added to Singletons
        # Currently, we infer our state from the inner_puzzle, and our current & target states
        c = self.pool_info.current
        t = self.pool_info.target
        if inner_puzzle.get_tree_hash() == esca
        current = create_pool_state(c.state, c.target_puzzle_hash, c.pool_url, c.relative_lock_height)
        return current
    """

    async def genesis_callback(self, coin: Coin):
        self.log.info(f"Singleton created for Pool Wallet {self.wallet_id} {self.pool_info.launcher_coin}")

        # Update our state to reflect the blockchain
        inner = self.puzzle_for_puzzlehash(coin.puzzle_hash)
        current = await self.update_current_state(inner)
        self.log.info(f"Adding parent {coin.name()}: {coin.parent_coin_info}")
        new_parent_list = self.pool_info.parent_list.copy()
        new_parent_list.append((coin.name(), coin.parent_coin_info))
        in_transaction = False

        new_pool_info = PoolWalletInfo(
            current,
            self.pool_info.target,
            None,  # clear self.pool_info.pending_transaction
            self.pool_info.launcher_coin,
            new_parent_list,
            inner,
            self.pool_info.self_pooled_reward_list,
            self.pool_info.owner_pubkey,
            self.pool_info.owner_target_puzzle_hash,
        )
        await self.save_info(new_pool_info, in_transaction)

        # Set the puzzle_hash watch callback for our next anticipated transition
        # self.wallet_state_manager.set_coin_with_puzzle_hash_created_callback(
        #    next_puzzle_hash, self.singleton_callback
        # )

    async def singleton_callback(self, coin: Coin):
        pass

    '''
    async def _attempt_transition(self):
        spend_bundle =
        pool_tx_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=xxx,
            amount=uint64(amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(10),  # xxx
            spend_bundle=None,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=token_bytes(),
        )

        self.pool_info.current_pending_tx = pool_tx_record
        await self.standard_wallet.push_transaction(pool_tx_record)

    async def _create_pooling_singleton(
        self,
        initial_target_state,
    ):
        """
        Pool Group creation involves the user, so we need clear error messages.
        """

        coins = await self.wallet_state_manager.main_wallet.select_coins(amount)
        if coins is None:
            raise ValueError("No coins found in main wallet")

        launcher = coins.copy().pop()
        launcher_id = launcher.name()

        user_pubkey_bytes = hexstr_to_bytes(user_pubkey)

        if self.pool_info.singleton_pubkey is None:
            raise ValueError("could not get pubkey or pubkey conversion failed")

        spend_bundle = await self.generate_new_decentralised_id(uint64(amount))
        if spend_bundle is None:
            raise ValueError("failed to generate create pool group genesis transaction")
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
        assert self.pool_info.launcher_coin is not None
        pool_puzzle_hash = pool_puzzles.create_full_puzzle(
            self.pool_info.current_inner, self.pool_info.launcher_coin.puzzle_hash
        ).get_tree_hash()

        """
        pool_group_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=did_puzzle_hash,
            amount=uint64(amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(10),
            spend_bundle=None,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=token_bytes(),
        )
        regular_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=did_puzzle_hash,
            amount=uint64(amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_state_manager.main_wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=token_bytes(),
        )
        """
        await self.standard_wallet.push_transaction(regular_record)
        await self.standard_wallet.push_transaction(did_record)
        return self
    '''

    # Note about using different pubkeys on each singleton iteration:
    # owner_pubkey needn't be from the same wallet that generated the genesis coin,
    # but it is, in this implementation.
    # target_puzzle_hash and owner_target_puzzle_hash
    async def _get_pubkey_and_puzzle_hash(self) -> Tuple[G1Element, bytes32]:
        """This puzzle / pubkey pair is for paying into the user's main wallet"""
        dr = await self._get_new_standard_derivation_record()
        return dr.pubkey, dr.puzzle_hash

    async def generate_new_pool_wallet_id(
        self,
        amount: uint64,
        owner_pubkey: G1Element,
        our_puzzle_hash: bytes32,
        target_puzzle_hash: bytes32,
        relative_lock_height: uint32,
    ) -> Tuple[SpendBundle, List, bytes32, Coin]:
        """
        Creates the initial singleton, which includes spending an origin coin, the launcher, and creating a singleton
        with the "pooling" inner state, which can be either self pooling or using a pool
        """

        coins: Set[Coin] = await self.standard_wallet.select_coins(amount)
        if coins is None:
            raise ValueError("Not enough coins to create pool wallet")

        assert len(coins) == 1

        launcher_parent: Coin = coins.copy().pop()
        genesis_launcher_puz: Program = SINGLETON_LAUNCHER
        launcher_coin: Coin = Coin(launcher_parent.name(), genesis_launcher_puz.get_tree_hash(), amount)

        # inner always starts in "member" state; either self or pooled
        escaping_inner_puzzle_hash: bytes32 = create_escaping_inner_puzzle(
            target_puzzle_hash, relative_lock_height, owner_pubkey
        )

        self_pooling_inner_puzzle: Program = create_pooling_inner_puzzle(
            our_puzzle_hash, escaping_inner_puzzle_hash, owner_pubkey
        )
        full_self_pooling_puzzle: Program = create_full_puzzle(
            self_pooling_inner_puzzle, launcher_id=launcher_coin.name()
        )
        inner: Program = self_pooling_inner_puzzle

        puzzle_hash: bytes32 = full_self_pooling_puzzle.get_tree_hash()

        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([puzzle_hash, amount, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message).name())

        create_launcher_tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            amount,
            genesis_launcher_puz.get_tree_hash(),
            uint64(0),
            None,
            coins,
            None,
            False,
            announcement_set,
        )
        assert create_launcher_tx_record is not None and create_launcher_tx_record.spend_bundle is not None

        # TODO: add PoolState serialization in the solution here
        genesis_launcher_solution: Program = Program.to([puzzle_hash, amount, bytes(0x80)])

        launcher_cs: CoinSolution = CoinSolution(
            launcher_coin,
            SerializedProgram.from_program(genesis_launcher_puz),
            SerializedProgram.from_program(genesis_launcher_solution),
        )
        launcher_sb: SpendBundle = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))

        eve_coin: Coin = Coin(launcher_coin.name(), puzzle_hash, amount)
        eve_parent = CCParent(
            launcher_coin.parent_coin_info,
            launcher_coin.puzzle_hash,
            launcher_coin.amount,
        )

        parents = [(eve_coin.parent_coin_info, eve_parent)]

        # Current inner will be updated when state is verified on the blockchain
        full_spend: SpendBundle = SpendBundle.aggregate([create_launcher_tx_record.spend_bundle, launcher_sb])
        return full_spend, parents, puzzle_hash, launcher_coin

    '''
    async def generate_p2_singleton_spend(self, coin: Coin, full_puzzle: Program, inner_puzzle: Program):
        """ `coin` is the singleton coin """
        assert self.pool_info.launcher_coin is not None
        block_height = 101  # XXX
        # inner_puzzle solution is:
        # ((singleton_id is_eve)
        #   spend_type inner_puzzle_hash my_amount pool_reward_amount pool_reward_height)
        # singleton_inner_puzzle_hash my_id)
        innersol = Program.to(
            [0, full_puzzle.get_tree_hash(), singleton_amount, p2_singleton_coin_amount, block_height]
        )

        # full solution is (parent_info my_amount innersolution)
        fullsol = Program.to(
            [
                [self.pool_info.launcher_coin.parent_coin_info, self.pool_info.launcher_coin.amount],
                coin.amount,
                innersol,
            ]
        )
        list_of_solutions = [CoinSolution(coin, full_puzzle, fullsol)]
        # sign for AGG_SIG_ME
        message = (
            Program.to([coin.amount, coin.puzzle_hash]).get_tree_hash()
            + coin.name()
            + self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
        )
        pubkey = did_wallet_puzzles.get_pubkey_from_inner_puzzle(inner_puzzle)
        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        private = master_sk_to_wallet_sk(self.wallet_state_manager.private_key, index)
        signature = AugSchemeMPL.sign(private, message)
        sigs = [signature]
        aggsig = AugSchemeMPL.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)
        return spend_bundle
    '''

    """
        return Success if added to mempool
Pool info
Pay to singleton address
Singleton owner public key
Rewards target puzzle hash
Fingerprint + derivation path of owner
    """

    def get_all_state(self) -> PoolWalletInfo:
        return self.pool_info
        """
        Current State: not created, self pooling, pooling (to pool X), escaping
        Target State: self pooling, pooling (to pool X)
        Pay to singleton address
    Balance
    Confirmation since last State (or 0 if have target state)
    Pool xxx I trust we will add a good name here xxx address: wallet recv address
    Confirmed singleton coinids
        """

    def get_current_state(self) -> PoolState:
        return self.pool_info.current

    def get_target_state(self) -> PoolState:
        return self.pool_info.target

    async def set_target_state(self, new_target_state: PoolState):
        """
        If the new target state is identical, do nothing, and return True
        Return False if the new target state is invalid
        Return False if we are currently attempting a state transition
        (there is a transaction outstanding)
        """
        if not self.is_valid_pool_state(new_target_state):
            return False
        if new_target_state == self.pool_info.target:
            return True
        if self.pool_info.pending_transaction is not None:
            return False

        await self._set_target_state(new_target_state)
        await self.maybe_transition_state()
        return True

    # xxx
    async def set_current_state(self, new_current_state: PoolState):
        # should only be set by blockchain callbacks
        assert new_current_state.state in [SELF_POOLING, FARMING_TO_POOL, LEAVING_POOL]
        if not self.is_valid_pool_state(new_current_state):
            raise AssertionError("")
        if new_current_state == self.pool_info.current:
            return True
        if self.pool_info.pending_transaction is not None:
            return False

        await self._set_current_state(new_current_state)
        await self.maybe_transition_state()
        return True

    async def new_current_state(self, new_current_state: PoolState):
        # if self pooling, rel lock must be zero
        pass

    async def calculate_next_state_and_tx(self, new_target_state: PoolState):
        """
        pool_info.current is the state of an actual state machine.
        State updates to current may come in off the blockchain without us anticipating them.
        `target_state` does not follow the rules of an explicit state machine.
        `target_state` is the ultimate goal state, not necessarily the next state.
        e.g. we must pass through "escaping" to go from FARMING_TO_POOL to SELF_POOLING

        PENDING_CREATION,
        SELF_POOLING,
        LEAVING_POOL,
        FARMING_TO_POOL,

        """
        current = self.pool_info.current.state
        target = self.pool_info.target.state

        valid_target_states = [SELF_POOLING, FARMING_TO_POOL]
        if target not in valid_target_states:
            raise AssertionError(
                f"Target state must be one of {valid_target_states} Invalid target state: {self.pool_info.target}"
            )
        if new_target_state not in valid_target_states:
            raise AssertionError(
                f"Target state must be one of {valid_target_states} Invalid target state: {self.pool_info.target}"
            )
            # return None, None

        if self.pool_info.current == self.pool_info.target:
            return self.pool_info.target, None
        if current == PENDING_CREATION and target in [SELF_POOLING, FARMING_TO_POOL]:
            return  # wait vs. re-issue singleton genesis tx
        if current == SELF_POOLING and target == SELF_POOLING:
            assert self.pool_info.current.target_puzzle_hash != self.pool_info.target.target_puzzle_hash
        # if current == SELF_POOLING and target == SELF_POOLING:
        #    assert self.pool_info.current.target_puzzle_hash != self.pool_info.target.target_puzzle_hash
        # update our payment address
        # if self.pool_info.current.state == [] and self.pool_info.target == PoolSingletonState.FARMING_TO_POOL:
        #    pass no
        if current == FARMING_TO_POOL and self.pool_info.target in [SELF_POOLING, FARMING_TO_POOL]:
            # We must go to escaping state because we are coming from a state with a non-zero relative_lock_height
            escaping_full = self.create_escaping_inner_puzzle()

            # need to save pending puzzle
            amount = 1
            tx_record = TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=next_puzzle_hash,
                amount=uint64(amount),
                fee_amount=uint64(0),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=spend_bundle,
                additions=spend_bundle.additions(),
                removals=spend_bundle.removals(),
                wallet_id=self.wallet_state_manager.main_wallet.id(),
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=token_bytes(),
            )
            return escaping_state, escaping_tx
        if current in [LEAVING_POOL] and self.pool_info.target in [SELF_POOLING, FARMING_TO_POOL]:
            # We have succeeded in entering the escaping state. Now we need to wait until
            # We can issue the transition to our target state
            # either add a new api to deliver to mempool later, or trigger a callback after relative_lock_height
            # blocks have passed
            trigger_time_delayed_tx
        raise AssertionError("Invalid combination of current and target states: current={current} target={target}")

    async def maybe_transition_state(self, new_target_state: PoolState):
        next_state, tx = self.calculate_next_state_and_tx(new_target_state)
        if self.pool_info.pending_transaction:
            raise

        await self.standard_wallet.push_transaction(tx_record)

    # async def claim_rewards(self, fee: uint64):
    # TODO
    async def collect_self_pooling_rewards(self, fee: uint64):
        """
        Create a spend from all p2_singleton utxos targeting our current self-pooling address
        Returns success if tx was added to the mempool.
        """
        if self.pool_info.state != PoolSingletonState.SELF_POOLING:
            raise AssertionError("Attempting claim of self-pooling rewards, but we are in state {self.pool_info.state}")
        spend_bundle = SpendBundle()
        # wallet.push_transaction

    async def join_pool(
        self, pool_url: str, target_puzzle_hash: bytes, relative_lock_height: uint32, fee: uint64
    ) -> Optional[JoinPoolResult]:
        ok = True
        key_fingerprint = 1
        # key_derivation_path = DerivationRecord()
        key_derivation_path = await self._get_new_standard_derivation_record()
        return JoinPoolResult(ok, key_fingerprint, key_derivation_path)

    """
    name
Pool url
Rewards target puzzle hash
Name
Relative lock height
Pool puzzle hash
Fee rate
Return
Success if added to mempool
Fingerprint + derivation path of owner
    """

    async def leave_pool(self):
        pass

    # We create a new puzzle whenever we change state
    # Our key derivations are m/12381/8444/a/b
    async def get_new_puzzlehash(self) -> bytes32:
        return await self.standard_wallet.get_new_puzzlehash()

    # What is the purpose of puzzle_for_pk? Does this need to be the puzzle at
    # the time the pk was issued / used, or should this be from the current state?
    # i.e. the puzzle for our current state, but with this pk?
    '''
    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        """ """
        inner_puzzle = pool_puzzles.create_inner_puzzle(
            pubkey, self.did_info.backup_ids, self.did_info.num_of_backup_ids_needed
        )
        #
        if self.did_info.launcher_coin is not None:
            return did_wallet_puzzles.create_full_puzzle(inner_puzzle, self.did_info.launcher_coin.puzzle_hash)
        else:
            return did_wallet_puzzles.create_full_puzzle(inner_puzzle, 0x00)
    '''

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            bytes((await self.wallet_state_manager.get_unused_derivation_record(self.db_wallet_info.id)).pubkey)
        )

    # coins_of_interest_received
    # coins_of_interest_added
    # coins_of_interest_removed
    # get_relevant_additions
    # reorg_rollback
    # search_blockrecords_for_puzzle_hash
    # puzzle_solution_received

    def load_info(self, wallet_info: WalletInfo) -> None:
        pool_info_json: Dict = json.loads(wallet_info.data)
        self.pool_info = PoolWalletInfo.from_json_dict(pool_info_json)

    async def save_info(self, pool_info: PoolWalletInfo, in_transaction: bool) -> None:
        self.pool_info = pool_info
        current_info = self.db_wallet_info
        data_str = json.dumps(pool_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.db_wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)
        # TODO: Notify GUI here

    async def add_self_pooled_reward(self, name: bytes32, in_transaction: bool):
        self.log.info(f"Adding self_pooled_reward {name}")
        new_reward_list = self.pool_info.self_pooled_reward_list.copy()
        new_reward_list.append(name)
        new_pool_info = PoolWalletInfo(
            self.pool_info.current,
            self.pool_info.target,
            self.pool_info.pending_transaction,
            self.pool_info.launcher_coin,
            self.pool_info.launcher_id,
            self.pool_info.parent_list,
            self.pool_info.current_inner,
            new_reward_list,
            self.pool_info.owner_pubkey,
            self.pool_info.owner_target_puzzle_hash,
        )
        await self.save_info(new_pool_info, in_transaction)

    async def add_parent(self, name: bytes32, parent: Optional[CCParent], in_transaction: bool):
        self.log.info(f"Adding parent {name}: {parent}")
        new_parent_list = self.pool_info.parent_list.copy()
        new_parent_list.append((name, parent))
        new_pool_info = PoolWalletInfo(
            self.pool_info.current,
            self.pool_info.target,
            self.pool_info.pending_transaction,
            self.pool_info.launcher_coin,
            self.pool_info.launcher_id,
            new_parent_list,
            self.pool_info.current_inner,
            self.pool_info.self_pooled_reward_list,
            self.pool_info.owner_pubkey,
            self.pool_info.owner_target_puzzle_hash,
        )
        await self.save_info(new_pool_info, in_transaction)

    async def set_launcher(self, launcher: Coin, in_transaction: bool):
        new_pool_info = PoolWalletInfo(
            self.pool_info.current,
            self.pool_info.target,
            self.pool_info.pending_transaction,
            launcher,
            self.pool_info.launcher_id,
            self.pool_info.parent_list,
            self.pool_info.current_inner,
            self.pool_info.self_pooled_reward_list,
            self.pool_info.owner_pubkey,
            self.pool_info.owner_target_puzzle_hash,
        )
        await self.save_info(new_pool_info, in_transaction)

    async def set_pending_transaction(self, tx: TransactionRecord, in_transaction: bool):
        new_pool_info = PoolWalletInfo(
            self.pool_info.current,
            self.pool_info.target,
            tx,
            self.pool_info.launcher_coin,
            self.pool_info.launcher_id,
            self.pool_info.parent_list,
            self.pool_info.current_inner,
            self.pool_info.self_pooled_reward_list,
            self.pool_info.owner_pubkey,
            self.pool_info.owner_target_puzzle_hash,
        )
        await self.save_info(new_pool_info, in_transaction)

    async def _set_target_state(self, target: PoolState, in_transaction: bool):
        new_pool_info = PoolWalletInfo(
            self.pool_info.current,
            target,
            self.pool_info.pending_transaction,
            self.pool_info.launcher_coin,
            self.pool_info.launcher_id,
            self.pool_info.parent_list,
            self.pool_info.current_inner,
            self.pool_info.self_pooled_reward_list,
            self.pool_info.owner_pubkey,
            self.pool_info.owner_target_puzzle_hash,
        )
        await self.save_info(new_pool_info, in_transaction)

    # TODO: @aqk puzzle_for_pk: Need a better API to request and index these
    # `puzzle_for_pk` is called from self.wallet_state_manager.add_new_wallet()

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        if self.pool_info.launcher_coin is None:
            return None

        # inner_puzzle = pool_puzzles.create_inner_puzzle(
        #    pubkey, self.did_info.backup_ids, self.did_info.num_of_backup_ids_needed
        # )

        # owner_puzzle_hash: bytes32 = self.current_rewards_puzzle_hash
        # owner_pubkey: bytes = self.current_rewards_pubkey
        # pool_puzzle_hash: bytes32 = self.current_rewards_puzzle_hash
        relative_lock_height = self.pool_info.current.relative_lock_height

        # xxx

        inner_puzzle = create_self_pooling_inner_puzzle(
            self.pool_info.owner_target_puzzle_hash, self.pool_info.owner_pubkey
        )
        return create_full_puzzle(inner_puzzle, self.pool_info.launcher_coin.name())
        # xxx

        # pool_info.current vs. target

        # PENDING_CREATION = 1
        # SELF_POOLING = 2
        # LEAVING_POOL = 3
        # FARMING_TO_POOL = 4
        """
        if self.pool_info.current.state == PENDING_CREATION:
            # XXX danger
            if self.pool_info.target.state == SELF_POOLING:
                pass
            elif self.pool_info.target.state == FARMING_TO_POOL:
                pass
            else:
                raise AssertError("puzzle_for_pk: Invalid state current={self.pool_info.current.state} target={self.pool_info.target.state}")
            inner_puzzle = pool_puzzles.create_inner_puzzle(
            # XXX danger
        elif self.pool_info.current.state == SELF_POOLING:
            inner_puzzle = pool_puzzles.create_self_pooling_inner_puzzle(
                owner_puzzle_hash, owner_pubkey)
        elif self.pool_info.current.state == LEAVING_POOL:
            inner_puzzle = pool_puzzles.create_escaping_inner_puzzle(
                pool_puzzle_hash, relative_lock_height, owner_pubkey)
        elif self.pool_info.current.state == FARMING_TO_POOL:
            inner_puzzle = pool_puzzles.create_pool_member_inner_puzzle(
                pool_puzzle_hash, relative_lock_height, powner_pubkey)
        else:
            raise AssertError("puzzle_for_pk: Invalid state current={self.pool_info.current.state} target={self.pool_info.target.state}")
            #return None  # TODO: validate and raise in this case
        # TODO: 2nd argument: genesis puzzle_hash or launcher_coin.name
        return pool_puzzles.create_full_puzzle(inner_puzzle, self.pool_info.launcher_coin.name())

        """

    async def get_confirmed_balance(self, record_list=None) -> uint64:
        return uint64(1)

    async def get_unconfirmed_balance(self, record_list=None) -> uint64:
        return uint64(1)

    async def get_spendable_balance(self, record_list=None) -> uint64:
        return uint64(1)

    async def get_pending_change_balance(self, record_list=None) -> uint64:
        return uint64(1)

    async def get_max_send_amount(self, record_list=None) -> uint64:
        return uint64(1)

        """
        if record_list is None:
            record_list = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.id())

        amount: uint64 = uint64(0)
        for record in record_list:
            parent = await self.get_parent_for_coin(record.coin)
            if parent is not None:
                amount = uint64(amount + record.coin.amount)

        self.log.info(f"Confirmed balance for pool wallet {self.id()} is {amount}")
        return uint64(amount)
        """

    # TODO: Need to be able to retrieve owner_pubkey from blockchain
