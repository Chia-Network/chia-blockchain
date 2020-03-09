from typing import Dict, Optional, List, Tuple, Set
import clvm
from blspy import ExtendedPrivateKey, PublicKey
import logging
from src.server.outbound_message import OutboundMessage, NodeType, Message, Delivery
from src.server.server import ChiaServer
from src.protocols import full_node_protocol
from src.types.hashable.BLSSignature import BLSSignature
from src.types.hashable.coin import Coin
from src.types.hashable.coin_solution import CoinSolution
from src.types.hashable.program import Program
from src.types.hashable.spend_bundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.condition_tools import (
    conditions_for_solution,
    conditions_by_opcode,
    hash_key_pairs_for_conditions_dict,
)
from src.util.ints import uint64
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.puzzles.p2_conditions import puzzle_for_conditions
from src.wallet.puzzles.p2_delegated_puzzle import puzzle_for_pk
from src.wallet.puzzles.puzzle_utils import (
    make_assert_my_coin_id_condition,
    make_assert_time_exceeds_condition,
    make_assert_coin_consumed_condition,
    make_create_coin_condition,
)
from src.wallet.util.wallet_types import WalletType

from src.wallet.wallet_state_manager import WalletStateManager


class Wallet:
    private_key: ExtendedPrivateKey
    key_config: Dict
    config: Dict
    server: Optional[ChiaServer]
    wallet_state_manager: WalletStateManager

    log: logging.Logger

    # TODO Don't allow user to send tx until wallet is synced
    synced: bool

    @staticmethod
    async def create(
        config: Dict,
        key_config: Dict,
        wallet_state_manager: WalletStateManager,
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

        self.server = None

        return self

    def get_public_key(self, index) -> PublicKey:
        pubkey = self.private_key.public_child(index).get_public_key()
        return pubkey

    async def get_confirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_confirmed_balance()

    async def get_unconfirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_unconfirmed_balance()

    async def can_generate_puzzle_hash(self, hash: bytes32) -> bool:
        return await self.wallet_state_manager.puzzle_store.puzzle_hash_exists(hash)

    def puzzle_for_pk(self, pubkey) -> Program:
        return puzzle_for_pk(pubkey)

    async def get_new_puzzlehash(self) -> bytes32:
        index = await self.wallet_state_manager.puzzle_store.get_max_derivation_path()
        index += 1
        pubkey: bytes = self.get_public_key(index).serialize()
        puzzle: Program = self.puzzle_for_pk(pubkey)
        puzzlehash: bytes32 = puzzle.get_hash()

        await self.wallet_state_manager.puzzle_store.add_derivation_path_of_interest(
            index, puzzlehash, pubkey, WalletType.STANDARD_WALLET
        )

        return puzzlehash

    def set_server(self, server: ChiaServer):
        self.server = server

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
            raise
        pubkey = self.private_key.public_child(index_for_puzzlehash).get_public_key()
        private = self.private_key.private_child(index_for_puzzlehash).get_private_key()
        return pubkey, private

    async def generate_unsigned_transaction(
        self, amount: int, newpuzzlehash: bytes32, fee: int = 0
    ) -> List[Tuple[Program, CoinSolution]]:
        """
        Generates a unsigned transaction in form of List(Puzzle, Solutions)
        """
        utxos: Optional[Set[Coin]] = await self.wallet_state_manager.select_coins(
            amount + fee
        )
        if utxos is None:
            return []

        spend_value = sum([coin.amount for coin in utxos])
        change = spend_value - amount - fee

        spends: List[Tuple[Program, CoinSolution]] = []
        output_created = False

        for coin in utxos:
            # Get keys for puzzle_hash
            puzzle_hash = coin.puzzle_hash
            maybe = await self.get_keys(puzzle_hash)
            if not maybe:
                return []

            # Get puzzle for pubkey
            pubkey, secretkey = maybe
            puzzle: Program = puzzle_for_pk(pubkey.serialize())

            # Only one coin creates outputs
            if output_created is False:
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
        return spends

    async def sign_transaction(self, spends: List[Tuple[Program, CoinSolution]]):
        signatures = []
        for puzzle, solution in spends:
            # Get keys
            keys = await self.get_keys(solution.coin.puzzle_hash)
            if not keys:
                return None
            pubkey, secretkey = keys
            secretkey = BLSPrivateKey(secretkey)

            code_ = [puzzle, solution.solution]
            sexp = clvm.to_sexp_f(code_)

            # Get AGGSIG conditions
            err, con, cost = conditions_for_solution(sexp)
            if err or not con:
                return None
            conditions_dict = conditions_by_opcode(con)

            # Create signature
            for pk_message in hash_key_pairs_for_conditions_dict(conditions_dict):
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

    async def generate_signed_transaction(
        self, amount, newpuzzlehash, fee: int = 0
    ) -> Optional[SpendBundle]:
        """ Use this to generate transaction. """
        transaction = await self.generate_unsigned_transaction(
            amount, newpuzzlehash, fee
        )
        if len(transaction) == 0:
            return None
        return await self.sign_transaction(transaction)

    async def push_transaction(self, spend_bundle: SpendBundle):
        """ Use this API to send transactions. """
        await self.wallet_state_manager.add_pending_transaction(spend_bundle)
        await self._send_transaction(spend_bundle)

    async def _send_transaction(self, spend_bundle: SpendBundle):
        if self.server:
            msg = OutboundMessage(
                NodeType.FULL_NODE,
                Message(
                    "respond_transaction",
                    full_node_protocol.RespondTransaction(spend_bundle),
                ),
                Delivery.BROADCAST,
            )
            self.server.push_message(msg)
