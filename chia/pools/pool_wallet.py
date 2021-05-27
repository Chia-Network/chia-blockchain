import logging
import time
from typing import Any, Optional, Set, Tuple, List, Dict

from blspy import AugSchemeMPL, PrivateKey, G2Element, G1Element

from chia.pools.pool_config import PoolWalletConfig, load_pool_config
from chia.pools.pool_wallet_info import (
    PoolWalletInfo,
    PoolSingletonState,
    PoolState,
    POOL_PROTOCOL_VERSION,
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
)
from chia.util.config import load_config

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
    target_state: PoolState
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
        return self.wallet_info.id

    def _init_log(self, name):
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

    @classmethod
    def _verify_self_pooled(cls, state) -> Optional[str]:
        err = ""
        if state.pool_url is not None:
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

    async def get_current_state(self, all_spends: Optional[List[CoinSolution]] = None) -> PoolWalletInfo:
        if all_spends is None:
            history: List[
                Tuple[int, uint32, CoinSolution]
            ] = await self.wallet_state_manager.pool_store.get_all_state_transitions(self.wallet_id)
            all_spends: List[CoinSolution] = [cs for _, _, cs in history]

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
        return PoolWalletInfo(extra_data, self.target_state, launcher_coin, current_inner, tip_singleton_coin_id)

    async def get_tip(self) -> bytes32:
        return (await self.get_current_state()).tip_singleton_coin_id

    async def update_pool_config(self, spends: List[CoinSolution], make_new_authentication_key: bool):
        current_state: PoolWalletInfo = await self.get_current_state(spends)
        # config_list: List[PoolWalletConfig] = load_pool_config(self.wallet_state_manager.wallet_node.root_path)
        # full_config: Dict = load_config(self.wallet_state_manager.wallet_node.root_path, "config.yaml")
        #
        # found = False
        # for config in full_config:
        #     if config.launcher_id == current_state.launcher_coin.name():
        #         found = True
        #         if make_new_authentication_key:
        #             owner_sk: PrivateKey = await find_owner_sk(
        #                 [self.wallet_state_manager.private_key], config.owner_public_key
        #             )
        #             new_auth_sk: PrivateKey = master_sk_to_pooling_authentication_sk(
        #                 self.wallet_state_manager.private_key, uint32(self.wallet_id), uint32(0)
        #             )
        #             auth_pk: G1Element = new_auth_sk.get_g1()
        #             auth_pk_timestamp: uint64 = uint64(int(time.time()))
        #             auth_key_signature: G2Element = AugSchemeMPL.sign(
        #                 owner_sk, AuthenticationKeyInfo(auth_pk, auth_pk_timestamp)
        #             )
        #             pool_payout_instructions: str = (await self.standard_wallet.get_new_puzzlehash()).hex()
        #         else:
        #             auth_pk = config.authentication_public_key
        #             auth_pk_timestamp = config.authentication_public_key_timestamp
        #             auth_key_signature = config.authentication_key_info_signature
        #             pool_payout_instructions = config.pool_payout_instructions
        #         new_config = PoolWalletConfig(
        #             current_state.current.pool_url,
        #             pool_payout_instructions,
        #             current_state.current.target_puzzle_hash,
        #             config.launcher_id,
        #             current_state.current.owner_pubkey,
        #             auth_pk,
        #             auth_pk_timestamp,
        #             auth_key_signature,
        #         )
        #
        # if not found and not make_new_authentication_key:
        #     raise ValueError("Can't use existing authentication key because config was not found")

    @staticmethod
    def get_next_interesting_coin_ids(spend: CoinSolution) -> List[bytes32]:
        # CoinSolution of one of the coins that we cared about. This coin was spent in a block, but might be in a reorg
        # If we return a value, it is a coin ID that we are also interested in (to support two transitions per block)
        additions: List[Coin] = spend.additions()
        for coin in additions:
            if coin.amount % 2 == 1:
                return [coin.name()]
        return []

    async def apply_state_transitions(self, block_spends: List[CoinSolution], block_height: uint32):
        """
        Updates the Pool state (including DB) with new singleton spends. The block spends can contain many spends
        that we are not interested in, and can contain many ephemeral spends. They must all be in the same block.
        The DB must be committed after calling this method.
        """
        history: List[
            Tuple[int, uint32, CoinSolution]
        ] = await self.wallet_state_manager.pool_store.get_all_state_transitions(self.wallet_id)
        all_spends: List[CoinSolution] = [cs for _, _, cs in history]
        tip: bytes32 = await self.get_tip()
        # Applies the spends one at a time. We need to keep track of the new ones, so we can add them to the DB
        # at the end. We don't add them one at a time because we cannot commit to the DB until later.
        new_spends: List[CoinSolution] = []
        advanced_state = True
        while advanced_state:
            advanced_state = False
            for spend in block_spends:
                if spend.coin.name() == tip:
                    new_tip: bytes32 = get_most_recent_singleton_coin_from_coin_solution(spend).name()
                    if new_tip != tip:
                        # Updated tip
                        self.log.info(f"Updated tip of this pool wallet to {self.get_tip()}")
                        tip = new_tip
                        all_spends.append(spend)
                        new_spends.append(spend)
                        advanced_state = True
                        break
        await self.wallet_state_manager.pool_store.apply_state(self.wallet_id, new_spends, block_height)
        await self.update_pool_config(all_spends, False)

    async def rewind(self, block_height: int) -> None:
        """
        Rolls back all transactions after block_height, and if creation was after block_height, deletes the wallet.
        """
        await self.wallet_state_manager.pool_store.rollback(block_height)
        history: List[
            Tuple[int, uint32, CoinSolution]
        ] = await self.wallet_state_manager.pool_store.get_all_state_transitions(self.wallet_id)
        if history[0][1] > block_height:
            await self.wallet_state_manager.user_store.delete_wallet(self.wallet_id)

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

        await self.wallet_state_manager.pool_store.apply_state(self.wallet_id, [launcher_spend], block_height)
        await self.update_pool_config([launcher_spend], True)

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

        # inner always starts in "member" state; either self or pooled
        escaping_inner_puzzle_hash: bytes32 = create_escaping_inner_puzzle(
            initial_target_state.target_puzzle_hash,
            initial_target_state.relative_lock_height,
            initial_target_state.owner_pubkey,
        )

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

    async def join_pool(self, target_state: PoolState):
        if self.target_state is not None:
            raise ValueError(f"Cannot join a pool when already having target state: {self.target_state}")
        self.target_state = target_state
        current_state = await self.get_current_state()

        all_sks = [self.wallet_state_manager.private_key]
        owner_sk: PrivateKey = await find_owner_sk(all_sks, current_state.current.owner_pubkey)
        # Check if we can join a pool (timelock)
        # Create the first blockchain transaction
        # Whenever we detect a new peak, potentially initiate the second blockchain transaction

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
        pass

    async def new_peak(self) -> None:
        # This gets called from the WalletStateManager whenever there is a new peak
        pass

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
