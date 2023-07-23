from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Set, Tuple, cast

from blspy import AugSchemeMPL, G1Element, G2Element
from typing_extensions import Unpack

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.coin_selection import select_coins
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.payment import Payment
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    puzzle_hash_for_pk,
    solution_for_conditions,
)
from chia.wallet.puzzles.puzzle_utils import (
    make_assert_coin_announcement,
    make_assert_puzzle_announcement,
    make_create_coin_announcement,
    make_create_coin_condition,
    make_create_puzzle_announcement,
    make_reserve_fee_condition,
)
from chia.wallet.secret_key_store import SecretKeyStore
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.puzzle_decorator import PuzzleDecoratorManager
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import GSTOptionalArgs, WalletProtocol

if TYPE_CHECKING:
    from chia.server.ws_connection import WSChiaConnection
    from chia.wallet.wallet_state_manager import WalletStateManager

# https://github.com/Chia-Network/chips/blob/80e4611fe52b174bf1a0382b9dff73805b18b8c6/CHIPs/chip-0002.md#signmessage
CHIP_0002_SIGN_MESSAGE_PREFIX = "Chia Signed Message"


class Wallet:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[WalletProtocol] = cast("Wallet", None)

    wallet_info: WalletInfo
    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_id: uint32
    secret_key_store: SecretKeyStore
    cost_of_single_tx: Optional[int]

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = __name__,
    ) -> Wallet:
        self = Wallet()
        self.log = logging.getLogger(name)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_id = info.id
        self.secret_key_store = SecretKeyStore()
        self.cost_of_single_tx = None
        return self

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        spendable: List[WalletCoinRecord] = list(
            await self.wallet_state_manager.get_spendable_coins_for_wallet(self.id(), records)
        )
        if len(spendable) == 0:
            return uint128(0)
        spendable.sort(reverse=True, key=lambda record: record.coin.amount)
        if self.cost_of_single_tx is None:
            coin = spendable[0].coin
            tx = await self.generate_signed_transaction(
                uint64(coin.amount), coin.puzzle_hash, coins={coin}, ignore_max_send_amount=True
            )
            assert tx.spend_bundle is not None
            program: BlockGenerator = simple_solution_generator(tx.spend_bundle)
            # npc contains names of the coins removed, puzzle_hashes and their spend conditions
            # we use height=0 here to not enable any soft-fork semantics. It
            # will only matter once the wallet generates transactions relying on
            # new conditions, and we can change this by then
            result: NPCResult = get_name_puzzle_conditions(
                program,
                self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
                mempool_mode=True,
                height=uint32(0),
                constants=self.wallet_state_manager.constants,
            )
            self.cost_of_single_tx = result.cost
            self.log.info(f"Cost of a single tx for standard wallet: {self.cost_of_single_tx}")

        max_cost = self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM / 5  # avoid full block TXs
        current_cost = 0
        total_amount = 0
        total_coin_count = 0
        for record in spendable:
            current_cost += self.cost_of_single_tx
            total_amount += record.coin.amount
            total_coin_count += 1
            if current_cost + self.cost_of_single_tx > max_cost:
                break

        return uint128(total_amount)

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.STANDARD_WALLET

    def id(self) -> uint32:
        return self.wallet_id

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return await self.wallet_state_manager.get_confirmed_balance_for_wallet(self.id(), record_list)

    async def get_unconfirmed_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return await self.wallet_state_manager.get_unconfirmed_balance(self.id(), unspent_records)

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        spendable = await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(
            self.id(), unspent_records
        )
        return spendable

    async def get_pending_change_balance(self) -> uint64:
        unconfirmed_tx: List[TransactionRecord] = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
            self.id()
        )
        addition_amount = 0

        for record in unconfirmed_tx:
            if not record.is_in_mempool():
                if record.spend_bundle is not None:
                    self.log.warning(
                        f"TransactionRecord SpendBundle ID: {record.spend_bundle.name()} not in mempool. "
                        f"(peer, included, error) list: {record.sent_to}"
                    )
                continue
            our_spend = False
            for coin in record.removals:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(coin, self.id()):
                    our_spend = True
                    break

            if our_spend is not True:
                continue

            for coin in record.additions:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(coin, self.id()):
                    addition_amount += coin.amount

        return uint64(addition_amount)

    def require_derivation_paths(self) -> bool:
        return True

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        return puzzle_for_pk(pubkey)

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        return puzzle_hash_for_pk(pubkey)

    async def convert_puzzle_hash(self, puzzle_hash: bytes32) -> bytes32:
        return puzzle_hash  # Looks unimpressive, but it's more complicated in other wallets

    async def hack_populate_secret_key_for_puzzle_hash(self, puzzle_hash: bytes32) -> G1Element:
        secret_key = await self.wallet_state_manager.get_private_key(puzzle_hash)
        # HACK
        synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        self.secret_key_store.save_secret_key(synthetic_secret_key)
        return secret_key.get_g1()

    async def hack_populate_secret_keys_for_coin_spends(self, coin_spends: List[CoinSpend]) -> None:
        """
        This hack forces secret keys into the `_pk2sk` lookup. This should eventually be replaced
        by a persistent DB table that can do this look-up directly.
        """
        for coin_spend in coin_spends:
            await self.hack_populate_secret_key_for_puzzle_hash(coin_spend.coin.puzzle_hash)

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        public_key = await self.hack_populate_secret_key_for_puzzle_hash(puzzle_hash)
        return puzzle_for_pk(public_key)

    async def get_new_puzzle(self) -> Program:
        dr = await self.wallet_state_manager.get_unused_derivation_record(self.id())
        puzzle = puzzle_for_pk(dr.pubkey)
        await self.hack_populate_secret_key_for_puzzle_hash(puzzle.get_tree_hash())
        return puzzle

    async def get_puzzle_hash(self, new: bool) -> bytes32:
        if new:
            return await self.get_new_puzzlehash()
        else:
            record: Optional[
                DerivationRecord
            ] = await self.wallet_state_manager.get_current_derivation_record_for_wallet(self.id())
            if record is None:
                return await self.get_new_puzzlehash()
            return record.puzzle_hash

    async def get_new_puzzlehash(self) -> bytes32:
        puzhash = (await self.wallet_state_manager.get_unused_derivation_record(self.id())).puzzle_hash
        await self.hack_populate_secret_key_for_puzzle_hash(puzhash)
        return puzhash

    def make_solution(
        self,
        primaries: List[Payment],
        coin_announcements: Optional[Set[bytes]] = None,
        coin_announcements_to_assert: Optional[Set[bytes32]] = None,
        puzzle_announcements: Optional[Set[bytes]] = None,
        puzzle_announcements_to_assert: Optional[Set[bytes32]] = None,
        magic_conditions: Optional[List[Any]] = None,
        fee: uint64 = uint64(0),
    ) -> Program:
        assert fee >= 0
        condition_list = []
        if len(primaries) > 0:
            for primary in primaries:
                condition_list.append(make_create_coin_condition(primary.puzzle_hash, primary.amount, primary.memos))
        if fee:
            condition_list.append(make_reserve_fee_condition(fee))
        if coin_announcements:
            for announcement in coin_announcements:
                condition_list.append(make_create_coin_announcement(announcement))
        if coin_announcements_to_assert:
            for announcement_hash in coin_announcements_to_assert:
                condition_list.append(make_assert_coin_announcement(announcement_hash))
        if puzzle_announcements:
            for announcement in puzzle_announcements:
                condition_list.append(make_create_puzzle_announcement(announcement))
        if puzzle_announcements_to_assert:
            for announcement_hash in puzzle_announcements_to_assert:
                condition_list.append(make_assert_puzzle_announcement(announcement_hash))
        if magic_conditions is not None:
            condition_list.extend(magic_conditions)
        return solution_for_conditions(condition_list)

    def add_condition_to_solution(self, condition: Program, solution: Program) -> Program:
        python_program = solution.as_python()
        python_program[1].append(condition)
        return cast(Program, Program.to(python_program))

    async def select_coins(
        self,
        amount: uint64,
        exclude: Optional[List[Coin]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        excluded_coin_amounts: Optional[List[uint64]] = None,
    ) -> Set[Coin]:
        """
        Returns a set of coins that can be used for generating a new transaction.
        Note: Must be called under wallet state manager lock
        """
        spendable_amount: uint128 = await self.get_spendable_balance()
        spendable_coins: List[WalletCoinRecord] = list(
            await self.wallet_state_manager.get_spendable_coins_for_wallet(self.id())
        )

        # Try to use coins from the store, if there isn't enough of "unused"
        # coins use change coins that are not confirmed yet
        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.id()
        )
        if max_coin_amount is None:
            max_coin_amount = uint64(self.wallet_state_manager.constants.MAX_COIN_AMOUNT)
        coins = await select_coins(
            spendable_amount,
            max_coin_amount,
            spendable_coins,
            unconfirmed_removals,
            self.log,
            uint128(amount),
            exclude,
            min_coin_amount,
            excluded_coin_amounts,
        )
        assert sum(c.amount for c in coins) >= amount
        return coins

    async def _generate_unsigned_transaction(
        self,
        amount: uint64,
        newpuzzlehash: bytes32,
        fee: uint64 = uint64(0),
        origin_id: Optional[bytes32] = None,
        coins: Optional[Set[Coin]] = None,
        primaries_input: Optional[List[Payment]] = None,
        ignore_max_send_amount: bool = False,
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        memos: Optional[List[bytes]] = None,
        negative_change_allowed: bool = False,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        excluded_coin_amounts: Optional[List[uint64]] = None,
        excluded_coins: Optional[Set[Coin]] = None,
        puzzle_decorator_override: Optional[List[Dict[str, Any]]] = None,
        reuse_puzhash: Optional[bool] = None,
    ) -> List[CoinSpend]:
        """
        Generates a unsigned transaction in form of List(Puzzle, Solutions)
        Note: this must be called under a wallet state manager lock
        """
        decorator_manager: PuzzleDecoratorManager = self.wallet_state_manager.decorator_manager
        if puzzle_decorator_override is not None:
            decorator_manager = PuzzleDecoratorManager.create(puzzle_decorator_override)

        primaries = []
        if primaries_input is not None:
            primaries.extend(primaries_input)

        total_amount = amount + sum(primary.amount for primary in primaries) + fee

        if reuse_puzhash is None:
            reuse_puzhash_config = self.wallet_state_manager.config.get("reuse_public_key_for_change", None)
            if reuse_puzhash_config is None:
                reuse_puzhash = False
            else:
                reuse_puzhash = reuse_puzhash_config.get(
                    str(self.wallet_state_manager.wallet_node.logged_in_fingerprint), False
                )
        total_balance = await self.get_spendable_balance()
        if not ignore_max_send_amount:
            max_send = await self.get_max_send_amount()
            if total_amount > max_send:
                raise ValueError(f"Can't send more than {max_send} mojos in a single transaction, got {total_amount}")
            self.log.debug("Got back max send amount: %s", max_send)
        if coins is None:
            if total_amount > total_balance:
                raise ValueError(
                    f"Can't spend more than wallet balance: {total_balance} mojos, tried to spend: {total_amount} mojos"
                )
            excluded_coins_list: Optional[List[Coin]] = None
            if excluded_coins is not None:
                excluded_coins_list = list(excluded_coins)
            coins = await self.select_coins(
                uint64(total_amount),
                min_coin_amount=min_coin_amount,
                max_coin_amount=max_coin_amount,
                excluded_coin_amounts=excluded_coin_amounts,
                exclude=excluded_coins_list,
            )
        elif excluded_coins is not None:
            raise ValueError("Can't exclude coins when also specifically including coins")

        assert len(coins) > 0
        self.log.info(f"coins is not None {coins}")
        spend_value = sum([coin.amount for coin in coins])
        self.log.info(f"spend_value is {spend_value} and total_amount is {total_amount}")
        change = spend_value - total_amount
        if negative_change_allowed:
            change = max(0, change)

        assert change >= 0

        if coin_announcements_to_consume is not None:
            coin_announcements_bytes: Optional[Set[bytes32]] = {a.name() for a in coin_announcements_to_consume}
        else:
            coin_announcements_bytes = None
        if puzzle_announcements_to_consume is not None:
            puzzle_announcements_bytes: Optional[Set[bytes32]] = {a.name() for a in puzzle_announcements_to_consume}
        else:
            puzzle_announcements_bytes = None

        spends: List[CoinSpend] = []
        primary_announcement_hash: Optional[bytes32] = None

        # Check for duplicates
        all_primaries_list = [(p.puzzle_hash, p.amount) for p in primaries]
        if len(set(all_primaries_list)) != len(all_primaries_list):
            raise ValueError("Cannot create two identical coins")
        for coin in coins:
            # Only one coin creates outputs
            if origin_id in (None, coin.name()):
                origin_id = coin.name()
                public_key = await self.hack_populate_secret_key_for_puzzle_hash(coin.puzzle_hash)
                inner_puzzle = puzzle_for_pk(public_key)
                decorated_target_puzzle_hash = decorator_manager.decorate_target_puzzle_hash(
                    inner_puzzle, newpuzzlehash
                )
                target_primary: List[Payment] = []
                if memos is None:
                    memos = []
                memos = decorator_manager.decorate_memos(inner_puzzle, newpuzzlehash, memos)
                if (primaries_input is None and amount > 0) or primaries_input is not None:
                    primaries.append(Payment(decorated_target_puzzle_hash, amount, memos))
                    target_primary.append(Payment(newpuzzlehash, amount, memos))

                if change > 0:
                    if reuse_puzhash:
                        change_puzzle_hash: bytes32 = coin.puzzle_hash
                        for primary in primaries:
                            if change_puzzle_hash == primary.puzzle_hash and change == primary.amount:
                                # We cannot create two coins has same id, create a new puzhash for the change:
                                change_puzzle_hash = await self.get_new_puzzlehash()
                                break
                    else:
                        change_puzzle_hash = await self.get_new_puzzlehash()
                    primaries.append(Payment(change_puzzle_hash, uint64(change)))
                message_list: List[bytes32] = [c.name() for c in coins]
                for primary in primaries:
                    message_list.append(Coin(coin.name(), primary.puzzle_hash, primary.amount).name())
                message: bytes32 = std_hash(b"".join(message_list))
                puzzle: Program = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)
                solution: Program = self.make_solution(
                    primaries=primaries,
                    fee=fee,
                    coin_announcements={message},
                    coin_announcements_to_assert=coin_announcements_bytes,
                    puzzle_announcements_to_assert=puzzle_announcements_bytes,
                )
                solution = decorator_manager.solve(inner_puzzle, target_primary, solution)
                primary_announcement_hash = Announcement(coin.name(), message).name()

                spends.append(
                    CoinSpend(
                        coin, SerializedProgram.from_bytes(bytes(puzzle)), SerializedProgram.from_bytes(bytes(solution))
                    )
                )
                break
        else:
            raise ValueError("origin_id is not in the set of selected coins")

        # Process the non-origin coins now that we have the primary announcement hash
        for coin in coins:
            if coin.name() == origin_id:
                continue
            public_key = await self.hack_populate_secret_key_for_puzzle_hash(coin.puzzle_hash)
            inner_puzzle = puzzle_for_pk(public_key)
            puzzle = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)
            solution = self.make_solution(primaries=[], coin_announcements_to_assert={primary_announcement_hash})
            solution = decorator_manager.solve(inner_puzzle, [], solution)
            spends.append(
                CoinSpend(
                    coin, SerializedProgram.from_bytes(bytes(puzzle)), SerializedProgram.from_bytes(bytes(solution))
                )
            )

        self.log.debug(f"Spends is {spends}")
        return spends

    async def sign_transaction(self, coin_spends: List[CoinSpend]) -> SpendBundle:
        return await sign_coin_spends(
            coin_spends,
            self.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )

    async def sign_message(
        self, message: str, puzzle_hash: bytes32, is_hex: bool = False
    ) -> Tuple[G1Element, G2Element]:
        # CHIP-0002 message signing as documented at:
        # https://github.com/Chia-Network/chips/blob/80e4611fe52b174bf1a0382b9dff73805b18b8c6/CHIPs/chip-0002.md#signmessage
        private = await self.wallet_state_manager.get_private_key(puzzle_hash)
        synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
        synthetic_pk = synthetic_secret_key.get_g1()
        if is_hex:
            puzzle: Program = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message)))
        else:
            puzzle = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message))
        return synthetic_pk, AugSchemeMPL.sign(synthetic_secret_key, puzzle.get_tree_hash())

    async def generate_signed_transaction(
        self,
        amount: uint64,
        puzzle_hash: bytes32,
        fee: uint64 = uint64(0),
        coins: Optional[Set[Coin]] = None,
        primaries: Optional[List[Payment]] = None,
        ignore_max_send_amount: bool = False,
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        memos: Optional[List[bytes]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        excluded_coin_amounts: Optional[List[uint64]] = None,
        excluded_coins: Optional[Set[Coin]] = None,
        puzzle_decorator_override: Optional[List[Dict[str, Any]]] = None,
        reuse_puzhash: Optional[bool] = None,
        **kwargs: Unpack[GSTOptionalArgs],
    ) -> TransactionRecord:
        origin_id: Optional[bytes32] = kwargs.get("origin_id", None)
        negative_change_allowed: bool = kwargs.get("negative_change_allowed", False)
        """
        Use this to generate transaction.
        Note: this must be called under a wallet state manager lock
        The first output is (amount, puzzle_hash, memos), and the rest of the outputs are in primaries.
        """
        if primaries is None:
            non_change_amount = amount
        else:
            non_change_amount = uint64(amount + sum(p.amount for p in primaries))

        self.log.debug("Generating transaction for: %s %s %s", puzzle_hash, amount, repr(coins))
        transaction = await self._generate_unsigned_transaction(
            amount,
            puzzle_hash,
            fee,
            origin_id,
            coins,
            primaries,
            ignore_max_send_amount,
            coin_announcements_to_consume,
            puzzle_announcements_to_consume,
            memos,
            negative_change_allowed,
            min_coin_amount=min_coin_amount,
            max_coin_amount=max_coin_amount,
            excluded_coin_amounts=excluded_coin_amounts,
            excluded_coins=excluded_coins,
            puzzle_decorator_override=puzzle_decorator_override,
            reuse_puzhash=reuse_puzhash,
        )
        assert len(transaction) > 0
        self.log.info("About to sign a transaction: %s", transaction)
        await self.hack_populate_secret_keys_for_coin_spends(transaction)
        spend_bundle: SpendBundle = await sign_coin_spends(
            transaction,
            self.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )

        now = uint64(int(time.time()))
        add_list: List[Coin] = list(spend_bundle.additions())
        rem_list: List[Coin] = list(spend_bundle.removals())

        output_amount = sum(a.amount for a in add_list) + fee
        input_amount = sum(r.amount for r in rem_list)
        if negative_change_allowed:
            assert output_amount >= input_amount
        else:
            assert output_amount == input_amount

        return TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=now,
            to_puzzle_hash=puzzle_hash,
            amount=uint64(non_change_amount),
            fee_amount=uint64(fee),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=add_list,
            removals=rem_list,
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
            memos=list(compute_memos(spend_bundle).items()),
        )

    async def create_tandem_xch_tx(
        self,
        fee: uint64,
        announcement_to_assert: Optional[Announcement] = None,
        reuse_puzhash: Optional[bool] = None,
    ) -> TransactionRecord:
        chia_coins = await self.select_coins(fee)
        if reuse_puzhash is None:
            reuse_puzhash_config = self.wallet_state_manager.config.get("reuse_public_key_for_change", None)
            if reuse_puzhash_config is None:
                reuse_puzhash = False
            else:
                reuse_puzhash = reuse_puzhash_config.get(
                    str(self.wallet_state_manager.wallet_node.logged_in_fingerprint), False
                )
        chia_tx = await self.generate_signed_transaction(
            uint64(0),
            (await self.get_puzzle_hash(not reuse_puzhash)),
            fee=fee,
            coins=chia_coins,
            coin_announcements_to_consume={announcement_to_assert} if announcement_to_assert is not None else None,
            reuse_puzhash=reuse_puzhash,
        )
        assert chia_tx.spend_bundle is not None
        return chia_tx

    async def push_transaction(self, tx: TransactionRecord) -> None:
        """Use this API to send transactions."""
        await self.wallet_state_manager.add_pending_transaction(tx)
        await self.wallet_state_manager.wallet_node.update_ui()

    async def get_coins_to_offer(
        self,
        asset_id: Optional[bytes32],
        amount: uint64,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
    ) -> Set[Coin]:
        if asset_id is not None:
            raise ValueError(f"The standard wallet cannot offer coins with asset id {asset_id}")
        balance = await self.get_spendable_balance()
        if balance < amount:
            raise Exception(f"insufficient funds in wallet {self.id()}")
        return await self.select_coins(amount, min_coin_amount=min_coin_amount, max_coin_amount=max_coin_amount)

    # WSChiaConnection is only imported for type checking
    async def coin_added(
        self, coin: Coin, height: uint32, peer: WSChiaConnection
    ) -> None:  # pylint: disable=used-before-assignment
        pass

    def get_name(self) -> str:
        return "Standard Wallet"
