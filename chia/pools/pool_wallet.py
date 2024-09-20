from __future__ import annotations

import dataclasses
import logging
import time
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Set, Tuple, cast

from chia_rs import G1Element, G2Element, PrivateKey
from typing_extensions import final

from chia.pools.pool_config import PoolWalletConfig, load_pool_config, update_pool_config
from chia.pools.pool_puzzles import (
    SINGLETON_LAUNCHER,
    create_absorb_spend,
    create_full_puzzle,
    create_pooling_inner_puzzle,
    create_travel_spend,
    create_waiting_room_inner_puzzle,
    get_delayed_puz_info_from_launcher_spend,
    get_most_recent_singleton_coin_from_coin_spend,
    is_pool_member_inner_puzzle,
    is_pool_waitingroom_inner_puzzle,
    launcher_id_to_p2_puzzle_hash,
    pool_state_to_inner_puzzle,
    solution_to_pool_state,
    uncurry_pool_member_inner_puzzle,
    uncurry_pool_waitingroom_inner_puzzle,
)
from chia.pools.pool_wallet_info import (
    FARMING_TO_POOL,
    LEAVING_POOL,
    SELF_POOLING,
    PoolSingletonState,
    PoolState,
    PoolWalletInfo,
    create_pool_state,
)
from chia.protocols.pool_protocol import POOL_PROTOCOL_VERSION
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, compute_additions
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.conditions import AssertCoinAnnouncement, Condition, ConditionValidTimes
from chia.wallet.derive_keys import find_owner_sk
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, TXConfig
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager


