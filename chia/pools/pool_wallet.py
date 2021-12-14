import logging
import time
from typing import Any, Optional, Set, Tuple, List, Dict

from blspy import PrivateKey, G2Element, G1Element

from chia.consensus.block_record import BlockRecord
from chia.pools.pool_config import PoolWalletConfig, load_pool_config, update_pool_config
from chia.pools.pool_wallet_info import (
    PoolWalletInfo,
    PoolSingletonState,
    PoolState,
    FARMING_TO_POOL,
    SELF_POOLING,
    LEAVING_POOL,
    create_pool_state,
)
from chia.protocols.pool_protocol import POOL_PROTOCOL_VERSION

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle

from chia.pools.pool_puzzles import (
    create_waiting_room_inner_puzzle,
    create_full_puzzle,
    SINGLETON_LAUNCHER,
    create_pooling_inner_puzzle,
    solution_to_pool_state,
    pool_state_to_inner_puzzle,
    get_most_recent_singleton_coin_from_coin_spend,
    launcher_id_to_p2_puzzle_hash,
    create_travel_spend,
    uncurry_pool_member_inner_puzzle,
    create_absorb_spend,
    is_pool_member_inner_puzzle,
    is_pool_waitingroom_inner_puzzle,
    uncurry_pool_waitingroom_inner_puzzle,
    get_delayed_puz_info_from_launcher_spend,
)

from chia.util.ints import uint8, uint32, uint64
from chia.wallet.derive_keys import (
    master_sk_to_pooling_authentication_sk,
    find_owner_sk,
)
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord

from chia.wallet.wallet_info import WalletInfo
from chia.wallet.util.transaction_type import TransactionType


