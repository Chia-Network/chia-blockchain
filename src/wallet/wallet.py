import time
from typing import Dict, Optional, List, Tuple, Set, Any
import clvm
import logging
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.condition_tools import (
    conditions_for_solution,
    conditions_dict_for_solution,
    conditions_by_opcode,
    hash_key_pairs_for_conditions_dict,
)
from src.util.ints import uint64, uint32
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.puzzles.p2_conditions import puzzle_for_conditions
from src.wallet.puzzles.p2_delegated_puzzle import puzzle_for_pk
from src.wallet.puzzles.puzzle_utils import (
    make_assert_my_coin_id_condition,
    make_assert_time_exceeds_condition,
    make_assert_coin_consumed_condition,
    make_create_coin_condition,
    make_assert_fee_condition,
)
from src.wallet.transaction_record import TransactionRecord
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.wallet_info import WalletInfo


class Wallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo

    @staticmethod
    async def create(
        wallet_state_manager: Any, info: WalletInfo, name: str = None,
    ):
        self = Wallet()

        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.wallet_info = info

        return self

    async def get_confirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_confirmed_balance_for_wallet(
            self.wallet_info.id
        )

    async def get_unconfirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_unconfirmed_balance(
            self.wallet_info.id
        )

    async def get_frozen_amount(self) -> uint64:
        return await self.wallet_state_manager.get_frozen_balance(self.wallet_info.id)

    async def get_spendable_balance(self) -> uint64:
        spendable_am = await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(
            self.wallet_info.id
        )
        return spendable_am

    async def get_pending_change_balance(self) -> uint64:
        unconfirmed_tx = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(
            self.wallet_info.id
        )
        addition_amount = 0

        for record in unconfirmed_tx:
            our_spend = False
            for coin in record.removals:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(
                    coin, self.wallet_info.id
                ):
                    our_spend = True
                    break

            if our_spend is not True:
                continue

            for coin in record.additions:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(
                    coin, self.wallet_info.id
                ):
                    addition_amount += coin.amount

        return uint64(addition_amount)

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        return puzzle_for_pk(pubkey)

    async def get_new_puzzle(self) -> Program:
        return puzzle_for_pk(
            bytes(
                self.wallet_state_manager.get_unused_derivation_record(
                    self.wallet_info.id
                ).pubkey
            )
        )

    async def get_new_puzzlehash(self) -> bytes32:
        return (
            await self.wallet_state_manager.get_unused_derivation_record(
                self.wallet_info.id
            )
        ).puzzle_hash

    def make_solution(
        self, primaries=None, min_time=0, me=None, consumed=None, fee=None
    ):
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
        return clvm.to_sexp_f([puzzle_for_conditions(condition_list), []])

    async def select_coins(
        self, amount, exclude: List[Coin] = None
    ) -> Optional[Set[Coin]]:
        """ Returns a set of coins that can be used for generating a new transaction. """
        async with self.wallet_state_manager.lock:
            if exclude is None:
                exclude = []

            spendable_am = await self.wallet_state_manager.get_unconfirmed_spendable_for_wallet(
                self.wallet_info.id
            )

            if amount > spendable_am:
                self.log.warning(
                    f"Can't select amount higher than our spendable balance {amount}, spendable {spendable_am}"
                )
                return None

            self.log.info(f"About to select coins for amount {amount}")
            unspent: List[WalletCoinRecord] = list(
                await self.wallet_state_manager.get_spendable_coins_for_wallet(
                    self.wallet_info.id
                )
            )
            sum = 0
            used_coins: Set = set()

            # Use older coins first
            unspent.sort(key=lambda r: r.confirmed_block_index)

            # Try to use coins from the store, if there isn't enough of "unused"
            # coins use change coins that are not confirmed yet
            unconfirmed_removals: Dict[
                bytes32, Coin
            ] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
                self.wallet_info.id
            )
            for coinrecord in unspent:
                if sum >= amount and len(used_coins) > 0:
                    break
                if coinrecord.coin.name() in unconfirmed_removals:
                    continue
                if coinrecord.coin in exclude:
                    continue
                sum += coinrecord.coin.amount
                used_coins.add(coinrecord.coin)
                self.log.info(
                    f"Selected coin: {coinrecord.coin.name()} at height {coinrecord.confirmed_block_index}!"
                )

            # This happens when we couldn't use one of the coins because it's already used
            # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
            unconfirmed_additions = None
            if sum < amount:
                raise ValueError(
                    "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
                )
                unconfirmed_additions = await self.wallet_state_manager.unconfirmed_additions_for_wallet(
                    self.wallet_info.id
                )
                for coin in unconfirmed_additions.values():
                    if sum > amount:
                        break
                    if coin.name() in unconfirmed_removals:
                        continue

                    sum += coin.amount
                    used_coins.add(coin)
                    self.log.info(f"Selected used coin: {coin.name()}")

        if sum >= amount:
            self.log.info(f"Successfully selected coins: {used_coins}")
            return used_coins
        else:
            # This shouldn't happen because of: if amount > self.get_unconfirmed_balance_spendable():
            self.log.error(
                f"Wasn't able to select coins for amount: {amount}"
                f"unspent: {unspent}"
                f"unconfirmed_removals: {unconfirmed_removals}"
                f"unconfirmed_additions: {unconfirmed_additions}"
            )
            return None

    async def generate_unsigned_transaction(
        self,
        amount: uint64,
        newpuzzlehash: bytes32,
        fee: uint64 = uint64(0),
        origin_id: bytes32 = None,
        coins: Set[Coin] = None,
    ) -> List[Tuple[Program, CoinSolution]]:
        """
        Generates a unsigned transaction in form of List(Puzzle, Solutions)
        """
        if coins is None:
            coins = await self.select_coins(amount + fee)
        if coins is None:
            self.log.info("coins is None")
            return []

        self.log.info(f"coins is not None {coins}")
        spend_value = sum([coin.amount for coin in coins])
        change = spend_value - amount - fee

        spends: List[Tuple[Program, CoinSolution]] = []
        output_created = False

        for coin in coins:
            self.log.info(f"coin from coins {coin}")
            # Get keys for puzzle_hash
            puzzle_hash = coin.puzzle_hash
            maybe = await self.wallet_state_manager.get_keys(puzzle_hash)
            if not maybe:
                self.log.error(
                    f"Wallet couldn't find keys for puzzle_hash {puzzle_hash}"
                )
                return []

            # Get puzzle for pubkey
            pubkey, secretkey = maybe
            puzzle: Program = puzzle_for_pk(bytes(pubkey))

            # Only one coin creates outputs
            if output_created is False and origin_id is None:
                primaries = [{"puzzlehash": newpuzzlehash, "amount": amount}]
                if change > 0:
                    changepuzzlehash = await self.get_new_puzzlehash()
                    primaries.append({"puzzlehash": changepuzzlehash, "amount": change})

                if fee > 0:
                    solution = self.make_solution(primaries=primaries, fee=fee)
                else:
                    solution = self.make_solution(primaries=primaries)
                output_created = True
            elif output_created is False and origin_id == coin.name():
                primaries = [{"puzzlehash": newpuzzlehash, "amount": amount}]
                if change > 0:
                    changepuzzlehash = await self.get_new_puzzlehash()
                    primaries.append({"puzzlehash": changepuzzlehash, "amount": change})

                if fee > 0:
                    solution = self.make_solution(primaries=primaries, fee=fee)
                else:
                    solution = self.make_solution(primaries=primaries)
                output_created = True
            else:
                solution = self.make_solution()

            spends.append((puzzle, CoinSolution(coin, solution)))

        self.log.info(f"Spends is {spends}")
        return spends

    async def sign_transaction(
        self, spends: List[Tuple[Program, CoinSolution]]
    ) -> Optional[SpendBundle]:
        signatures = []
        for puzzle, solution in spends:
            # Get keys
            keys = await self.wallet_state_manager.get_keys(solution.coin.puzzle_hash)
            if not keys:
                self.log.error(
                    f"Sign transaction failed, No Keys for puzzlehash {solution.coin.puzzle_hash}"
                )
                return None

            pubkey, secretkey = keys
            secretkey = BLSPrivateKey(secretkey)
            code_ = [puzzle, solution.solution]
            sexp = clvm.to_sexp_f(code_)

            # Get AGGSIG conditions
            err, con, cost = conditions_for_solution(sexp)
            if err or not con:
                self.log.error(f"Sign transcation failed, con:{con}, error: {err}")
                return None

            conditions_dict = conditions_by_opcode(con)

            # Create signature
            for pk_message in hash_key_pairs_for_conditions_dict(
                conditions_dict, bytes(solution.coin)
            ):
                signature = secretkey.sign(pk_message.message_hash)
                signatures.append(signature)

        # Aggregate signatures
        aggsig = BLSSignature.aggregate(signatures)
        solution_list: List[CoinSolution] = [
            CoinSolution(
                coin_solution.coin, clvm.to_sexp_f([puzzle, coin_solution.solution])
            )
            for (puzzle, coin_solution) in spends
        ]
        spend_bundle = SpendBundle(solution_list, aggsig)

        return spend_bundle

    async def generate_signed_transaction_dict(
        self, data: Dict[str, Any]
    ) -> Optional[TransactionRecord]:
        """ Use this to generate transaction. """
        # Check that both are integers
        if not isinstance(data["amount"], int) or not isinstance(data["amount"], int):
            raise ValueError("An integer amount or fee is required (too many decimals)")
        amount = uint64(data["amount"])

        if "fee" in data:
            fee = uint64(data["fee"])
        else:
            fee = uint64(0)

        puzzle_hash = bytes32(bytes.fromhex(data["puzzle_hash"]))

        return await self.generate_signed_transaction(amount, puzzle_hash, fee)

    async def generate_signed_transaction(
        self,
        amount: uint64,
        puzzle_hash: bytes32,
        fee: uint64 = uint64(0),
        origin_id: bytes32 = None,
        coins: Set[Coin] = None,
    ) -> Optional[TransactionRecord]:
        """ Use this to generate transaction. """

        transaction = await self.generate_unsigned_transaction(
            amount, puzzle_hash, fee, origin_id, coins
        )
        if len(transaction) == 0:
            self.log.info("Unsigned transaction not generated")
            return None

        self.log.info("About to sign a transaction")
        spend_bundle: Optional[SpendBundle] = await self.sign_transaction(transaction)
        if spend_bundle is None:
            return None

        now = uint64(int(time.time()))
        add_list: List[Coin] = []
        rem_list: List[Coin] = []

        for add in spend_bundle.additions():
            add_list.append(add)
        for rem in spend_bundle.removals():
            rem_list.append(rem)

        tx_record = TransactionRecord(
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
            wallet_id=self.wallet_info.id,
            sent_to=[],
        )

        return tx_record

    async def push_transaction(self, tx: TransactionRecord) -> None:
        """ Use this API to send transactions. """
        await self.wallet_state_manager.add_pending_transaction(tx)

    # This is also defined in CCWallet as get_sigs()
    # I think this should be a the default way the wallet gets signatures in sign_transaction()
    async def get_sigs_for_innerpuz_with_innersol(
        self, innerpuz: Program, innersol: Program
    ) -> List[BLSSignature]:
        puzzle_hash = innerpuz.get_tree_hash()
        pubkey, private = await self.wallet_state_manager.get_keys(puzzle_hash)
        private = BLSPrivateKey(private)
        sigs: List[BLSSignature] = []
        code_ = [innerpuz, innersol]
        sexp = Program.to(code_)
        error, conditions, cost = conditions_dict_for_solution(sexp)
        if conditions is not None:
            for _ in hash_key_pairs_for_conditions_dict(conditions):
                signature = private.sign(_.message_hash)
                sigs.append(signature)
        return sigs

        # Create an offer spend bundle for chia given an amount of relative change (i.e -400 or 1000)

    # This is to be aggregated together with a coloured coin offer to ensure that the trade happens
    async def create_spend_bundle_relative_chia(
        self, chia_amount: int, exclude: List[Coin]
    ):
        list_of_solutions = []
        utxos = None

        # If we're losing value then get coins with at least that much value
        # If we're gaining value then our amount doesn't matter
        if chia_amount < 0:
            utxos = await self.select_coins(abs(chia_amount), exclude)
        else:
            utxos = await self.select_coins(0, exclude)

        if utxos is None:
            return None

        # Calculate output amount given sum of utxos
        spend_value = sum([coin.amount for coin in utxos])
        chia_amount = spend_value + chia_amount

        # Create coin solutions for each utxo
        output_created = None
        sigs: List[BLSSignature] = []
        for coin in utxos:
            pubkey, secretkey = await self.wallet_state_manager.get_keys(
                coin.puzzle_hash
            )
            puzzle = self.puzzle_for_pk(bytes(pubkey))
            if output_created is None:
                newpuzhash = await self.get_new_puzzlehash()
                primaries = [{"puzzlehash": newpuzhash, "amount": chia_amount}]
                solution = self.make_solution(primaries=primaries)
                output_created = coin
            else:
                solution = self.make_solution(consumed=[output_created.name()])
            list_of_solutions.append(
                CoinSolution(coin, clvm.to_sexp_f([puzzle, solution]))
            )
            new_sigs = await self.get_sigs_for_innerpuz_with_innersol(puzzle, solution)
            sigs = sigs + new_sigs

        aggsig = BLSSignature.aggregate(sigs)
        spend_bundle = SpendBundle(list_of_solutions, aggsig)
        return spend_bundle