@final
@dataclasses.dataclass
class PoolWallet:
    if TYPE_CHECKING:
        from chia.wallet.wallet_protocol import WalletProtocol

        _protocol_check: ClassVar[WalletProtocol[object]] = cast("PoolWallet", None)

    MINIMUM_INITIAL_BALANCE = 1
    MINIMUM_RELATIVE_LOCK_HEIGHT = 5
    MAXIMUM_RELATIVE_LOCK_HEIGHT = 1000
    DEFAULT_MAX_CLAIM_SPENDS = 100

    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_info: WalletInfo
    standard_wallet: Wallet
    wallet_id: int
    next_transaction_fee: uint64 = uint64(0)
    next_tx_config: TXConfig = DEFAULT_TX_CONFIG
    target_state: Optional[PoolState] = None
    _owner_sk_and_index: Optional[Tuple[PrivateKey, uint32]] = None

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
    def type(cls) -> WalletType:
        return WalletType.POOLING_WALLET

    def id(self) -> uint32:
        return self.wallet_info.id

    @classmethod
    def _verify_self_pooled(cls, state: PoolState) -> Optional[str]:
        err = ""
        if state.pool_url not in [None, ""]:
            err += " Unneeded pool_url for self-pooling"

        if state.relative_lock_height != 0:
            err += " Incorrect relative_lock_height for self-pooling"

        return None if err == "" else err

    @classmethod
    def _verify_pooling_state(cls, state: PoolState) -> Optional[str]:
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

        if state.state == PoolSingletonState.SELF_POOLING.value:
            return cls._verify_self_pooled(state)
        elif (
            state.state == PoolSingletonState.FARMING_TO_POOL.value
            or state.state == PoolSingletonState.LEAVING_POOL.value
        ):
            return cls._verify_pooling_state(state)
        else:
            return "Internal Error"

    @classmethod
    def _verify_initial_target_state(cls, initial_target_state: PoolState) -> None:
        err = cls._verify_pool_state(initial_target_state)
        if err:
            raise ValueError(f"Invalid internal Pool State: {err}: {initial_target_state}")

    async def get_spend_history(self) -> List[Tuple[uint32, CoinSpend]]:
        return await self.wallet_state_manager.pool_store.get_spends_for_wallet(self.wallet_id)

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
        return PoolWalletInfo(
            pool_state,
            self.target_state,
            launcher_coin,
            launcher_id,
            p2_singleton_puzzle_hash,
            tip_singleton_coin.name(),
            last_singleton_spend_height,
        )

    async def get_unconfirmed_transactions(self) -> List[TransactionRecord]:
        return await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(self.wallet_id)

    async def get_tip(self) -> Tuple[uint32, CoinSpend]:
        return (await self.wallet_state_manager.pool_store.get_spends_for_wallet(self.wallet_id))[-1]

    async def update_pool_config(self) -> None:
        current_state: PoolWalletInfo = await self.get_current_state()
        pool_config_list: List[PoolWalletConfig] = load_pool_config(self.wallet_state_manager.root_path)
        pool_config_dict: Dict[bytes32, PoolWalletConfig] = {c.launcher_id: c for c in pool_config_list}
        existing_config: Optional[PoolWalletConfig] = pool_config_dict.get(current_state.launcher_id, None)
        payout_instructions: str = existing_config.payout_instructions if existing_config is not None else ""

        if len(payout_instructions) == 0:
            payout_instructions = (await self.standard_wallet.get_new_puzzlehash()).hex()
            self.log.info(f"New config entry. Generated payout_instructions puzzle hash: {payout_instructions}")

        new_config: PoolWalletConfig = PoolWalletConfig(
            current_state.launcher_id,
            current_state.current.pool_url if current_state.current.pool_url else "",
            payout_instructions,
            current_state.current.target_puzzle_hash,
            current_state.p2_singleton_puzzle_hash,
            current_state.current.owner_pubkey,
        )
        pool_config_dict[new_config.launcher_id] = new_config
        await update_pool_config(self.wallet_state_manager.root_path, list(pool_config_dict.values()))

    async def apply_state_transition(self, new_state: CoinSpend, block_height: uint32) -> bool:
        """
        Updates the Pool state (including DB) with new singleton spends.
        The DB must be committed after calling this method. All validation should be done here. Returns True iff
        the spend is a valid transition spend for the singleton, False otherwise.
        """
        tip: Tuple[uint32, CoinSpend] = await self.get_tip()
        tip_spend = tip[1]

        tip_coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(tip_spend)
        assert tip_coin is not None
        spent_coin_name: bytes32 = tip_coin.name()

        if spent_coin_name != new_state.coin.name():
            history: List[Tuple[uint32, CoinSpend]] = await self.get_spend_history()
            if new_state.coin.name() in [sp.coin.name() for _, sp in history]:
                self.log.info(f"Already have state transition: {new_state.coin.name().hex()}")
            else:
                self.log.warning(
                    f"Failed to apply state transition. tip: {tip_coin} new_state: {new_state} height {block_height}"
                )
            return False

        await self.wallet_state_manager.pool_store.add_spend(self.wallet_id, new_state, block_height)
        tip_spend = (await self.get_tip())[1]
        self.log.info(f"New PoolWallet singleton tip_coin: {tip_spend} farmed at height {block_height}")

        # If we have reached the target state, resets it to None. Loops back to get current state
        for _, added_spend in reversed(
            await self.wallet_state_manager.pool_store.get_spends_for_wallet(self.wallet_id)
        ):
            latest_state: Optional[PoolState] = solution_to_pool_state(added_spend)
            if latest_state is not None:
                if self.target_state == latest_state:
                    self.target_state = None
                    self.next_transaction_fee = uint64(0)
                    self.next_tx_config = DEFAULT_TX_CONFIG
                break

        await self.update_pool_config()
        return True

    async def rewind(self, block_height: int) -> bool:
        """
        Rolls back all transactions after block_height, and if creation was after block_height, deletes the wallet.
        Returns True if the wallet should be removed.
        """
        try:
            history: List[Tuple[uint32, CoinSpend]] = await self.wallet_state_manager.pool_store.get_spends_for_wallet(
                self.wallet_id
            )
            prev_state: PoolWalletInfo = await self.get_current_state()
            await self.wallet_state_manager.pool_store.rollback(block_height, self.wallet_id)

            if len(history) > 0 and history[0][0] > block_height:
                return True
            else:
                if await self.get_current_state() != prev_state:
                    await self.update_pool_config()
                return False
        except Exception as e:
            self.log.error(f"Exception rewinding: {e}")
            return False

    @classmethod
    async def create(
        cls,
        wallet_state_manager: Any,
        wallet: Wallet,
        launcher_coin_id: bytes32,
        block_spends: List[CoinSpend],
        block_height: uint32,
        *,
        name: Optional[str] = None,
    ) -> PoolWallet:
        """
        This creates a new PoolWallet with only one spend: the launcher spend. The DB MUST be committed after calling
        this method.
        """
        wallet_info = await wallet_state_manager.user_store.create_wallet(
            "Pool wallet", WalletType.POOLING_WALLET.value, ""
        )

        pool_wallet = cls(
            wallet_state_manager=wallet_state_manager,
            log=logging.getLogger(name if name else __name__),
            wallet_info=wallet_info,
            wallet_id=wallet_info.id,
            standard_wallet=wallet,
        )

        launcher_spend: Optional[CoinSpend] = None
        for spend in block_spends:
            if spend.coin.name() == launcher_coin_id:
                launcher_spend = spend
        assert launcher_spend is not None
        await wallet_state_manager.pool_store.add_spend(pool_wallet.wallet_id, launcher_spend, block_height)
        await pool_wallet.update_pool_config()

        p2_puzzle_hash: bytes32 = (await pool_wallet.get_current_state()).p2_singleton_puzzle_hash
        await wallet_state_manager.add_new_wallet(pool_wallet)
        await wallet_state_manager.add_interested_puzzle_hashes([p2_puzzle_hash], [pool_wallet.wallet_id])

        return pool_wallet

    @classmethod
    async def create_from_db(
        cls,
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: Optional[str] = None,
    ) -> PoolWallet:
        """
        This creates a PoolWallet from DB. However, all data is already handled by WalletPoolStore, so we don't need
        to do anything here.
        """
        pool_wallet = cls(
            wallet_state_manager=wallet_state_manager,
            log=logging.getLogger(name if name else __name__),
            wallet_info=wallet_info,
            wallet_id=wallet_info.id,
            standard_wallet=wallet,
        )
        return pool_wallet

    @staticmethod
    async def create_new_pool_wallet_transaction(
        wallet_state_manager: Any,
        main_wallet: Wallet,
        initial_target_state: PoolState,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        p2_singleton_delay_time: Optional[uint64] = None,
        p2_singleton_delayed_ph: Optional[bytes32] = None,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> Tuple[bytes32, bytes32]:
        """
        A "plot NFT", or pool wallet, represents the idea of a set of plots that all pay to
        the same pooling puzzle. This puzzle is a `chia singleton` that is
        parameterized with a public key controlled by the user's wallet
        (a `smart coin`). It contains an inner puzzle that can switch between
        paying block rewards to a pool, or to a user's own wallet.

        Call under the wallet state manager lock
        """
        standard_wallet = main_wallet

        if p2_singleton_delayed_ph is None:
            p2_singleton_delayed_ph = await main_wallet.get_new_puzzlehash()
        if p2_singleton_delay_time is None:
            p2_singleton_delay_time = uint64(604800)

        unspent_records = await wallet_state_manager.coin_store.get_unspent_coins_for_wallet(standard_wallet.wallet_id)
        balance = await standard_wallet.get_confirmed_balance(unspent_records)
        if balance < PoolWallet.MINIMUM_INITIAL_BALANCE:
            raise ValueError("Not enough balance in main wallet to create a managed plotting pool.")
        if balance < PoolWallet.MINIMUM_INITIAL_BALANCE + fee:
            raise ValueError("Not enough balance in main wallet to create a managed plotting pool with fee {fee}.")

        # Verify Parameters - raise if invalid
        PoolWallet._verify_initial_target_state(initial_target_state)

        singleton_puzzle_hash, launcher_coin_id = await PoolWallet.generate_launcher_spend(
            standard_wallet,
            uint64(1),
            fee,
            initial_target_state,
            wallet_state_manager.constants.GENESIS_CHALLENGE,
            p2_singleton_delay_time,
            p2_singleton_delayed_ph,
            action_scope,
            extra_conditions=extra_conditions,
        )

        p2_singleton_puzzle_hash: bytes32 = launcher_id_to_p2_puzzle_hash(
            launcher_coin_id, p2_singleton_delay_time, p2_singleton_delayed_ph
        )

        return p2_singleton_puzzle_hash, launcher_coin_id

    async def _get_owner_key_cache(self) -> Tuple[PrivateKey, uint32]:
        if self._owner_sk_and_index is None:
            self._owner_sk_and_index = find_owner_sk(
                [self.wallet_state_manager.get_master_private_key()],
                (await self.get_current_state()).current.owner_pubkey,
            )
        assert self._owner_sk_and_index is not None
        return self._owner_sk_and_index

    async def get_pool_wallet_index(self) -> uint32:
        return (await self._get_owner_key_cache())[1]

    async def generate_fee_transaction(
        self,
        fee: uint64,
        action_scope: WalletActionScope,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        await self.standard_wallet.generate_signed_transaction(
            uint64(0),
            (await self.standard_wallet.get_new_puzzlehash()),
            action_scope,
            fee=fee,
            origin_id=None,
            coins=None,
            primaries=None,
            extra_conditions=extra_conditions,
        )

    async def generate_travel_transactions(self, fee: uint64, action_scope: WalletActionScope) -> None:
        # target_state is contained within pool_wallet_state
        pool_wallet_info: PoolWalletInfo = await self.get_current_state()

        spend_history = await self.get_spend_history()
        last_coin_spend: CoinSpend = spend_history[-1][1]
        delayed_seconds, delayed_puzhash = get_delayed_puz_info_from_launcher_spend(spend_history[0][1])
        assert pool_wallet_info.target is not None
        next_state = pool_wallet_info.target
        if pool_wallet_info.current.state == FARMING_TO_POOL.value:
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
        singleton = compute_additions(tip)[0]
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
        elif is_pool_waitingroom_inner_puzzle(inner_puzzle):
            (
                target_puzzle_hash,  # payout_puzzle_hash
                relative_lock_height,
                pubkey_as_program,
                p2_singleton_hash,
            ) = uncurry_pool_waitingroom_inner_puzzle(inner_puzzle)
        else:
            raise RuntimeError("Invalid state")

        unsigned_spend_bundle = WalletSpendBundle([outgoing_coin_spend], G2Element())
        assert unsigned_spend_bundle.removals()[0].puzzle_hash == singleton.puzzle_hash
        assert unsigned_spend_bundle.removals()[0].name() == singleton.name()
        if fee > 0:
            await self.generate_fee_transaction(fee, action_scope)

        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(
                TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=new_full_puzzle.get_tree_hash(),
                    amount=uint64(1),
                    fee_amount=fee,
                    confirmed=False,
                    sent=uint32(0),
                    spend_bundle=unsigned_spend_bundle,
                    additions=unsigned_spend_bundle.additions(),
                    removals=unsigned_spend_bundle.removals(),
                    wallet_id=self.id(),
                    sent_to=[],
                    trade_id=None,
                    memos=[],
                    type=uint32(TransactionType.OUTGOING_TX.value),
                    name=unsigned_spend_bundle.name(),
                    valid_times=ConditionValidTimes(),
                )
            )

    @staticmethod
    async def generate_launcher_spend(
        standard_wallet: Wallet,
        amount: uint64,
        fee: uint64,
        initial_target_state: PoolState,
        genesis_challenge: bytes32,
        delay_time: uint64,
        delay_ph: bytes32,
        action_scope: WalletActionScope,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> Tuple[bytes32, bytes32]:
        """
        Creates the initial singleton, which includes spending an origin coin, the launcher, and creating a singleton
        with the "pooling" inner state, which can be either self pooling or using a pool
        """
        coins: Set[Coin] = await standard_wallet.select_coins(uint64(amount + fee), action_scope)
        if coins is None:
            raise ValueError("Not enough coins to create pool wallet")

        launcher_parent: Coin = coins.copy().pop()
        genesis_launcher_puz: Program = SINGLETON_LAUNCHER
        launcher_coin: Coin = Coin(launcher_parent.name(), genesis_launcher_puz.get_tree_hash(), amount)

        escaping_inner_puzzle: Program = create_waiting_room_inner_puzzle(
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

        if initial_target_state.state == SELF_POOLING.value:
            puzzle = escaping_inner_puzzle
        elif initial_target_state.state == FARMING_TO_POOL.value:
            puzzle = self_pooling_inner_puzzle
        else:
            raise ValueError("Invalid initial state")
        full_pooling_puzzle: Program = create_full_puzzle(puzzle, launcher_id=launcher_coin.name())

        puzzle_hash: bytes32 = full_pooling_puzzle.get_tree_hash()
        pool_state_bytes = Program.to([("p", bytes(initial_target_state)), ("t", delay_time), ("h", delay_ph)])
        announcement_message = Program.to([puzzle_hash, amount, pool_state_bytes]).get_tree_hash()

        genesis_launcher_solution: Program = Program.to([puzzle_hash, amount, pool_state_bytes])

        launcher_cs: CoinSpend = CoinSpend(
            launcher_coin,
            SerializedProgram.from_program(genesis_launcher_puz),
            SerializedProgram.from_program(genesis_launcher_solution),
        )
        launcher_sb = WalletSpendBundle([launcher_cs], G2Element())

        await standard_wallet.generate_signed_transaction(
            amount,
            genesis_launcher_puz.get_tree_hash(),
            action_scope,
            fee,
            coins,
            None,
            origin_id=launcher_parent.name(),
            extra_conditions=(
                *extra_conditions,
                AssertCoinAnnouncement(asserted_id=launcher_coin.name(), asserted_msg=announcement_message),
            ),
        )

        async with action_scope.use() as interface:
            interface.side_effects.extra_spends.append(launcher_sb)

        return puzzle_hash, launcher_coin.name()

    async def join_pool(self, target_state: PoolState, fee: uint64, action_scope: WalletActionScope) -> uint64:
        if target_state.state != FARMING_TO_POOL.value:
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
        elif current_state.current.state in [SELF_POOLING.value, LEAVING_POOL.value]:
            total_fee = fee
        elif current_state.current.state == FARMING_TO_POOL.value:
            total_fee = uint64(fee * 2)

        if self.target_state is not None:
            raise ValueError(
                f"Cannot change to state {target_state} when already having target state: {self.target_state}"
            )
        PoolWallet._verify_initial_target_state(target_state)
        if current_state.current.state == LEAVING_POOL.value:
            history: List[Tuple[uint32, CoinSpend]] = await self.get_spend_history()
            last_height: uint32 = history[-1][0]
            if (
                await self.wallet_state_manager.blockchain.get_finished_sync_up_to()
                <= last_height + current_state.current.relative_lock_height
            ):
                raise ValueError(
                    f"Cannot join a pool until height {last_height + current_state.current.relative_lock_height}"
                )

        self.target_state = target_state
        self.next_transaction_fee = fee
        self.next_tx_config = action_scope.config.tx_config
        await self.generate_travel_transactions(fee, action_scope)
        return total_fee

    async def self_pool(self, fee: uint64, action_scope: WalletActionScope) -> uint64:
        if await self.have_unconfirmed_transaction():
            raise ValueError(
                "Cannot self pool due to unconfirmed transaction. If this is stuck, delete the unconfirmed transaction."
            )
        pool_wallet_info: PoolWalletInfo = await self.get_current_state()
        if pool_wallet_info.current.state == SELF_POOLING.value:
            raise ValueError("Attempted to self pool when already self pooling")

        if self.target_state is not None:
            raise ValueError(f"Cannot self pool when already having target state: {self.target_state}")

        # Note the implications of getting owner_puzzlehash from our local wallet right now
        # vs. having pre-arranged the target self-pooling address
        owner_puzzlehash = await self.standard_wallet.get_new_puzzlehash()
        owner_pubkey = pool_wallet_info.current.owner_pubkey
        current_state: PoolWalletInfo = await self.get_current_state()
        total_fee = uint64(fee * 2)

        if current_state.current.state == LEAVING_POOL.value:
            total_fee = fee
            history: List[Tuple[uint32, CoinSpend]] = await self.get_spend_history()
            last_height: uint32 = history[-1][0]
            if (
                await self.wallet_state_manager.blockchain.get_finished_sync_up_to()
                <= last_height + current_state.current.relative_lock_height
            ):
                raise ValueError(
                    f"Cannot self pool until height {last_height + current_state.current.relative_lock_height}"
                )
        self.target_state = create_pool_state(
            SELF_POOLING, owner_puzzlehash, owner_pubkey, pool_url=None, relative_lock_height=uint32(0)
        )
        self.next_transaction_fee = fee
        self.next_tx_config = action_scope.config.tx_config
        await self.generate_travel_transactions(fee, action_scope)
        return total_fee

    async def claim_pool_rewards(
        self, fee: uint64, max_spends_in_tx: Optional[int], action_scope: WalletActionScope
    ) -> None:
        # Search for p2_puzzle_hash coins, and spend them with the singleton
        if await self.have_unconfirmed_transaction():
            raise ValueError(
                "Cannot claim due to unconfirmed transaction. If this is stuck, delete the unconfirmed transaction."
            )

        if max_spends_in_tx is None:
            max_spends_in_tx = self.DEFAULT_MAX_CLAIM_SPENDS
        elif max_spends_in_tx <= 0:
            self.log.info(f"Bad max_spends_in_tx value of {max_spends_in_tx}. Set to {self.DEFAULT_MAX_CLAIM_SPENDS}.")
            max_spends_in_tx = self.DEFAULT_MAX_CLAIM_SPENDS

        unspent_coin_records = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.wallet_id)
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

        # The coins being claimed are gathered into the `SpendBundle`, :absorb_spend:
        # We use an announcement in the fee spend to ensure that the claim spend is spent in the same block as the fee
        # We only need to do this for one of the coins, because each `SpendBundle` can only be spent as a unit

        first_coin_record = None
        for coin_record in unspent_coin_records:
            if coin_record.coin not in coin_to_height_farmed:
                continue
            if first_coin_record is None:
                first_coin_record = coin_record
            if len(all_spends) >= max_spends_in_tx:
                # Limit the total number of spends, so the SpendBundle fits into the block
                self.log.info(f"pool wallet truncating absorb to {max_spends_in_tx} spends to fit into block")
                print(f"pool wallet truncating absorb to {max_spends_in_tx} spends to fit into block")
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
        if len(all_spends) == 0 or first_coin_record is None:
            raise ValueError("Nothing to claim, no unspent coinbase rewards")

        claim_spend = WalletSpendBundle(all_spends, G2Element())

        # If fee is 0, no signatures are required to absorb
        if fee > 0:
            await self.generate_fee_transaction(
                fee,
                action_scope,
                extra_conditions=(
                    AssertCoinAnnouncement(asserted_id=first_coin_record.coin.name(), asserted_msg=b"$"),
                ),
            )

        current_time = uint64(int(time.time()))
        # The claim spend, minus the fee amount from the main wallet
        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(
                TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=current_time,
                    to_puzzle_hash=current_state.current.target_puzzle_hash,
                    amount=uint64(total_amount),
                    fee_amount=fee,  # This will not be double counted in self.standard_wallet
                    confirmed=False,
                    sent=uint32(0),
                    spend_bundle=claim_spend,
                    additions=claim_spend.additions(),
                    removals=claim_spend.removals(),
                    wallet_id=uint32(self.wallet_id),
                    sent_to=[],
                    memos=[],
                    trade_id=None,
                    type=uint32(TransactionType.OUTGOING_TX.value),
                    name=claim_spend.name(),
                    valid_times=ConditionValidTimes(),
                )
            )

    async def new_peak(self, peak_height: uint32) -> None:
        # This gets called from the WalletStateManager whenever there is a new peak

        pool_wallet_info: PoolWalletInfo = await self.get_current_state()
        tip_height, tip_spend = await self.get_tip()

        if self.target_state is None:
            return
        if self.target_state == pool_wallet_info.current:
            self.target_state = None
            raise ValueError(f"Internal error. Pool wallet {self.wallet_id} state: {pool_wallet_info.current}")

        if (
            self.target_state.state in [FARMING_TO_POOL.value, SELF_POOLING.value]
            and pool_wallet_info.current.state == LEAVING_POOL.value
        ):
            leave_height = tip_height + pool_wallet_info.current.relative_lock_height

            # Add some buffer (+2) to reduce chances of a reorg
            if peak_height > leave_height + 2:
                unconfirmed: List[TransactionRecord] = (
                    await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(self.wallet_id)
                )
                next_tip: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(tip_spend)
                assert next_tip is not None

                if any([rem.name() == next_tip.name() for tx_rec in unconfirmed for rem in tx_rec.removals]):
                    self.log.info("Already submitted second transaction, will not resubmit.")
                    return

                self.log.info(f"Attempting to leave from\n{pool_wallet_info.current}\nto\n{self.target_state}")
                assert self.target_state.version == POOL_PROTOCOL_VERSION
                assert pool_wallet_info.current.state == LEAVING_POOL.value
                assert self.target_state.target_puzzle_hash is not None

                if self.target_state.state == SELF_POOLING.value:
                    assert self.target_state.relative_lock_height == 0
                    assert self.target_state.pool_url is None
                elif self.target_state.state == FARMING_TO_POOL.value:
                    assert self.target_state.relative_lock_height >= self.MINIMUM_RELATIVE_LOCK_HEIGHT
                    assert self.target_state.pool_url is not None

                async with self.wallet_state_manager.new_action_scope(self.next_tx_config, push=True) as action_scope:
                    await self.generate_travel_transactions(self.next_transaction_fee, action_scope)

    async def have_unconfirmed_transaction(self) -> bool:
        unconfirmed: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
            self.wallet_id
        )
        return len(unconfirmed) > 0

    async def get_confirmed_balance(self, _: Optional[object] = None) -> uint128:
        amount: uint128 = uint128(0)
        if (await self.get_current_state()).current.state == SELF_POOLING.value:
            unspent_coin_records: List[WalletCoinRecord] = list(
                await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.wallet_id)
            )
            for record in unspent_coin_records:
                if record.coinbase:
                    amount = uint128(amount + record.coin.amount)
        return amount

    async def get_unconfirmed_balance(self, record_list: Optional[object] = None) -> uint128:
        return await self.get_confirmed_balance(record_list)

    async def get_spendable_balance(self, record_list: Optional[object] = None) -> uint128:
        return await self.get_confirmed_balance(record_list)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection, coin_data: Optional[object]) -> None:
        pass

    async def select_coins(self, amount: uint64, action_scope: WalletActionScope) -> Set[Coin]:
        raise RuntimeError("PoolWallet does not support select_coins()")

    def require_derivation_paths(self) -> bool:
        return False

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise RuntimeError("PoolWallet does not support puzzle_hash_for_pk")

    def get_name(self) -> str:
        return self.wallet_info.name

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:  # pragma: no cover
        return False  # PoolWallet pre-dates hints
