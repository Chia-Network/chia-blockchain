import logging
import time
from typing import Any, Optional, Set, Tuple, List, Dict

from blspy import AugSchemeMPL, PrivateKey, G2Element, G1Element

from chia.consensus.block_record import BlockRecord
from chia.pools.pool_config import PoolWalletConfig, load_pool_config, update_pool_config
from chia.pools.pool_wallet_info import (
    PoolWalletInfo,
    PoolSingletonState,
    PoolState,
    POOL_PROTOCOL_VERSION,
    FARMING_TO_POOL,
    SELF_POOLING,
)
from chia.protocols.pool_protocol import AuthenticationKeyInfo

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
    create_pooling_inner_puzzle,
    solution_to_extra_data,
    pool_state_to_inner_puzzle,
    get_most_recent_singleton_coin_from_coin_solution,
    launcher_id_to_p2_puzzle_hash,
    create_member_spend, uncurry_pool_member_inner_puzzle,
)

from chia.util.ints import uint8, uint32, uint64
from chia.wallet.derive_keys import find_owner_sk, master_sk_to_pooling_authentication_sk
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet

from chia.wallet.wallet_info import WalletInfo
from chia.wallet.util.transaction_type import TransactionType


class PoolWallet:
    MINIMUM_INITIAL_BALANCE = 1
    MINIMUM_RELATIVE_LOCK_HEIGHT = 10

    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    target_state: Optional[PoolState]
    standard_wallet: Wallet
    wallet_id: int
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

    Control of switching states is granted to the owner public key.

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
        return self.wallet_info.id

    def _init_log(self, name):
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

    @classmethod
    def _verify_self_pooled(cls, state) -> Optional[str]:
        err = ""
        if state.pool_url != "":
            err += " Unneeded pool_url for self-pooling"

        if state.relative_lock_height != 0:
            err += " Incorrect relative_lock_height for self-pooling"

        return None if err == "" else err

    @classmethod
    def _verify_pooling_state(cls, state) -> Optional[str]:
        err = ""
        if state.relative_lock_height < cls.MINIMUM_RELATIVE_LOCK_HEIGHT:
            err += (
                f" Pool relative_lock_height ({state.relative_lock_height})"
                f"is less than recommended minimum ({cls.MINIMUM_RELATIVE_LOCK_HEIGHT})"
            )

        if state.pool_url in [None, ""]:
            err += " Empty pool url in pooling state"
        return err

    @classmethod
    def _verify_pool_state(cls, state: PoolState) -> Optional[str]:
        # SELF_POOLING = 1
        # LEAVING_POOL = 2
        # FARMING_TO_POOL = 3
        if state.target_puzzle_hash is None:
            return "Invalid puzzle_hash"

        if state.version > POOL_PROTOCOL_VERSION:
            return (
                f"Detected pool protocol version {state.version}, which is "
                f"newer than this wallet's version ({POOL_PROTOCOL_VERSION}). Please upgrade "
                f"to use this pooling wallet"
            )

        if state.state == PoolSingletonState.SELF_POOLING:
            return cls._verify_self_pooled(state)
        elif state.state == PoolSingletonState.FARMING_TO_POOL or state.state == PoolSingletonState.LEAVING_POOL:
            return cls._verify_pooling_state(state)
        else:
            return "Internal Error"

    @classmethod
    def _verify_initial_target_state(cls, initial_target_state):
        err = cls._verify_pool_state(initial_target_state)
        if err:
            raise ValueError(f"Invalid internal Pool State: {err}: {initial_target_state}")

    async def get_spend_history(self) -> List[Tuple[uint32, CoinSolution]]:
        return self.wallet_state_manager.pool_store.get_spends_for_wallet(self.wallet_id)

    async def get_current_state(self) -> PoolWalletInfo:
        history: List[Tuple[uint32, CoinSolution]] = await self.get_spend_history()
        all_spends: List[CoinSolution] = [cs for _, cs in history]

        # We must have at least the launcher spend
        assert len(all_spends) >= 1

        launcher_coin: Coin = all_spends[0].coin
        tip_singleton_coin_id: bytes32 = get_most_recent_singleton_coin_from_coin_solution(all_spends[-1]).name()

        curr_spend_i = len(all_spends) - 1
        extra_data: Optional[PoolState] = None
        while extra_data is None:
            full_spend: CoinSolution = all_spends[curr_spend_i]
            extra_data = solution_to_extra_data(full_spend)

        assert extra_data is not None
        current_inner = pool_state_to_inner_puzzle(extra_data)
        launcher_id: bytes32 = launcher_coin.name()
        p2_singleton_puzzle_hash = launcher_id_to_p2_puzzle_hash(launcher_id)
        return PoolWalletInfo(
            extra_data,
            self.target_state,
            launcher_coin,
            launcher_id,
            p2_singleton_puzzle_hash,
            current_inner,
            tip_singleton_coin_id,
        )

    async def get_tip(self) -> Tuple[uint32, CoinSolution]:
        return self.wallet_state_manager.pool_store.get_spends_for_wallet(self.wallet_id)[-1]

    async def update_pool_config(self, make_new_authentication_key: bool):
        current_state: PoolWalletInfo = await self.get_current_state()
        pool_config_list: List[PoolWalletConfig] = load_pool_config(self.wallet_state_manager.root_path)
        pool_config_dict: Dict[bytes32, PoolWalletConfig] = {c.launcher_id: c for c in pool_config_list}
        owner_sk: PrivateKey = await find_owner_sk(
            [self.wallet_state_manager.private_key],
            current_state.current.owner_pubkey,
        )
        existing_config: Optional[PoolWalletConfig] = pool_config_dict.get(current_state.launcher_id, None)

        if existing_config is None and not make_new_authentication_key:
            raise ValueError("Can't use existing authentication key because config was not found")
        if make_new_authentication_key or existing_config is None:
            new_auth_sk: PrivateKey = master_sk_to_pooling_authentication_sk(
                self.wallet_state_manager.private_key, uint32(self.wallet_id), uint32(0)
            )
            auth_pk: G1Element = new_auth_sk.get_g1()
            auth_pk_timestamp: uint64 = uint64(int(time.time()))
            auth_key_signature: G2Element = AugSchemeMPL.sign(
                owner_sk, bytes(AuthenticationKeyInfo(auth_pk, auth_pk_timestamp))
            )
            pool_payout_instructions: str = (await self.standard_wallet.get_new_puzzlehash(in_transaction=True)).hex()
        else:
            auth_pk = existing_config.authentication_public_key
            auth_pk_timestamp = existing_config.authentication_public_key_timestamp
            auth_key_signature = existing_config.authentication_key_info_signature
            pool_payout_instructions = existing_config.pool_payout_instructions

        new_config: PoolWalletConfig = PoolWalletConfig(
            current_state.current.pool_url,
            pool_payout_instructions,
            current_state.current.target_puzzle_hash,
            current_state.launcher_id,
            current_state.current.owner_pubkey,
            auth_pk,
            auth_pk_timestamp,
            auth_key_signature,
        )
        pool_config_dict[new_config.launcher_id] = new_config
        self.log.warning(
            f"Updating pool config to {list(pool_config_dict.values())}., root {self.wallet_state_manager.root_path}"
        )
        await update_pool_config(self.wallet_state_manager.root_path, list(pool_config_dict.values()))

    @staticmethod
    def get_next_interesting_coin_ids(spend: CoinSolution) -> List[bytes32]:
        # CoinSolution of one of the coins that we cared about. This coin was spent in a block, but might be in a reorg
        # If we return a value, it is a coin ID that we are also interested in (to support two transitions per block)
        coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_solution(spend)
        if coin is not None:
            return [coin.name()]
        return []

    async def apply_state_transitions(self, block_spends: List[CoinSolution], block_height: uint32):
        """
        Updates the Pool state (including DB) with new singleton spends. The block spends can contain many spends
        that we are not interested in, and can contain many ephemeral spends. They must all be in the same block.
        The DB must be committed after calling this method. All validation should be done here.
        """
        coin_name_to_spend: Dict[bytes32, CoinSolution] = {cs.coin.name(): cs for cs in block_spends}

        tip: Tuple[uint32, CoinSolution] = await self.get_tip()
        spend_height = tip[0]
        tip_spend = tip[1]

        while get_most_recent_singleton_coin_from_coin_solution(tip_spend).name() in coin_name_to_spend:
            assert block_height < spend_height  # We should not have a spend with a lesser block height
            spend: CoinSolution = coin_name_to_spend[tip]
            await self.wallet_state_manager.pool_store.add_spend(self.wallet_id, spend, block_height)
            new_tip = await self.get_tip()
            await self.coin_spent(new_tip[1])
        await self.update_pool_config(False)

    async def coin_spent(self, coin_solution: CoinSolution):
        """
        Our singleton being spent indicates a change to our `current_state`
        A spend to our p2_singleton address indicates a payment to ourselves (self pooling),
        or to our pool, both of which we should track.
        """
        coin = coin_solution.coin
        sol = coin_solution.solution
        puz = coin_solution.puzzle_reveal
        amount = uint64(1)
        if self.target_state is None:
            self.log.info("PoolWallet state updated by external event: {coin}")
            pass

        # xxx
        new_singleton_coin = Coin(coin.name(), puz.get_tree_hash(), amount)
        new_current_state: Optional[PoolState] = solution_to_extra_data(
            coin_solution
        )  # TODO: Test that this works with escaping and member puzzles
        self._verify_pool_state(new_current_state)
        current_state: PoolWalletInfo = await self.get_current_state()
        assert self.target_state == current_state.target

        # Now see if we need to change target state
        if self.target_state == new_current_state:
            # We reach!
            self.target_state = None

    async def rewind(self, block_height: int) -> bool:
        """
        Rolls back all transactions after block_height, and if creation was after block_height, deletes the wallet.
        Returns True if the wallet should be removed.
        """
        history: List[Tuple[uint32, CoinSolution]] = self.wallet_state_manager.pool_store.get_spends_for_wallet(
            self.wallet_id
        ).copy()
        prev_state: PoolWalletInfo = await self.get_current_state()
        await self.wallet_state_manager.pool_store.rollback(block_height, self.wallet_id)
        await self.wallet_state_manager.interested_store.remove_interested_puzzle_hash(
            prev_state.p2_singleton_puzzle_hash, in_transaction=True
        )

        if len(history) > 0 and history[0][0] > block_height:
            # If we have no entries in the DB, we have no singleton, so we should not have a wallet either
            # The PoolWallet object becomes invalid after this.
            return True
        else:
            if await self.get_current_state() != prev_state:
                await self.update_pool_config(False)
            return False

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        launcher_coin_id: bytes32,
        block_spends: List[CoinSolution],
        block_height: uint32,
        in_transaction: bool,
        name: str = None,
    ):
        """
        This creates a new PoolWallet with only one spend: the launcher spend. The DB MUST be committed after calling
        this method.
        """
        self = PoolWallet()
        self.wallet_state_manager = wallet_state_manager

        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "Pool wallet", WalletType.POOLING_WALLET.value, "", in_transaction=in_transaction
        )
        self.wallet_id = self.wallet_info.id
        self.standard_wallet = wallet
        self.target_state = None
        self._init_log(name)

        launcher_spend: Optional[CoinSolution] = None
        for spend in block_spends:
            if spend.coin.name() == launcher_coin_id:
                launcher_spend = spend
        assert launcher_spend is not None
        await self.wallet_state_manager.pool_store.add_spend(self.wallet_id, launcher_spend, block_height)
        await self.update_pool_config(True)

        p2_puzzle_hash: bytes32 = (await self.get_current_state()).p2_singleton_puzzle_hash
        await self.wallet_state_manager.interested_store.add_interested_puzzle_hash(
            p2_puzzle_hash, self.wallet_id, True
        )

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id, create_puzzle_hashes=False)
        return self

    @staticmethod
    async def create_from_db(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = None,
    ):
        """
        This creates a PoolWallet from DB. However, all data is already handled by WalletPoolStore, so we don't need
        to do anything here.
        """
        self = PoolWallet()
        self.wallet_state_manager = wallet_state_manager
        self.wallet_id = wallet_info.id
        self.standard_wallet = wallet
        self.wallet_info = wallet_info
        self.target_state = None
        self._init_log(name)

        return self

    @staticmethod
    async def create_new_pool_wallet_transaction(
        wallet_state_manager: Any,
        main_wallet: Wallet,
        initial_target_state: PoolState,
        fee: uint64 = uint64(0),
    ) -> TransactionRecord:
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
        standard_wallet = main_wallet
        wallet_state_manager = wallet_state_manager

        unspent_records = await wallet_state_manager.coin_store.get_unspent_coins_for_wallet(standard_wallet.wallet_id)
        balance = await standard_wallet.get_confirmed_balance(unspent_records)
        if balance < PoolWallet.MINIMUM_INITIAL_BALANCE:
            raise ValueError("Not enough balance in main wallet to create a managed plotting pool.")
        if balance < fee:
            raise ValueError("Not enough balance in main wallet to create a managed plotting pool with fee {fee}.")

        # Verify Parameters - raise if invalid
        PoolWallet._verify_initial_target_state(initial_target_state)

        spend_bundle, singleton_puzzle_hash = await PoolWallet.generate_launcher_spend(
            standard_wallet, uint64(1), initial_target_state
        )

        if spend_bundle is None:
            raise ValueError("failed to generate ID for wallet")

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
            wallet_id=wallet_state_manager.main_wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
        )
        await standard_wallet.push_transaction(standard_wallet_record)
        return standard_wallet_record

    async def generate_member_spend(self) -> Tuple[SpendBundle, bytes32]:
        # target_state is contained within pool_wallet_state
        pool_wallet_state: PoolWalletInfo = await self.get_current_state()
        spend_history = await self.get_spend_history()
        last_coin_solution: CoinSolution = spend_history[-1][1]
        member_coin_solution, full_puzzle, inner_puzzle = create_member_spend(last_coin_solution, pool_wallet_state)
        puzzle_hash = full_puzzle.get_tree_hash()
        inner_f, target_puzzle_hash, p2_singleton_hash, owner_pubkey, pool_reward_prefix, escape_puzzlehash = uncurry_pool_member_inner_puzzle(inner_puzzle)
        spend_bundle: SpendBundle = SpendBundle([member_coin_solution], AugSchemeMPL.aggregate([]))
        return spend_bundle, puzzle_hash

    async def generate_member_transaction(self, target_state: PoolState) -> TransactionRecord:
        singleton_amount = uint64(1)
        self.target_state = target_state  # Yuck! TODO: Fix this.
        spend_bundle, new_singleton_puzzle_hash = await self.generate_member_spend()
        # inner_puzzle: Program = pool_state_to_inner_puzzle(target_state)
        # launcher_id = await self.get_current_state().launcher_coin.name()
        # full_puzzle: Program = create_full_puzzle(inner_puzzle, launcher_id)
        assert spend_bundle is not None

        tx_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=new_singleton_puzzle_hash,
            amount=uint64(singleton_amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
        )
        self.log.warning(f"generate_member_transaction removal_id={spend_bundle.removals()[0].name()}")
        self.log.warning(
            f"generate_member_transaction: additions={spend_bundle.additions()}, removals={spend_bundle.removals()}")
        return tx_record

    @staticmethod
    async def generate_launcher_spend(
        standard_wallet: Wallet,
        amount: uint64,
        initial_target_state: PoolState,
    ) -> Tuple[SpendBundle, bytes32]:
        """
        Creates the initial singleton, which includes spending an origin coin, the launcher, and creating a singleton
        with the "pooling" inner state, which can be either self pooling or using a pool
        """

        coins: Set[Coin] = await standard_wallet.select_coins(amount)
        if coins is None:
            raise ValueError("Not enough coins to create pool wallet")

        assert len(coins) == 1

        launcher_parent: Coin = coins.copy().pop()
        genesis_launcher_puz: Program = SINGLETON_LAUNCHER
        launcher_coin: Coin = Coin(launcher_parent.name(), genesis_launcher_puz.get_tree_hash(), amount)

        escaping_inner_puzzle_hash: bytes32 = create_escaping_inner_puzzle(
            initial_target_state.target_puzzle_hash,
            initial_target_state.relative_lock_height,
            initial_target_state.owner_pubkey,
        )

        # inner always starts in "member" state; either self or pooled
        self_pooling_inner_puzzle: Program = create_pooling_inner_puzzle(
            initial_target_state.target_puzzle_hash, escaping_inner_puzzle_hash, initial_target_state.owner_pubkey
        )
        full_pooling_puzzle: Program = create_full_puzzle(self_pooling_inner_puzzle, launcher_id=launcher_coin.name())

        puzzle_hash: bytes32 = full_pooling_puzzle.get_tree_hash()
        extra_data_bytes = bytes(initial_target_state)

        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([puzzle_hash, amount, extra_data_bytes]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message).name())

        create_launcher_tx_record: Optional[TransactionRecord] = await standard_wallet.generate_signed_transaction(
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

        genesis_launcher_solution: Program = Program.to([puzzle_hash, amount, extra_data_bytes])

        launcher_cs: CoinSolution = CoinSolution(
            launcher_coin,
            SerializedProgram.from_program(genesis_launcher_puz),
            SerializedProgram.from_program(genesis_launcher_solution),
        )
        launcher_sb: SpendBundle = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))

        # Current inner will be updated when state is verified on the blockchain
        full_spend: SpendBundle = SpendBundle.aggregate([create_launcher_tx_record.spend_bundle, launcher_sb])
        return full_spend, puzzle_hash

    async def _try_to_farm_to_pool(self, target_state: PoolState):

        tx_record = await self.generate_member_transaction(target_state)

        if tx_record is None:
            raise ValueError("failed to generate transaction to farm to pool")

        await self.standard_wallet.push_transaction(tx_record)
        return tx_record

    async def _try_to_self_pool(self, target_state: PoolState):
        pass

    async def transition(self, target_state: PoolState):
        """
        Attempt to move to `target_state` or to LEAVING_POOL state, as appropriate.
        Compare target_state and self.get_current_state() to determine next state
        """
        if target_state is None:
            raise ValueError(f"invalid target_state {target_state}")
        current_state = await self.get_current_state()

        #

        if current_state == target_state:
            self.target_state = None
            self.log.info("Asked to change to current state. Target = {target_state}")
            return

        if self.target_state is not None:
            raise ValueError(
                f"Cannot change to state {target_state} when already having target state: {self.target_state}"
            )

        # TODO: Do not set target state until all checks are done
        self.target_state = target_state

        all_sks = [self.wallet_state_manager.private_key]
        owner_sk: PrivateKey = await find_owner_sk(all_sks, current_state.current.owner_pubkey)

        # Check if we can join a pool (timelock)
        # Create the first blockchain transaction
        # Whenever we detect a new peak, potentially initiate the second blockchain transaction
        # verify target state

        tx = None
        if target_state.state == FARMING_TO_POOL:
            tx = await self._try_to_farm_to_pool(target_state)
        elif target_state.state == SELF_POOLING:
            tx = await self._try_to_self_pool(target_state)

        return tx

    async def join_pool(self, target_state: PoolState):
        if target_state.state != FARMING_TO_POOL:
            raise ValueError(f"join_pool must be called with target_state={FARMING_TO_POOL} (FARMING_TO_POOL)")
        if self.target_state is not None:
            raise ValueError(f"Cannot join a pool when already having target state: {self.target_state}")

        return await self.transition(target_state)

    async def self_pool(self, target_state: PoolState):
        if self.target_state is not None:
            raise ValueError(f"Cannot self pool when already having target state: {self.target_state}")
        self.target_state = target_state
        current_state = await self.get_current_state()
        all_sks = [self.wallet_state_manager.private_key]
        owner_sk: PrivateKey = await find_owner_sk(all_sks, current_state.current.owner_pubkey)
        # Check if we can self pool (timelock)
        # Create the first blockchain transaction
        # Whenever we detect a new peak, potentially initiate the second blockchain transaction
        pass

    async def claim_pool_rewards(self) -> None:
        # Search for p2_puzzle_hash coins, and spend them with the singleton
        current_state: PoolWalletInfo = await self.get_current_state()
        if (
            current_state.current.state != PoolSingletonState.SELF_POOLING
            and current_state.current.state != PoolSingletonState.LEAVING_POOL
        ):
            raise ValueError("Cannot claim rewards, invali")

        # unspent_coin_records = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.wallet_id)
        pass

    async def new_peak(self, peak: BlockRecord) -> None:
        # This gets called from the WalletStateManager whenever there is a new peak
        pass

    async def get_confirmed_balance(self, record_list=None) -> uint64:
        return await self.wallet_state_manager.get_confirmed_balance_for_wallet(self.wallet_id, record_list)

    async def get_unconfirmed_balance(self, record_list=None) -> uint64:
        return await self.get_confirmed_balance(record_list)

    async def get_spendable_balance(self, record_list=None) -> uint64:
        return await self.get_confirmed_balance(record_list)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def get_max_send_amount(self, record_list=None) -> uint64:
        return uint64(0)
