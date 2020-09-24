import time
from typing import Dict, Optional, List, Set, Any
import logging
from blspy import G1Element, AugSchemeMPL, PrivateKey
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.condition_tools import (
    conditions_dict_for_solution,
    pkm_pairs_for_conditions_dict,
)
from src.util.ints import uint8, uint64, uint32
from src.wallet.puzzles.p2_delegated_puzzle import (
    puzzle_for_pk,
    solution_for_conditions,
)
from src.wallet.puzzles.puzzle_utils import (
    make_assert_my_coin_id_condition,
    make_assert_time_exceeds_condition,
    make_assert_coin_consumed_condition,
    make_create_coin_condition,
    make_assert_fee_condition,
)
from src.wallet.transaction_record import TransactionRecord
from src.wallet.util.wallet_types import WalletType
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo


class Wallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_id: uint32
    _pk2sk: Dict[G1Element, PrivateKey]

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = None,
    ):
        self = Wallet()
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_id = info.id

        # HACK
        self._pk2sk = {}

        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.STANDARD_WALLET.value)

    def id(self):
        return self.wallet_id

    async def get_confirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_confirmed_balance_for_wallet(
            self.id()
        )

    async def get_unconfirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_unconfirmed_balance(self.id())

    async def get_frozen_amount(self) -> uint64:
        return await self.wallet_state_manager.get_frozen_balance(self.id())

    async def get_spendable_balance(self) -> uint64:
        spendable_am = (
            await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(
                self.id()
            )
        )
        return spendable_am

    async def get_pending_change_balance(self) -> uint64:
        unconfirmed_tx = (
            await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
                self.id()
            )
        )
        addition_amount = 0

        for record in unconfirmed_tx:
            our_spend = False
            for coin in record.removals:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(
                    coin, self.id()
                ):
                    our_spend = True
                    break

            if our_spend is not True:
                continue

            for coin in record.additions:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(
                    coin, self.id()
                ):
                    addition_amount += coin.amount

        return uint64(addition_amount)

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        return puzzle_for_pk(pubkey)

    async def hack_populate_secret_key_for_puzzle_hash(
        self, puzzle_hash: bytes32
    ) -> G1Element:
        maybe = await self.wallet_state_manager.get_keys(puzzle_hash)
        if maybe is None:
            error_msg = f"Wallet couldn't find keys for puzzle_hash {puzzle_hash}"
            self.log.error(error_msg)
            raise ValueError(error_msg)

        # Get puzzle for pubkey
        public_key, secret_key = maybe

        # HACK
        self._pk2sk[bytes(public_key)] = secret_key
        return public_key

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        public_key = await self.hack_populate_secret_key_for_puzzle_hash(puzzle_hash)
        return puzzle_for_pk(bytes(public_key))

    async def get_new_puzzle(self) -> Program:
        dr = await self.wallet_state_manager.get_unused_derivation_record(self.id())
        return puzzle_for_pk(bytes(dr.pubkey))

    async def get_new_puzzlehash(self) -> bytes32:
        return (
            await self.wallet_state_manager.get_unused_derivation_record(self.id())
        ).puzzle_hash

    def make_solution(self, primaries=None, min_time=0, me=None, consumed=None, fee=0):
        assert fee >= 0
        condition_list = []
        if primaries:
            for primary in primaries:
                condition_list.append(
                    make_create_coin_condition(primary["puzzlehash"], primary["amount"])
                )
        if consumed:
            for coin in consumed:
                condition_list.append(make_assert_coin_consumed_condition(coin))
        if min_time > 0:
            condition_list.append(make_assert_time_exceeds_condition(min_time))
        if me:
            condition_list.append(make_assert_my_coin_id_condition(me["id"]))
        if fee:
            condition_list.append(make_assert_fee_condition(fee))
        return solution_for_conditions(condition_list)

    async def select_coins(self, amount, exclude: List[Coin] = None) -> Set[Coin]:
        """ Returns a set of coins that can be used for generating a new transaction. """
        async with self.wallet_state_manager.lock:
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
                await self.wallet_state_manager.get_spendable_coins_for_wallet(
                    self.id()
                )
            )
            sum_value = 0
            used_coins: Set = set()

            # Use older coins first
            unspent.sort(key=lambda r: r.confirmed_block_index)

            # Try to use coins from the store, if there isn't enough of "unused"
            # coins use change coins that are not confirmed yet
            unconfirmed_removals: Dict[
                bytes32, Coin
            ] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
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
                self.log.info(
                    f"Selected coin: {coinrecord.coin.name()} at height {coinrecord.confirmed_block_index}!"
                )

            # This happens when we couldn't use one of the coins because it's already used
            # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
            if sum_value < amount:
                raise ValueError(
                    "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
                )
                # TODO(straya): remove this
                # unconfirmed_additions = await self.wallet_state_manager.unconfirmed_additions_for_wallet(
                #     self.id()
                # )
                # for coin in unconfirmed_additions.values():
                #     if sum_value > amount:
                #         break
                #     if coin.name() in unconfirmed_removals:
                #         continue

                #     sum_value += coin.amount
                #     used_coins.add(coin)
                #     self.log.info(f"Selected used coin: {coin.name()}")

        self.log.info(f"Successfully selected coins: {used_coins}")
        return used_coins

    async def generate_unsigned_transaction(
        self,
        amount: uint64,
        newpuzzlehash: bytes32,
        fee: uint64 = uint64(0),
        origin_id: bytes32 = None,
        coins: Set[Coin] = None,
    ) -> List[CoinSolution]:
        """
        Generates a unsigned transaction in form of List(Puzzle, Solutions)
        """
        if coins is None:
            coins = await self.select_coins(amount + fee)
        assert len(coins) > 0

        self.log.info(f"coins is not None {coins}")
        spend_value = sum([coin.amount for coin in coins])
        change = spend_value - amount - fee

        spends: List[CoinSolution] = []
        output_created = False

        for coin in coins:
            self.log.info(f"coin from coins {coin}")
            puzzle: Program = await self.puzzle_for_puzzle_hash(coin.puzzle_hash)

            # Only one coin creates outputs
            if not output_created and origin_id in (None, coin.name()):
                primaries = [{"puzzlehash": newpuzzlehash, "amount": amount}]
                if change > 0:
                    changepuzzlehash = await self.get_new_puzzlehash()
                    primaries.append({"puzzlehash": changepuzzlehash, "amount": change})

                solution = self.make_solution(primaries=primaries, fee=fee)
                output_created = True
            else:
                solution = self.make_solution()

            puzzle_solution_pair = Program.to([puzzle, solution])
            spends.append(CoinSolution(coin, puzzle_solution_pair))

        self.log.info(f"Spends is {spends}")
        return spends

    def secret_key_for_public_key(self, public_key: G1Element) -> Optional[PrivateKey]:
        return self._pk2sk.get(bytes(public_key))

    async def sign_transaction(self, coin_solutions: List[CoinSolution]) -> SpendBundle:
        signatures = []

        for coin_solution in coin_solutions:
            await self.hack_populate_secret_key_for_puzzle_hash(
                coin_solution.coin.puzzle_hash
            )

            # Get AGGSIG conditions
            err, conditions_dict, cost = conditions_dict_for_solution(
                coin_solution.solution
            )
            if err or conditions_dict is None:
                error_msg = (
                    f"Sign transaction failed, con:{conditions_dict}, error: {err}"
                )
                self.log.error(error_msg)
                raise ValueError(error_msg)

            # Create signature
            for _, msg in pkm_pairs_for_conditions_dict(
                conditions_dict, bytes(coin_solution.coin)
            ):
                secret_key = self.secret_key_for_public_key(_)
                if secret_key is None:
                    e_msg = f"no secret key for {_}"
                    self.log.error(e_msg)
                    raise ValueError(e_msg)
                signature = AugSchemeMPL.sign(secret_key, msg)
                signatures.append(signature)

        # Aggregate signatures
        aggsig = AugSchemeMPL.aggregate(signatures)
        return SpendBundle(coin_solutions, aggsig)

    async def generate_signed_transaction(
        self,
        amount: uint64,
        puzzle_hash: bytes32,
        fee: uint64 = uint64(0),
        origin_id: bytes32 = None,
        coins: Set[Coin] = None,
    ) -> TransactionRecord:
        """ Use this to generate transaction. """

        transaction = await self.generate_unsigned_transaction(
            amount, puzzle_hash, fee, origin_id, coins
        )
        assert len(transaction) > 0

        self.log.info("About to sign a transaction")
        spend_bundle: SpendBundle = await self.sign_transaction(transaction)

        now = uint64(int(time.time()))
        add_list: List[Coin] = list(spend_bundle.additions())
        rem_list: List[Coin] = list(spend_bundle.removals())

        return TransactionRecord(
            confirmed_at_index=uint32(0),
            created_at_time=now,
            to_puzzle_hash=puzzle_hash,
            amount=uint64(amount),
            fee_amount=uint64(fee),
            incoming=False,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=add_list,
            removals=rem_list,
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
        )

    async def push_transaction(self, tx: TransactionRecord) -> None:
        """ Use this API to send transactions. """
        await self.wallet_state_manager.add_pending_transaction(tx)

    # This is to be aggregated together with a coloured coin offer to ensure that the trade happens
    async def create_spend_bundle_relative_chia(
        self, chia_amount: int, exclude: List[Coin]
    ) -> SpendBundle:
        list_of_solutions = []
        utxos = None

        # If we're losing value then get coins with at least that much value
        # If we're gaining value then our amount doesn't matter
        if chia_amount < 0:
            utxos = await self.select_coins(abs(chia_amount), exclude)
        else:
            utxos = await self.select_coins(0, exclude)

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
                solution = self.make_solution(primaries=primaries)
                output_created = coin
            else:
                solution = self.make_solution(consumed=[output_created.name()])
            list_of_solutions.append(CoinSolution(coin, Program.to([puzzle, solution])))

        spend_bundle = await self.sign_transaction(list_of_solutions)
        return spend_bundle
