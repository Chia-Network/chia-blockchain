import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from blspy import G1Element

from chia.consensus.condition_costs import ConditionCost
from chia.consensus.cost_calculator import calculate_cost_of_program, NPCResult
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.announcement import Announcement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_solution import CoinSolution
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
from chia.wallet.sign_coin_solutions import sign_coin_solutions
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo


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
            self.cost_of_single_tx = await self.calculate_cost_of_single_tx()
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
                self.log.warning(f"Record: {record} not in mempool")
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

    async def hack_populate_secret_keys_for_coin_solutions(self, coin_solutions: List[CoinSolution]) -> None:
        """
        This hack forces secret keys into the `_pk2sk` lookup. This should eventually be replaced
        by a persistent DB table that can do this look-up directly.
        """
        for coin_solution in coin_solutions:
            await self.hack_populate_secret_key_for_puzzle_hash(coin_solution.coin.puzzle_hash)

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
        create_coins: Optional[List[Dict[str, Any]]] = None,
        min_time=0,
        me=None,
        coin_announcements: Optional[Set[bytes32]] = None,
        coin_announcements_to_assert: Optional[Set[bytes32]] = None,
        puzzle_announcements: Optional[Set[bytes32]] = None,
        puzzle_announcements_to_assert: Optional[Set[bytes32]] = None,
        fee=0,
    ) -> Program:
        assert fee >= 0
        condition_list = []
        if create_coins:
            for new_coin in create_coins:
                condition_list.append(make_create_coin_condition(new_coin["puzzlehash"], new_coin["amount"]))
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

    async def select_coins(
        self, amount, fee_rate: float = 0.0, current_cost: uint64 = uint64(0), exclude: List[Coin] = None
    ) -> Tuple[Set[Coin], uint64]:
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

        if self.cost_of_single_tx is None:
            self.cost_of_single_tx = await self.calculate_cost_of_single_tx()

        total_fee = fee_rate * current_cost

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
            total_fee += int(self.cost_of_single_tx * fee_rate)
            if amount + total_fee > spendable_amount:
                raise ValueError("No enough xch for this fee rate")
            if sum_value >= amount + total_fee and len(used_coins) > 0:
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
        if sum_value < amount + total_fee:
            raise ValueError(
                "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
            )

        self.log.debug(f"Successfully selected coins: {used_coins}")
        return used_coins, uint64(int(total_fee))

    async def calculate_cost_of_single_tx(self):
        if self.cost_of_single_tx is not None:
            return self.cost_of_single_tx
        record = await self.wallet_state_manager.puzzle_store.get_derivation_record(0, self.id())
        if record is None:
            return
        puzzle: Program = await self.puzzle_for_puzzle_hash(record.puzzle_hash)
        solution = self.make_solution()
        coin_solutions = CoinSolution(
            Coin(32 * b"0", record.puzzle_hash, 100),
            SerializedProgram.from_bytes(bytes(puzzle)),
            SerializedProgram.from_bytes(bytes(solution)),
        )
        spend_bundle: SpendBundle = await sign_coin_solutions(
            [coin_solutions],
            self.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )
        program: BlockGenerator = simple_solution_generator(spend_bundle)
        # npc contains names of the coins removed, puzzle_hashes and their spend conditions
        result: NPCResult = get_name_puzzle_conditions(
            program,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
            cost_per_byte=self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
            safe_mode=True,
        )
        cost_result: uint64 = calculate_cost_of_program(
            program.program, result, self.wallet_state_manager.constants.COST_PER_BYTE
        )
        self.cost_of_single_tx = cost_result
        return cost_result

    async def _generate_unsigned_transaction(
        self,
        create_coins: List[Dict[str, Any]],
        fee: uint64 = uint64(0),
        origin_id: bytes32 = None,
        coins: Set[Coin] = None,
        announcements_to_consume: Set[Announcement] = None,
    ) -> List[CoinSolution]:
        """
        Generates a unsigned transaction in form of List(Puzzle, Solutions)
        Note: this must be called under a wallet state manager lock
        """

        create_coins_copy = create_coins.copy()
        create_amount = 0
        for prim in create_coins_copy:
            create_amount += prim["amount"]

        total_amount = create_amount + fee
        assert coins is not None
        spend_value = sum([coin.amount for coin in coins])
        change = spend_value - total_amount
        assert change >= 0

        spends: List[CoinSolution] = []
        primary_announcement_hash: Optional[bytes32] = None

        # Check for duplicate outputs
        dict_addresses: Dict[bytes32, Set] = {}
        for new_coin in create_coins:
            if new_coin["puzzlehash"] not in dict_addresses:
                dict_addresses[new_coin["puzzlehash"]] = set()

            amount = new_coin["amount"]
            if amount in dict_addresses[new_coin["puzzlehash"]]:
                raise ValueError("can't create two identical coins")
            dict_addresses[new_coin["puzzlehash"]].add(amount)

        for coin in coins:
            self.log.info(f"coin from coins {coin}")
            puzzle: Program = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)

            # Only one coin creates outputs
            if primary_announcement_hash is None and origin_id in (None, coin.name()):
                if change > 0:
                    change_puzzle_hash: bytes32 = await self.get_new_puzzlehash()
                    create_coins.append({"puzzlehash": change_puzzle_hash, "amount": change})
                message_list: List[bytes32] = [c.name() for c in coins]
                for primary in create_coins:
                    message_list.append(Coin(coin.name(), primary["puzzlehash"], primary["amount"]).name())
                message: bytes32 = std_hash(b"".join(message_list))
                solution: Program = self.make_solution(
                    create_coins=create_coins,
                    fee=fee,
                    coin_announcements={message},
                    coin_announcements_to_assert=announcements_to_consume,
                )
                primary_announcement_hash = Announcement(coin.name(), message).name()
            else:
                solution = self.make_solution(coin_announcements_to_assert={primary_announcement_hash})

            spends.append(
                CoinSolution(
                    coin, SerializedProgram.from_bytes(bytes(puzzle)), SerializedProgram.from_bytes(bytes(solution))
                )
            )

        self.log.info(f"Spends is {spends}")
        return spends

    async def sign_transaction(self, coin_solutions: List[CoinSolution]) -> SpendBundle:
        return await sign_coin_solutions(
            coin_solutions,
            self.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )

    async def generate_signed_transaction(
        self,
        create_coins: List[Dict[str, Any]],
        fee_rate: float = 0.0,
        origin_id: bytes32 = None,
        coins: Set[Coin] = None,
        announcements_to_consume: Set[Announcement] = None,
    ) -> TransactionRecord:
        # Total fee will be create coin conditions + sum of clvm puzzle costs
        first_address = create_coins[0]["puzzlehash"]
        condition_cost = 0
        for _ in create_coins:
            condition_cost += ConditionCost.CREATE_COIN.value

        non_change_amount = uint64(sum(p["amount"] for p in create_coins))

        if coins is not None:
            # Require fee to be passed in if coins list is
            fee = fee_rate * condition_cost
            cost = await self.calculate_cost_of_single_tx()
            for _ in coins:
                fee += cost * fee_rate
        else:
            coins, fee = await self.select_coins(non_change_amount, fee_rate, uint64(condition_cost))

        coin_solutions = await self._generate_unsigned_transaction(
            create_coins, uint64(int(fee)), origin_id, coins, announcements_to_consume
        )

        assert len(coin_solutions) > 0
        await self.hack_populate_secret_keys_for_coin_solutions(coin_solutions)
        spend_bundle: SpendBundle = await sign_coin_solutions(
            coin_solutions,
            self.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )
        now = uint64(int(time.time()))
        add_list: List[Coin] = list(spend_bundle.additions())
        rem_list: List[Coin] = list(spend_bundle.removals())
        assert sum(a.amount for a in add_list) + fee == sum(r.amount for r in rem_list)

        return TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=now,
            to_puzzle_hash=first_address,
            amount=uint64(non_change_amount),
            fee_amount=uint64(int(fee)),
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
        )

    async def push_transaction(self, tx: TransactionRecord) -> None:
        """Use this API to send transactions."""
        await self.wallet_state_manager.add_pending_transaction(tx)

    # This is to be aggregated together with a coloured coin offer to ensure that the trade happens
    async def create_spend_bundle_relative_chia(self, chia_amount: int, exclude: List[Coin]) -> SpendBundle:
        list_of_solutions = []

        # If we're losing value then get coins with at least that much value
        # If we're gaining value then our amount doesn't matter
        if chia_amount < 0:
            utxos, fee = await self.select_coins(abs(chia_amount), exclude=exclude)
        else:
            utxos, fee = await self.select_coins(0, exclude=exclude)

        assert len(utxos) > 0

        # Calculate output amount given sum of utxos
        spend_value = sum([coin.amount for coin in utxos])
        chia_amount = spend_value + chia_amount

        # Create coin solutions for each utxo
        output_created = None
        for coin in utxos:
            puzzle = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)
            if output_created is None:
                newpuzhash = await self.get_new_puzzlehash()
                primaries = [{"puzzlehash": newpuzhash, "amount": chia_amount}]
                solution = self.make_solution(create_coins=primaries)
                output_created = coin
            list_of_solutions.append(CoinSolution(coin, puzzle, solution))

        await self.hack_populate_secret_keys_for_coin_solutions(list_of_solutions)
        spend_bundle = await sign_coin_solutions(
            list_of_solutions,
            self.secret_key_store.secret_key_for_public_key,
            self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
        )
        return spend_bundle
