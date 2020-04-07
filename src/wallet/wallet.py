from typing import Dict, Optional, List, Tuple, Set, Any
import clvm
from blspy import ExtendedPrivateKey, PublicKey
import logging
from src.types.BLSSignature import BLSSignature
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.program import Program
from src.types.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.condition_tools import (
    conditions_for_solution,
    conditions_by_opcode,
    hash_key_pairs_for_conditions_dict,
)
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.util.ints import uint64, uint32
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.puzzles.p2_conditions import puzzle_for_conditions
from src.wallet.puzzles.p2_delegated_puzzle import puzzle_for_pk
from src.wallet.puzzles.puzzle_utils import (
    make_assert_my_coin_id_condition,
    make_assert_time_exceeds_condition,
    make_assert_coin_consumed_condition,
    make_create_coin_condition,
)
from src.wallet.wallet_coin_record import WalletCoinRecord
from src.wallet.transaction_record import TransactionRecord
from src.wallet.wallet_info import WalletInfo


class Wallet:
    private_key: ExtendedPrivateKey
    key_config: Dict
    config: Dict
    wallet_state_manager: Any

    log: logging.Logger

    wallet_info: WalletInfo

    @staticmethod
    async def create(
        config: Dict,
        key_config: Dict,
        wallet_state_manager: Any,
        info: WalletInfo,
        name: str = None,
    ):
        self = Wallet()
        self.config = config
        self.key_config = key_config
        sk_hex = self.key_config["wallet_sk"]
        self.private_key = ExtendedPrivateKey.from_bytes(bytes.fromhex(sk_hex))
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.wallet_state_manager = wallet_state_manager

        self.wallet_info = info

        return self

    def get_public_key(self, index: uint32) -> PublicKey:
        pubkey = self.private_key.public_child(index).get_public_key()
        return pubkey

    async def get_confirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_confirmed_balance_for_wallet(
            self.wallet_info.id
        )

    async def get_unconfirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_unconfirmed_balance(
            self.wallet_info.id
        )

    async def can_generate_puzzle_hash(self, hash: bytes32) -> bool:
        return await self.wallet_state_manager.puzzle_store.puzzle_hash_exists(hash)

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        return puzzle_for_pk(pubkey)

    async def get_new_puzzlehash(self) -> bytes32:
        return (
            await self.wallet_state_manager.get_unused_derivation_record(
                self.wallet_info.id
            )
        ).puzzle_hash

    def make_solution(self, primaries=None, min_time=0, me=None, consumed=None):
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
        return clvm.to_sexp_f([puzzle_for_conditions(condition_list), []])

    async def get_keys(
        self, hash: bytes32
    ) -> Optional[Tuple[PublicKey, ExtendedPrivateKey]]:
        index_for_puzzlehash = await self.wallet_state_manager.puzzle_store.index_for_puzzle_hash(
            hash
        )
        if index_for_puzzlehash == -1:
            raise ValueError(f"No key for this puzzlehash {hash})")
        pubkey = self.private_key.public_child(index_for_puzzlehash).get_public_key()
        private = self.private_key.private_child(index_for_puzzlehash).get_private_key()
        return pubkey, private

    async def select_coins(self, amount) -> Optional[Set[Coin]]:
        """ Returns a set of coins that can be used for generating a new transaction. """
        spendable_am = await self.wallet_state_manager.get_unconfirmed_spendable_for_wallet(
            self.wallet_info.id
        )

        if amount > spendable_am:
            self.log.warning(
                f"Can't select amount higher than our spendable balance {amount}, spendable {spendable_am}"
            )
            return None

        self.log.info(f"About to select coins for amount {amount}")
        unspent: Set[
            WalletCoinRecord
        ] = await self.wallet_state_manager.get_spendable_coins_for_wallet(
            self.wallet_info.id
        )
        sum = 0
        used_coins: Set = set()

        # Try to use coins from the store, if there isn't enough of "unused"
        # coins use change coins that are not confirmed yet
        unconfirmed_removals: Dict[
            bytes32, Coin
        ] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.wallet_info.id
        )
        for coinrecord in unspent:
            if sum >= amount:
                break
            if coinrecord.coin.name() in unconfirmed_removals:
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
            self.log.info(f"coins is None")
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
            maybe = await self.get_keys(puzzle_hash)
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

                solution = self.make_solution(primaries=primaries)
                output_created = True
            elif output_created is False and origin_id == coin.name():
                primaries = [{"puzzlehash": newpuzzlehash, "amount": amount}]
                if change > 0:
                    changepuzzlehash = await self.get_new_puzzlehash()
                    primaries.append({"puzzlehash": changepuzzlehash, "amount": change})

                solution = self.make_solution(primaries=primaries)
                output_created = True
            else:
                # TODO coin consumed condition should be removed
                solution = self.make_solution(consumed=[coin.name()])

            spends.append((puzzle, CoinSolution(coin, solution)))

        self.log.info(f"Spends is {spends}")
        return spends

    async def sign_transaction(
        self, spends: List[Tuple[Program, CoinSolution]]
    ) -> Optional[SpendBundle]:
        signatures = []
        for puzzle, solution in spends:
            # Get keys
            keys = await self.get_keys(solution.coin.puzzle_hash)
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
    ) -> Optional[SpendBundle]:
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
    ) -> Optional[SpendBundle]:
        """ Use this to generate transaction. """

        transaction = await self.generate_unsigned_transaction(
            amount, puzzle_hash, fee, origin_id, coins
        )
        if len(transaction) == 0:
            self.log.info("Unsigned transaction not generated")
            return None

        self.log.info("About to sign a transaction")
        return await self.sign_transaction(transaction)

    async def get_transaction_status(
        self, tx_id: SpendBundle
    ) -> List[Tuple[str, MempoolInclusionStatus, Optional[str]]]:
        tr: Optional[
            TransactionRecord
        ] = await self.wallet_state_manager.get_transaction(tx_id)
        ret_list = []
        if tr is not None:
            for (name, ss, err) in tr.sent_to:
                ret_list.append((name, MempoolInclusionStatus(ss), err))
        return ret_list

    async def push_transaction(self, spend_bundle: SpendBundle) -> None:
        """ Use this API to send transactions. """
        await self.wallet_state_manager.add_pending_transaction(
            spend_bundle, self.wallet_info.id
        )