class PoolWallet:
    MINIMUM_INITIAL_BALANCE = 1
    MINIMUM_RELATIVE_LOCK_HEIGHT = 5
    MAXIMUM_RELATIVE_LOCK_HEIGHT = 1000

    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    target_state: Optional[PoolState]
    next_transaction_fee: uint64
    standard_wallet: Wallet
    wallet_id: int
    singleton_list: List[Coin]
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
        elif state.relative_lock_height > cls.MAXIMUM_RELATIVE_LOCK_HEIGHT:
            err += (
                f" Pool relative_lock_height ({state.relative_lock_height})"
                f"is greater than recommended maximum ({cls.MAXIMUM_RELATIVE_LOCK_HEIGHT})"
            )

        if state.pool_url in [None, ""]:
            err += " Empty pool url in pooling state"
        return err

    @classmethod
    def _verify_pool_state(cls, state: PoolState) -> Optional[str]:
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

    async def get_spend_history(self) -> List[Tuple[uint32, CoinSpend]]:
        return self.wallet_state_manager.pool_store.get_spends_for_wallet(self.wallet_id)

    async def get_current_state(self) -> PoolWalletInfo:
        history: List[Tuple[uint32, CoinSpend]] = await self.get_spend_history()
        all_spends: List[CoinSpend] = [cs for _, cs in history]

        # We must have at least the launcher spend
        assert len(all_spends) >= 1

        launcher_coin: Coin = all_spends[0].coin
        delayed_seconds, delayed_puzhash = get_delayed_puz_info_from_launcher_spend(all_spends[0])
        tip_singleton_coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(all_spends[-1])
        launcher_id: bytes32 = launcher_coin.name()
        p2_singleton_puzzle_hash = launcher_id_to_p2_puzzle_hash(launcher_id, delayed_seconds, delayed_puzhash)
        assert tip_singleton_coin is not None

        curr_spend_i = len(all_spends) - 1
        pool_state: Optional[PoolState] = None
        last_singleton_spend_height = uint32(0)
        while pool_state is None:
            full_spend: CoinSpend = all_spends[curr_spend_i]
            pool_state = solution_to_pool_state(full_spend)
            last_singleton_spend_height = uint32(history[curr_spend_i][0])
            curr_spend_i -= 1

        assert pool_state is not None
        current_inner = pool_state_to_inner_puzzle(
            pool_state,
            launcher_coin.name(),
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            delayed_seconds,
            delayed_puzhash,
        )
        return PoolWalletInfo(
            pool_state,
            self.target_state,
            launcher_coin,
            launcher_id,
            p2_singleton_puzzle_hash,
            current_inner,
            tip_singleton_coin.name(),
            last_singleton_spend_height,
        )

    async def get_unconfirmed_transactions(self) -> List[TransactionRecord]:
        return await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(self.wallet_id)

    async def get_tip(self) -> Tuple[uint32, CoinSpend]:
        return self.wallet_state_manager.pool_store.get_spends_for_wallet(self.wallet_id)[-1]

    async def update_pool_config(self, make_new_authentication_key: bool):
        current_state: PoolWalletInfo = await self.get_current_state()
        pool_config_list: List[PoolWalletConfig] = load_pool_config(self.wallet_state_manager.root_path)
        pool_config_dict: Dict[bytes32, PoolWalletConfig] = {c.launcher_id: c for c in pool_config_list}
        existing_config: Optional[PoolWalletConfig] = pool_config_dict.get(current_state.launcher_id, None)

        if make_new_authentication_key or existing_config is None:
            new_auth_sk: PrivateKey = master_sk_to_pooling_authentication_sk(
                self.wallet_state_manager.private_key, uint32(self.wallet_id), uint32(0)
            )
            auth_pk: G1Element = new_auth_sk.get_g1()
            payout_instructions: str = (await self.standard_wallet.get_new_puzzlehash(in_transaction=True)).hex()
        else:
            auth_pk = existing_config.authentication_public_key
            payout_instructions = existing_config.payout_instructions

        new_config: PoolWalletConfig = PoolWalletConfig(
            current_state.launcher_id,
            current_state.current.pool_url if current_state.current.pool_url else "",
            payout_instructions,
            current_state.current.target_puzzle_hash,
            current_state.p2_singleton_puzzle_hash,
            current_state.current.owner_pubkey,
            auth_pk,
        )
        pool_config_dict[new_config.launcher_id] = new_config
        await update_pool_config(self.wallet_state_manager.root_path, list(pool_config_dict.values()))

    @staticmethod
    def get_next_interesting_coin_ids(spend: CoinSpend) -> List[bytes32]:
        # CoinSpend of one of the coins that we cared about. This coin was spent in a block, but might be in a reorg
        # If we return a value, it is a coin ID that we are also interested in (to support two transitions per block)
        coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(spend)
        if coin is not None:
            return [coin.name()]
        return []

    async def apply_state_transitions(self, block_spends: List[CoinSpend], block_height: uint32):
        """
        Updates the Pool state (including DB) with new singleton spends. The block spends can contain many spends
        that we are not interested in, and can contain many ephemeral spends. They must all be in the same block.
        The DB must be committed after calling this method. All validation should be done here.
        """
        coin_name_to_spend: Dict[bytes32, CoinSpend] = {cs.coin.name(): cs for cs in block_spends}

        tip: Tuple[uint32, CoinSpend] = await self.get_tip()
        tip_height = tip[0]
        tip_spend = tip[1]
        assert block_height >= tip_height  # We should not have a spend with a lesser block height

        while True:
            tip_coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(tip_spend)
            assert tip_coin is not None
            spent_coin_name: bytes32 = tip_coin.name()
            if spent_coin_name not in coin_name_to_spend:
                break
            spend: CoinSpend = coin_name_to_spend[spent_coin_name]
            await self.wallet_state_manager.pool_store.add_spend(self.wallet_id, spend, block_height)
            tip_spend = (await self.get_tip())[1]
            self.log.info(f"New PoolWallet singleton tip_coin: {tip_spend}")
            coin_name_to_spend.pop(spent_coin_name)

            # If we have reached the target state, resets it to None. Loops back to get current state
            for _, added_spend in reversed(self.wallet_state_manager.pool_store.get_spends_for_wallet(self.wallet_id)):
                latest_state: Optional[PoolState] = solution_to_pool_state(added_spend)
                if latest_state is not None:
                    if self.target_state == latest_state:
                        self.target_state = None
                        self.next_transaction_fee = uint64(0)
                    break
        await self.update_pool_config(False)

    async def rewind(self, block_height: int) -> bool:
        """
        Rolls back all transactions after block_height, and if creation was after block_height, deletes the wallet.
        Returns True if the wallet should be removed.
        """
        try:
            history: List[Tuple[uint32, CoinSpend]] = self.wallet_state_manager.pool_store.get_spends_for_wallet(
                self.wallet_id
            ).copy()
            prev_state: PoolWalletInfo = await self.get_current_state()
            await self.wallet_state_manager.pool_store.rollback(block_height, self.wallet_id)

            if len(history) > 0 and history[0][0] > block_height:
                # If we have no entries in the DB, we have no singleton, so we should not have a wallet either
                # The PoolWallet object becomes invalid after this.
                await self.wallet_state_manager.interested_store.remove_interested_puzzle_hash(
                    prev_state.p2_singleton_puzzle_hash, in_transaction=True
                )
                return True
            else:
                if await self.get_current_state() != prev_state:
                    await self.update_pool_config(False)
                return False
        except Exception as e:
            self.log.error(f"Exception rewinding: {e}")
            return False

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        launcher_coin_id: bytes32,
        block_spends: List[CoinSpend],
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
        self.next_transaction_fee = uint64(0)
        self.log = logging.getLogger(name if name else __name__)

        launcher_spend: Optional[CoinSpend] = None
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
        self.wallet_state_manager.set_new_peak_callback(self.wallet_id, self.new_peak)
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
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager.set_new_peak_callback(self.wallet_id, self.new_peak)
        return self

    @staticmethod
    async def create_new_pool_wallet_transaction(
        wallet_state_manager: Any,
        main_wallet: Wallet,
        initial_target_state: PoolState,
        fee: uint64 = uint64(0),
        p2_singleton_delay_time: Optional[uint64] = None,
        p2_singleton_delayed_ph: Optional[bytes32] = None,
    ) -> Tuple[TransactionRecord, bytes32, bytes32]:
        """
        A "plot NFT", or pool wallet, represents the idea of a set of plots that all pay to
        the same pooling puzzle. This puzzle is a `sit singleton` that is
        parameterized with a public key controlled by the user's wallet
        (a `smart coin`). It contains an inner puzzle that can switch between
        paying block rewards to a pool, or to a user's own wallet.

        Call under the wallet state manger lock
        """
        amount = 1
        standard_wallet = main_wallet

        if p2_singleton_delayed_ph is None:
            p2_singleton_delayed_ph = await main_wallet.get_new_puzzlehash()
        if p2_singleton_delay_time is None:
            p2_singleton_delay_time = uint64(604800)

        unspent_records = await wallet_state_manager.coin_store.get_unspent_coins_for_wallet(standard_wallet.wallet_id)
        balance = await standard_wallet.get_confirmed_balance(unspent_records)
        if balance < PoolWallet.MINIMUM_INITIAL_BALANCE:
            raise ValueError("Not enough balance in main wallet to create a managed plotting pool.")
        if balance < fee:
            raise ValueError("Not enough balance in main wallet to create a managed plotting pool with fee {fee}.")

        # Verify Parameters - raise if invalid
        PoolWallet._verify_initial_target_state(initial_target_state)

        spend_bundle, singleton_puzzle_hash, launcher_coin_id = await PoolWallet.generate_launcher_spend(
            standard_wallet,
            uint64(1),
            initial_target_state,
            wallet_state_manager.constants.GENESIS_CHALLENGE,
            p2_singleton_delay_time,
            p2_singleton_delayed_ph,
        )

        if spend_bundle is None:
            raise ValueError("failed to generate ID for wallet")

        standard_wallet_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=singleton_puzzle_hash,
            amount=uint64(amount),
            fee_amount=fee,
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
        p2_singleton_puzzle_hash: bytes32 = launcher_id_to_p2_puzzle_hash(
            launcher_coin_id, p2_singleton_delay_time, p2_singleton_delayed_ph
        )
        return standard_wallet_record, p2_singleton_puzzle_hash, launcher_coin_id

    async def sign(self, coin_spend: CoinSpend) -> SpendBundle:
        async def pk_to_sk(pk: G1Element) -> PrivateKey:
            owner_sk: Optional[PrivateKey] = await find_owner_sk([self.wallet_state_manager.private_key], pk)
            assert owner_sk is not None
            return owner_sk

        return await sign_coin_spends(
            [coin_spend],
            pk_to_sk,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )

    async def generate_travel_transaction(self, fee: uint64) -> TransactionRecord:
        # target_state is contained within pool_wallet_state
        pool_wallet_info: PoolWalletInfo = await self.get_current_state()

        spend_history = await self.get_spend_history()
        last_coin_spend: CoinSpend = spend_history[-1][1]
        delayed_seconds, delayed_puzhash = get_delayed_puz_info_from_launcher_spend(spend_history[0][1])
        assert pool_wallet_info.target is not None
        next_state = pool_wallet_info.target
        if pool_wallet_info.current.state in [FARMING_TO_POOL]:
            next_state = create_pool_state(
                LEAVING_POOL,
                pool_wallet_info.current.target_puzzle_hash,
                pool_wallet_info.current.owner_pubkey,
                pool_wallet_info.current.pool_url,
                pool_wallet_info.current.relative_lock_height,
            )

        new_inner_puzzle = pool_state_to_inner_puzzle(
            next_state,
            pool_wallet_info.launcher_coin.name(),
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            delayed_seconds,
            delayed_puzhash,
        )
        new_full_puzzle: SerializedProgram = SerializedProgram.from_program(
            create_full_puzzle(new_inner_puzzle, pool_wallet_info.launcher_coin.name())
        )

        outgoing_coin_spend, inner_puzzle = create_travel_spend(
            last_coin_spend,
            pool_wallet_info.launcher_coin,
            pool_wallet_info.current,
            next_state,
            self.wallet_state_manager.constants.GENESIS_CHALLENGE,
            delayed_seconds,
            delayed_puzhash,
        )

        tip = (await self.get_tip())[1]
        tip_coin = tip.coin
        singleton = tip.additions()[0]
        singleton_id = singleton.name()
        assert outgoing_coin_spend.coin.parent_coin_info == tip_coin.name()
        assert outgoing_coin_spend.coin.name() == singleton_id
        assert new_inner_puzzle != inner_puzzle
        if is_pool_member_inner_puzzle(inner_puzzle):
            (
                inner_f,
                target_puzzle_hash,
                p2_singleton_hash,
                pubkey_as_program,
                pool_reward_prefix,
                escape_puzzle_hash,
            ) = uncurry_pool_member_inner_puzzle(inner_puzzle)
            pk_bytes: bytes = bytes(pubkey_as_program.as_atom())
            assert len(pk_bytes) == 48
            owner_pubkey = G1Element.from_bytes(pk_bytes)
            assert owner_pubkey == pool_wallet_info.current.owner_pubkey
        elif is_pool_waitingroom_inner_puzzle(inner_puzzle):
            (
                target_puzzle_hash,  # payout_puzzle_hash
                relative_lock_height,
                owner_pubkey,
                p2_singleton_hash,
            ) = uncurry_pool_waitingroom_inner_puzzle(inner_puzzle)
            pk_bytes = bytes(owner_pubkey.as_atom())
            assert len(pk_bytes) == 48
            assert owner_pubkey == pool_wallet_info.current.owner_pubkey
        else:
            raise RuntimeError("Invalid state")

        signed_spend_bundle = await self.sign(outgoing_coin_spend)

        assert signed_spend_bundle.removals()[0].puzzle_hash == singleton.puzzle_hash
        assert signed_spend_bundle.removals()[0].name() == singleton.name()
        assert signed_spend_bundle is not None

        tx_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=new_full_puzzle.get_tree_hash(),
            amount=uint64(1),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=signed_spend_bundle,
            additions=signed_spend_bundle.additions(),
            removals=signed_spend_bundle.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=signed_spend_bundle.name(),
        )
        return tx_record

    @staticmethod
    async def generate_launcher_spend(
        standard_wallet: Wallet,
        amount: uint64,
        initial_target_state: PoolState,
        genesis_challenge: bytes32,
        delay_time: uint64,
        delay_ph: bytes32,
    ) -> Tuple[SpendBundle, bytes32, bytes32]:
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

        escaping_inner_puzzle: bytes32 = create_waiting_room_inner_puzzle(
            initial_target_state.target_puzzle_hash,
            initial_target_state.relative_lock_height,
            initial_target_state.owner_pubkey,
            launcher_coin.name(),
            genesis_challenge,
            delay_time,
            delay_ph,
        )
        escaping_inner_puzzle_hash = escaping_inner_puzzle.get_tree_hash()

        self_pooling_inner_puzzle: Program = create_pooling_inner_puzzle(
            initial_target_state.target_puzzle_hash,
            escaping_inner_puzzle_hash,
            initial_target_state.owner_pubkey,
            launcher_coin.name(),
            genesis_challenge,
            delay_time,
            delay_ph,
        )

        if initial_target_state.state == SELF_POOLING:
            puzzle = escaping_inner_puzzle
        elif initial_target_state.state == FARMING_TO_POOL:
            puzzle = self_pooling_inner_puzzle
        else:
            raise ValueError("Invalid initial state")
        full_pooling_puzzle: Program = create_full_puzzle(puzzle, launcher_id=launcher_coin.name())

        puzzle_hash: bytes32 = full_pooling_puzzle.get_tree_hash()
        pool_state_bytes = Program.to([("p", bytes(initial_target_state)), ("t", delay_time), ("h", delay_ph)])
        announcement_set: Set[bytes32] = set()
        announcement_message = Program.to([puzzle_hash, amount, pool_state_bytes]).get_tree_hash()
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

        genesis_launcher_solution: Program = Program.to([puzzle_hash, amount, pool_state_bytes])

        launcher_cs: CoinSpend = CoinSpend(
            launcher_coin,
            SerializedProgram.from_program(genesis_launcher_puz),
            SerializedProgram.from_program(genesis_launcher_solution),
        )
        launcher_sb: SpendBundle = SpendBundle([launcher_cs], G2Element())

        # Current inner will be updated when state is verified on the blockchain
        full_spend: SpendBundle = SpendBundle.aggregate([create_launcher_tx_record.spend_bundle, launcher_sb])
        return full_spend, puzzle_hash, launcher_coin.name()

    async def join_pool(self, target_state: PoolState, fee: uint64) -> Tuple[uint64, TransactionRecord]:
        if target_state.state != FARMING_TO_POOL:
            raise ValueError(f"join_pool must be called with target_state={FARMING_TO_POOL} (FARMING_TO_POOL)")
        if self.target_state is not None:
            raise ValueError(f"Cannot join a pool while waiting for target state: {self.target_state}")
        if await self.have_unconfirmed_transaction():
            raise ValueError(
                "Cannot join pool due to unconfirmed transaction. If this is stuck, delete the unconfirmed transaction."
            )

        current_state: PoolWalletInfo = await self.get_current_state()

        total_fee = fee
        if current_state.current == target_state:
            self.target_state = None
            msg = f"Asked to change to current state. Target = {target_state}"
            self.log.info(msg)
            raise ValueError(msg)
        elif current_state.current.state in [SELF_POOLING, LEAVING_POOL]:
            total_fee = fee
        elif current_state.current.state == FARMING_TO_POOL:
            total_fee = uint64(fee * 2)

        if self.target_state is not None:
            raise ValueError(
                f"Cannot change to state {target_state} when already having target state: {self.target_state}"
            )
        PoolWallet._verify_initial_target_state(target_state)
        if current_state.current.state == LEAVING_POOL:
            history: List[Tuple[uint32, CoinSpend]] = await self.get_spend_history()
            last_height: uint32 = history[-1][0]
            if self.wallet_state_manager.get_peak().height <= last_height + current_state.current.relative_lock_height:
                raise ValueError(
                    f"Cannot join a pool until height {last_height + current_state.current.relative_lock_height}"
                )

        self.target_state = target_state
        self.next_transaction_fee = fee
        tx_record: TransactionRecord = await self.generate_travel_transaction(fee)
        await self.wallet_state_manager.add_pending_transaction(tx_record)

        return total_fee, tx_record

    async def self_pool(self, fee: uint64) -> Tuple[uint64, TransactionRecord]:
        if await self.have_unconfirmed_transaction():
            raise ValueError(
                "Cannot self pool due to unconfirmed transaction. If this is stuck, delete the unconfirmed transaction."
            )
        pool_wallet_info: PoolWalletInfo = await self.get_current_state()
        if pool_wallet_info.current.state == SELF_POOLING:
            raise ValueError("Attempted to self pool when already self pooling")

        if self.target_state is not None:
            raise ValueError(f"Cannot self pool when already having target state: {self.target_state}")

        # Note the implications of getting owner_puzzlehash from our local wallet right now
        # vs. having pre-arranged the target self-pooling address
        owner_puzzlehash = await self.standard_wallet.get_new_puzzlehash()
        owner_pubkey = pool_wallet_info.current.owner_pubkey
        current_state: PoolWalletInfo = await self.get_current_state()
        total_fee = uint64(fee * 2)

        if current_state.current.state == LEAVING_POOL:
            total_fee = fee
            history: List[Tuple[uint32, CoinSpend]] = await self.get_spend_history()
            last_height: uint32 = history[-1][0]
            if self.wallet_state_manager.get_peak().height <= last_height + current_state.current.relative_lock_height:
                raise ValueError(
                    f"Cannot self pool until height {last_height + current_state.current.relative_lock_height}"
                )
        self.target_state = create_pool_state(
            SELF_POOLING, owner_puzzlehash, owner_pubkey, pool_url=None, relative_lock_height=uint32(0)
        )
        self.next_transaction_fee = fee
        tx_record = await self.generate_travel_transaction(fee)
        await self.wallet_state_manager.add_pending_transaction(tx_record)
        return total_fee, tx_record

    async def claim_pool_rewards(self, fee: uint64) -> TransactionRecord:
        # Search for p2_puzzle_hash coins, and spend them with the singleton
        if await self.have_unconfirmed_transaction():
            raise ValueError(
                "Cannot claim due to unconfirmed transaction. If this is stuck, delete the unconfirmed transaction."
            )

        unspent_coin_records: List[CoinRecord] = list(
            await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.wallet_id)
        )

        if len(unspent_coin_records) == 0:
            raise ValueError("Nothing to claim, no transactions to p2_singleton_puzzle_hash")
        farming_rewards: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_farming_rewards()
        coin_to_height_farmed: Dict[Coin, uint32] = {}
        for tx_record in farming_rewards:
            height_farmed: Optional[uint32] = tx_record.height_farmed(
                self.wallet_state_manager.constants.GENESIS_CHALLENGE
            )
            assert height_farmed is not None
            coin_to_height_farmed[tx_record.additions[0]] = height_farmed
        history: List[Tuple[uint32, CoinSpend]] = await self.get_spend_history()
        assert len(history) > 0
        delayed_seconds, delayed_puzhash = get_delayed_puz_info_from_launcher_spend(history[0][1])
        current_state: PoolWalletInfo = await self.get_current_state()
        last_solution: CoinSpend = history[-1][1]

        all_spends: List[CoinSpend] = []
        total_amount = 0
        for coin_record in unspent_coin_records:
            if coin_record.coin not in coin_to_height_farmed:
                continue
            if len(all_spends) >= 100:
                # Limit the total number of spends, so it fits into the block
                break
            absorb_spend: List[CoinSpend] = create_absorb_spend(
                last_solution,
                current_state.current,
                current_state.launcher_coin,
                coin_to_height_farmed[coin_record.coin],
                self.wallet_state_manager.constants.GENESIS_CHALLENGE,
                delayed_seconds,
                delayed_puzhash,
            )
            last_solution = absorb_spend[0]
            all_spends += absorb_spend
            total_amount += coin_record.coin.amount
            self.log.info(
                f"Farmer coin: {coin_record.coin} {coin_record.coin.name()} {coin_to_height_farmed[coin_record.coin]}"
            )
        if len(all_spends) == 0:
            raise ValueError("Nothing to claim, no unspent coinbase rewards")

        # No signatures are required to absorb
        spend_bundle: SpendBundle = SpendBundle(all_spends, G2Element())

        absorb_transaction: TransactionRecord = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=current_state.current.target_puzzle_hash,
            amount=uint64(total_amount),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=uint32(self.wallet_id),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
        )
        await self.wallet_state_manager.add_pending_transaction(absorb_transaction)
        return absorb_transaction

    async def new_peak(self, peak: BlockRecord) -> None:
        # This gets called from the WalletStateManager whenever there is a new peak

        pool_wallet_info: PoolWalletInfo = await self.get_current_state()
        tip_height, tip_spend = await self.get_tip()

        if self.target_state is None:
            return
        if self.target_state == pool_wallet_info.current.state:
            self.target_state = None
            raise ValueError("Internal error")

        if (
            self.target_state.state in [FARMING_TO_POOL, SELF_POOLING]
            and pool_wallet_info.current.state == LEAVING_POOL
        ):
            leave_height = tip_height + pool_wallet_info.current.relative_lock_height

            curr: BlockRecord = peak
            while not curr.is_transaction_block:
                curr = self.wallet_state_manager.blockchain.block_record(curr.prev_hash)

            self.log.info(f"Last transaction block height: {curr.height} OK to leave at height {leave_height}")

            # Add some buffer (+2) to reduce chances of a reorg
            if curr.height > leave_height + 2:
                unconfirmed: List[
                    TransactionRecord
                ] = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(self.wallet_id)
                next_tip: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(tip_spend)
                assert next_tip is not None

                if any([rem.name() == next_tip.name() for tx_rec in unconfirmed for rem in tx_rec.removals]):
                    self.log.info("Already submitted second transaction, will not resubmit.")
                    return

                self.log.info(f"Attempting to leave from\n{pool_wallet_info.current}\nto\n{self.target_state}")
                assert self.target_state.version == POOL_PROTOCOL_VERSION
                assert pool_wallet_info.current.state == LEAVING_POOL
                assert self.target_state.target_puzzle_hash is not None

                if self.target_state.state == SELF_POOLING:
                    assert self.target_state.relative_lock_height == 0
                    assert self.target_state.pool_url is None
                elif self.target_state.state == FARMING_TO_POOL:
                    assert self.target_state.relative_lock_height >= self.MINIMUM_RELATIVE_LOCK_HEIGHT
                    assert self.target_state.pool_url is not None

                tx_record = await self.generate_travel_transaction(self.next_transaction_fee)
                await self.wallet_state_manager.add_pending_transaction(tx_record)

    async def have_unconfirmed_transaction(self) -> bool:
        unconfirmed: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
            self.wallet_id
        )
        return len(unconfirmed) > 0

    async def get_confirmed_balance(self, _=None) -> uint64:
        amount: uint64 = uint64(0)
        if (await self.get_current_state()).current.state == SELF_POOLING:
            unspent_coin_records: List[WalletCoinRecord] = list(
                await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.wallet_id)
            )
            for record in unspent_coin_records:
                if record.coinbase:
                    amount = uint64(amount + record.coin.amount)
        return amount

    async def get_unconfirmed_balance(self, record_list=None) -> uint64:
        return await self.get_confirmed_balance(record_list)

    async def get_spendable_balance(self, record_list=None) -> uint64:
        return await self.get_confirmed_balance(record_list)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def get_max_send_amount(self, record_list=None) -> uint64:
        return uint64(0)
