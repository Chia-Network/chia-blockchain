from typing import Dict, Optional, List, Tuple
import clvm
from blspy import ExtendedPrivateKey, PublicKey
import logging
from src.server.outbound_message import OutboundMessage, NodeType, Message, Delivery
from src.server.server import ChiaServer
from src.protocols import full_node_protocol
from src.types.hashable.BLSSignature import BLSSignature
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

from src.wallet.wallet_state_manager import WalletStateManager


class Wallet:
    private_key: ExtendedPrivateKey
    key_config: Dict
    config: Dict
    server: Optional[ChiaServer]
    next_address: int = 0
    pubkey_num_lookup: Dict[bytes, int]
    wallet_state_manager: WalletStateManager

    log: logging.Logger

    # TODO Don't allow user to send tx until wallet is synced
    synced: bool

    # Queue of SpendBundles that FullNode hasn't acked yet.
    send_queue: Dict[bytes32, SpendBundle]

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
        self.pubkey_num_lookup = {}

        self.server = None

        return self

    def get_next_public_key(self) -> PublicKey:
        pubkey = self.private_key.public_child(self.next_address).get_public_key()
        self.pubkey_num_lookup[pubkey.serialize()] = self.next_address
        self.next_address = self.next_address + 1
        self.wallet_state_manager.next_address = self.next_address
        return pubkey

    async def get_confirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_confirmed_balance()

    async def get_unconfirmed_balance(self) -> uint64:
        return await self.wallet_state_manager.get_unconfirmed_balance()

    def can_generate_puzzle_hash(self, hash: bytes32) -> bool:
        return any(
            map(
                lambda child: hash
                == puzzle_for_pk(
                    self.private_key.public_child(child).get_public_key().serialize()
                ).get_hash(),
                reversed(range(self.next_address)),
            )
        )

    def puzzle_for_pk(self, pubkey) -> Program:
        return puzzle_for_pk(pubkey)

    def get_new_puzzle(self) -> Program:
        pubkey: bytes = self.get_next_public_key().serialize()
        puzzle: Program = puzzle_for_pk(pubkey)
        return puzzle

    def get_new_puzzlehash(self) -> bytes32:
        puzzle: Program = self.get_new_puzzle()
        puzzlehash: bytes32 = puzzle.get_hash()
        self.wallet_state_manager.puzzlehash_set.add(puzzlehash)
        return puzzlehash

    def set_server(self, server: ChiaServer):
        self.server = server

    def sign(self, value: bytes32, pubkey: PublicKey):
        private_key = self.private_key.private_child(
            self.pubkey_num_lookup[pubkey]
        ).get_private_key()
        bls_key = BLSPrivateKey(private_key)
        return bls_key.sign(value)

    def make_solution(self, primaries=None, min_time=0, me=None, consumed=None):
        ret = []
        if primaries:
            for primary in primaries:
                ret.append(
                    make_create_coin_condition(primary["puzzlehash"], primary["amount"])
                )
        if consumed:
            for coin in consumed:
                ret.append(make_assert_coin_consumed_condition(coin))
        if min_time > 0:
            ret.append(make_assert_time_exceeds_condition(min_time))
        if me:
            ret.append(make_assert_my_coin_id_condition(me["id"]))
        return clvm.to_sexp_f([puzzle_for_conditions(ret), []])

    def get_keys(self, hash: bytes32) -> Optional[Tuple[PublicKey, ExtendedPrivateKey]]:
        for child in range(self.next_address):
            pubkey = self.private_key.public_child(child).get_public_key()
            if hash == puzzle_for_pk(pubkey.serialize()).get_hash():
                return pubkey, self.private_key.private_child(child).get_private_key()
        return None

    async def generate_unsigned_transaction(
        self, amount: int, newpuzzlehash: bytes32, fee: int = 0
    ) -> List[Tuple[Program, CoinSolution]]:
        utxos = await self.wallet_state_manager.select_coins(amount + fee)
        if utxos is None:
            return []
        spends: List[Tuple[Program, CoinSolution]] = []
        output_created = False
        spend_value = sum([coin.amount for coin in utxos])
        change = spend_value - amount - fee
        for coin in utxos:
            puzzle_hash = coin.puzzle_hash
            maybe = self.get_keys(puzzle_hash)
            if not maybe:
                return []
            pubkey, secretkey = maybe
            puzzle: Program = puzzle_for_pk(pubkey.serialize())
            if output_created is False:
                primaries = [{"puzzlehash": newpuzzlehash, "amount": amount}]
                if change > 0:
                    changepuzzlehash = self.get_new_puzzlehash()
                    primaries.append({"puzzlehash": changepuzzlehash, "amount": change})

                solution = self.make_solution(primaries=primaries)
                output_created = True
            else:
                solution = self.make_solution(consumed=[coin.name()])
            spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    def sign_transaction(self, spends: List[Tuple[Program, CoinSolution]]):
        sigs = []
        for puzzle, solution in spends:
            keys = self.get_keys(solution.coin.puzzle_hash)
            if not keys:
                return None
            pubkey, secretkey = keys
            secretkey = BLSPrivateKey(secretkey)
            code_ = [puzzle, solution.solution]
            sexp = clvm.to_sexp_f(code_)
            err, con, cost = conditions_for_solution(sexp)
            if err or not con:
                return None
            conditions_dict = conditions_by_opcode(con)

            for _ in hash_key_pairs_for_conditions_dict(conditions_dict):
                signature = secretkey.sign(_.message_hash)
                sigs.append(signature)
        aggsig = BLSSignature.aggregate(sigs)
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
        return self.sign_transaction(transaction)

    async def push_transaction(self, spend_bundle: SpendBundle):
        """ Use this API to send transactions. """
        await self.wallet_state_manager.add_pending_transaction(spend_bundle)
        await self._send_transaction(spend_bundle)

    async def _send_transaction(self, spend_bundle: SpendBundle):
        if self.server:
            msg = OutboundMessage(
                NodeType.FULL_NODE,
                Message("respond_transaction", full_node_protocol.RespondTransaction(spend_bundle)),
                Delivery.BROADCAST,
            )
            async for reply in self.server.push_message(msg):
                self.log.info(reply)
