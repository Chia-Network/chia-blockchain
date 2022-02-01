import logging
import time
from typing import Any, Dict, List, Optional, Set

from blspy import G1Element

from chia.consensus.cost_calculator import NPCResult
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.announcement import Announcement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.hash import std_hash
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    solution_for_conditions,
)
from chia.wallet.puzzles.puzzle_utils import (
    make_assert_coin_announcement,
    make_assert_puzzle_announcement,
    make_assert_my_coin_id_condition,
    make_assert_absolute_seconds_exceeds_condition,
    make_create_coin_announcement,
    make_create_puzzle_announcement,
    make_create_coin_condition,
    make_reserve_fee_condition,
)
from chia.wallet.secret_key_store import SecretKeyStore
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.payment import Payment
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.util.compute_memos import compute_memos


class Wallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_id: uint32
    secret_key_store: SecretKeyStore
    cost_of_single_tx: Optional[int]

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = None,
    ):
        self = Wallet()
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_id = info.id
        self.secret_key_store = SecretKeyStore()
        self.cost_of_single_tx = None
        return self

    async def get_max_send_amount(self, records=None):
        spendable: List[WalletCoinRecord] = list(
            await self.wallet_state_manager.get_spendable_coins_for_wallet(self.id(), records)
        )
        if len(spendable) == 0:
            return 0
        spendable.sort(reverse=True, key=lambda record: record.coin.amount)
        if self.cost_of_single_tx is None:
            coin = spendable[0].coin
            [tx] = await self.generate_signed_transaction(
                [Payment(coin.puzzle_hash, coin.amount, [])], coins={coin}, ignore_max_send_amount=True
            )
            program: BlockGenerator = simple_solution_generator(tx.spend_bundle)
            # npc contains names of the coins removed, puzzle_hashes and their spend conditions
            result: NPCResult = get_name_puzzle_conditions(
                program,
                self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
                cost_per_byte=self.wallet_state_manager.constants.COST_PER_BYTE,
                mempool_mode=True,
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

        return total_amount

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.STANDARD_WALLET)

    def id(self) -> uint32:
        return self.wallet_id

    async def get_confirmed_balance(self, unspent_records=None) -> uint128:
        return await self.wallet_state_manager.get_confirmed_balance_for_wallet(self.id(), unspent_records)

    async def get_unconfirmed_balance(self, unspent_records=None) -> uint128:
        return await self.wallet_state_manager.get_unconfirmed_balance(self.id(), unspent_records)

    async def get_spendable_balance(self, unspent_records=None) -> uint128:
        spendable = await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(
            self.id(), unspent_records
        )
        return spendable

    async def get_pending_change_balance(self) -> uint64:
        unconfirmed_tx = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(self.id())
        addition_amount = 0

        for record in unconfirmed_tx:
            if not record.is_in_mempool():
                self.log.warning(f"Record: {record} not in mempool, {record.sent_to}")
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

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        return puzzle_for_pk(pubkey)

    async def convert_puzzle_hash(self, puzzle_hash: bytes32) -> bytes32:
        return puzzle_hash  # Looks unimpressive, but it's more complicated in other wallets

    async def hack_populate_secret_key_for_puzzle_hash(self, puzzle_hash: bytes32) -> G1Element:
        maybe = await self.wallet_state_manager.get_keys(puzzle_hash)
        if maybe is None:
            error_msg = f"Wallet couldn't find keys for puzzle_hash {puzzle_hash}"
            self.log.error(error_msg)
            raise ValueError(error_msg)

        # Get puzzle for pubkey
        public_key, secret_key = maybe

        # HACK
        synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        self.secret_key_store.save_secret_key(synthetic_secret_key)

        return public_key

    async def hack_populate_secret_keys_for_coin_spends(self, coin_spends: List[CoinSpend]) -> None:
        """
        This hack forces secret keys into the `_pk2sk` lookup. This should eventually be replaced
        by a persistent DB table that can do this look-up directly.
        """
        for coin_spend in coin_spends:
            await self.hack_populate_secret_key_for_puzzle_hash(coin_spend.coin.puzzle_hash)

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        public_key = await self.hack_populate_secret_key_for_puzzle_hash(puzzle_hash)
        return puzzle_for_pk(bytes(public_key))

    async def get_new_puzzle(self) -> Program:
        dr = await self.wallet_state_manager.get_unused_derivation_record(self.id())
        return puzzle_for_pk(bytes(dr.pubkey))

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

    async def get_new_puzzlehash(self, in_transaction: bool = False) -> bytes32:
        return (await self.wallet_state_manager.get_unused_derivation_record(self.id(), in_transaction)).puzzle_hash

    def make_solution(
        self,
        payments: List[Payment],
        min_time=0,
        me=None,
        coin_announcements: Optional[Set[bytes]] = None,
        coin_announcements_to_assert: Optional[Set[bytes32]] = None,
        puzzle_announcements: Optional[Set[bytes32]] = None,
        puzzle_announcements_to_assert: Optional[Set[bytes32]] = None,
        fee=0,
    ) -> Program:
        assert fee >= 0
        condition_list = []
        if len(payments) > 0:
            for payment in payments:
                condition_list.append(make_create_coin_condition(payment.puzzle_hash, payment.amount, payment.memos))
        if min_time > 0:
            condition_list.append(make_assert_absolute_seconds_exceeds_condition(min_time))
        if me:
            condition_list.append(make_assert_my_coin_id_condition(me["id"]))
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
        return solution_for_conditions(condition_list)

    def add_condition_to_solution(self, condition: Program, solution: Program) -> Program:
        python_program = solution.as_python()
        python_program[1].append(condition)
        return Program.to(python_program)

    async def select_coins(self, amount, exclude: List[Coin] = None) -> Set[Coin]:
        """
        Returns a set of coins that can be used for generating a new transaction.
        Note: This must be called under a wallet state manager lock
        """
        if exclude is None:
            exclude = []

        spendable_amount = await self.get_spendable_balance()

        if amount > spendable_amount:
            error_msg = (
                f"Can't select amount higher than our spendable balance.  Amount: {amount}, spendable: "
                f" {spendable_amount}"
            )
            self.log.warning(error_msg)
            raise ValueError(error_msg)

        self.log.info(f"About to select coins for amount {amount}")
        unspent: List[WalletCoinRecord] = list(
            await self.wallet_state_manager.get_spendable_coins_for_wallet(self.id())
        )
        sum_value = 0
        used_coins: Set = set()

        # Use older coins first
        unspent.sort(reverse=True, key=lambda r: r.coin.amount)

        # Try to use coins from the store, if there isn't enough of "unused"
        # coins use change coins that are not confirmed yet
        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.id()
        )
        for coinrecord in unspent:
            if sum_value >= amount and len(used_coins) > 0:
                break
            if coinrecord.coin.name() in unconfirmed_removals:
                continue
            if coinrecord.coin in exclude:
                continue
            sum_value += coinrecord.coin.amount
            used_coins.add(coinrecord.coin)
            self.log.debug(f"Selected coin: {coinrecord.coin.name()} at height {coinrecord.confirmed_block_height}!")

        # This happens when we couldn't use one of the coins because it's already used
        # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
        if sum_value < amount:
            raise ValueError(
                "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
            )

        self.log.debug(f"Successfully selected coins: {used_coins}")
        return used_coins

    async def _generate_unsigned_transaction(
        self,
        payments: List[Payment],
        fee: uint64 = uint64(0),
        origin_id: bytes32 = None,
        coins: Set[Coin] = None,
        ignore_max_send_amount: bool = False,
        coin_announcements_to_consume: Set[Announcement] = None,
        puzzle_announcements_to_consume: Set[Announcement] = None,
        negative_change_allowed: bool = False,
    ) -> List[CoinSpend]:
        """
        Generates a unsigned transaction in form of List(Puzzle, Solutions)
        Note: this must be called under a wallet state manager lock
        """
        total_amount = sum(p.amount for p in payments) + fee

        if not ignore_max_send_amount:
            max_send = await self.get_max_send_amount()
            if total_amount > max_send:
                raise ValueError(f"Can't send more than {max_send} in a single transaction")

        if coins is None:
            coins = await self.select_coins(total_amount)
        assert len(coins) > 0
        self.log.info(f"coins is not None {coins}")
        spend_value = sum([coin.amount for coin in coins])

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
        all_payments_list = [(p.puzzle_hash, p.amount) for p in payments]
        if len(set(all_payments_list)) != len(all_payments_list):
            raise ValueError("Cannot create two identical coins")

        for coin in coins:
            # Only one coin creates outputs
            if origin_id in (None, coin.name()):
                origin_id = coin.name()
                if change > 0:
                    change_puzzle_hash: bytes32 = await self.get_new_puzzlehash()
                    payments.append(Payment(change_puzzle_hash, uint64(change), []))
                message_list: List[bytes32] = [c.name() for c in coins]
                for payment in payments:
                    message_list.append(Coin(coin.name(), payment.puzzle_hash, payment.amount).name())
                message: bytes32 = std_hash(b"".join(message_list))
                puzzle: Program = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)
                solution: Program = self.make_solution(
                    payments=payments,
                    fee=fee,
                    coin_announcements={message},
                    coin_announcements_to_assert=coin_announcements_bytes,
                    puzzle_announcements_to_assert=puzzle_announcements_bytes,
                )
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

            puzzle = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)
            solution = self.make_solution([], coin_announcements_to_assert={primary_announcement_hash})
            spends.append(
                CoinSpend(
                    coin, SerializedProgram.from_bytes(bytes(puzzle)), SerializedProgram.from_bytes(bytes(solution))
                )
            )

        self.log.info(f"Spends is {spends}")
        return spends

    async def sign_transaction(self, coin_spends: List[CoinSpend]) -> SpendBundle:
        return await sign_coin_spends(
            coin_spends,
            self.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )

    async def generate_signed_transaction(
        self,
        payments: List[Payment],
        fee: uint64 = uint64(0),
        origin_id: bytes32 = None,
        coins: Set[Coin] = None,
        ignore_max_send_amount: bool = False,
        coin_announcements_to_consume: Set[Announcement] = None,
        puzzle_announcements_to_consume: Set[Announcement] = None,
        negative_change_allowed: bool = False,
    ) -> List[TransactionRecord]:
        """
        Use this to generate transaction.
        Note: this must be called under a wallet state manager lock
        """
        transaction = await self._generate_unsigned_transaction(
            payments.copy(),
            fee,
            origin_id,
            coins,
            ignore_max_send_amount,
            coin_announcements_to_consume,
            puzzle_announcements_to_consume,
            negative_change_allowed,
        )
        assert len(transaction) > 0

        self.log.info("About to sign a transaction")
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

        return [
            TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=now,
                to_puzzle_hash=payments[0].puzzle_hash,
                amount=uint64(sum(p.amount for p in payments)),
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
        ]

    async def push_transaction(self, tx: TransactionRecord) -> None:
        """Use this API to send transactions."""
        await self.wallet_state_manager.add_pending_transaction(tx)
        await self.wallet_state_manager.wallet_node.update_ui()
