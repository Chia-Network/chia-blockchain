from typing import Dict, Optional, List, Set, Tuple

import clvm
from blspy import ExtendedPrivateKey, PublicKey
import logging

import src.protocols.wallet_protocol
from src.full_node import OutboundMessageGenerator
from src.protocols.wallet_protocol import ProofHash
from src.server.outbound_message import OutboundMessage, NodeType, Message, Delivery
from src.server.server import ChiaServer
from src.types.hashable.Coin import Coin
from src.types.hashable.CoinSolution import CoinSolution
from src.types.hashable.Program import Program
from src.types.hashable.SpendBundle import SpendBundle
from src.types.sized_bytes import bytes32
from src.util.Hash import std_hash
from src.util.api_decorators import api_request
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.puzzles.p2_conditions import puzzle_for_conditions
from src.wallet.puzzles.p2_delegated_puzzle import puzzle_for_pk
from src.wallet.puzzles.puzzle_utils import make_assert_my_coin_id_condition, make_assert_time_exceeds_condition, \
    make_assert_coin_consumed_condition, make_create_coin_condition


class Wallet:
    private_key: ExtendedPrivateKey
    key_config: Dict
    config: Dict
    server: ChiaServer
    next_address: int = 0
    pubkey_num_lookup: Dict[bytes, int]
    tmp_balance: int
    tmp_coins: Set[Coin]

    def __init__(self, config: Dict, key_config: Dict, name: str = None):
        print("init wallet")
        self.config = config
        self.key_config = key_config
        sk_hex = self.key_config["wallet_sk"]
        self.private_key = ExtendedPrivateKey.from_bytes(bytes.fromhex(sk_hex))
        if name:
            self.log = logging.getLogger(name)
        else:
            self.log = logging.getLogger(__name__)

        self.pubkey_num_lookup = {}
        self.tmp_balance = 0
        self.tmp_utxos = set()

    def get_next_public_key(self) -> PublicKey:
        pubkey = self.private_key.public_child(
            self.next_address).get_public_key()
        self.pubkey_num_lookup[pubkey.serialize()] = self.next_address
        self.next_address = self.next_address + 1
        return pubkey

    def can_generate_puzzle_hash(self, hash: bytes32) -> bool:
        return any(map(lambda child: hash == puzzle_for_pk(
            self.private_key.public_child(child).get_public_key().serialize()).get_hash(),
            reversed(range(self.next_address))))

    def puzzle_for_pk(self, pubkey) -> Program:
        return puzzle_for_pk(pubkey)

    def get_new_puzzle(self) -> Program:
        pubkey: bytes = self.get_next_public_key().serialize()
        puzzle: Program = puzzle_for_pk(pubkey)
        return puzzle

    def get_new_puzzlehash(self) -> bytes32:
        puzzle: Program = self.get_new_puzzle()
        puzzlehash: bytes32 = puzzle.get_hash()
        return puzzlehash

    def select_coins(self, amount) -> Optional[Set[Coin]]:
        if amount > self.tmp_balance:
            return None
        used_coins: Set[Coin] = set()
        while sum(map(lambda coin: coin.amount, used_coins)) < amount:
            used_coins.add(self.tmp_utxos.pop())
        return used_coins

    def set_server(self, server: ChiaServer):
        self.server = server

    def sign(self, value: bytes32, pubkey: PublicKey):
        private_key = self.private_key.private_child(
            self.pubkey_num_lookup[pubkey]).get_private_key()
        bls_key = BLSPrivateKey(private_key)
        return bls_key.sign(value)

    def make_solution(self, primaries=[], min_time=0, me={}, consumed=[]):
        ret = []
        for primary in primaries:
            ret.append(make_create_coin_condition(
                primary['puzzlehash'], primary['amount']))
        for coin in consumed:
            ret.append(make_assert_coin_consumed_condition(coin))
        if min_time > 0:
            ret.append(make_assert_time_exceeds_condition(min_time))
        if me:
            ret.append(make_assert_my_coin_id_condition(me['id']))
        return clvm.to_sexp_f([puzzle_for_conditions(ret), []])

    def get_keys(self, hash: bytes32) -> Optional[Tuple[PublicKey, ExtendedPrivateKey]]:
        for child in range(self.next_address):
            pubkey = self.private_key.public_child(
                child).get_public_key()
            if hash == puzzle_for_pk(pubkey.serialize()).get_hash():
                return pubkey, self.private_key.private_child(child).get_private_key()
        return None

    def generate_unsigned_transaction(self, amount: int, newpuzzlehash: bytes32, fee: int = 0) -> List[Tuple[Program, CoinSolution]]:
        if self.tmp_balance < amount:
            return None
        utxos = self.select_coins(amount + fee)
        spends: List[Tuple[Program, CoinSolution]] = []
        output_created = False
        spend_value = sum([coin.amount for coin in utxos])
        change = spend_value - amount - fee
        for coin in utxos:
            puzzle_hash = coin.puzzle_hash

            pubkey, secretkey = self.get_keys(puzzle_hash)
            puzzle: Program = puzzle_for_pk(pubkey.serialize())
            if output_created is False:
                primaries = [{'puzzlehash': newpuzzlehash, 'amount': amount}]
                if change > 0:
                    changepuzzlehash = self.get_new_puzzlehash()
                    primaries.append(
                        {'puzzlehash': changepuzzlehash, 'amount': change})
                    # add change coin into temp_utxo set
                    self.tmp_utxos.add(Coin(coin, changepuzzlehash, change))
                solution = self.make_solution(primaries=primaries)
                output_created = True
            else:
                solution = self.make_solution(consumed=[coin.name()])
            spends.append((puzzle, CoinSolution(coin, solution)))
        self.tmp_balance -= (amount + fee)
        return spends

    async def _on_connect(self) -> OutboundMessageGenerator:
        """
        Whenever we connect to a FullNode we request new proof_hashes by sending last proof hash we have
        """
        self.log.info(f"Requesting proof hashes")
        request = ProofHash(std_hash(b"deadbeef"))
        yield OutboundMessage(
            NodeType.FULL_NODE, Message("request_proof_hashes", request), Delivery.BROADCAST
        )

    @api_request
    async def proof_hash(self, request: src.protocols.wallet_protocol.ProofHash) -> OutboundMessageGenerator:
        """
        Received a proof hash from the FullNode
        """
        self.log.info(f"Received a new proof hash: {request}")
        reply_request = ProofHash(std_hash(b"a"))
        # TODO Store and decide if we want full proof for this proof hash
        yield OutboundMessage(
            NodeType.FULL_NODE, Message("request_full_proof_for_hash", reply_request), Delivery.RESPOND
        )

    @api_request
    async def full_proof_for_hash(self, request: src.protocols.wallet_protocol.FullProofForHash):
        """
        We've received a full proof for hash we requested
        """
        # TODO Validate full proof
        self.log.info(f"Received new proof: {request}")

    async def send_transaction(self, spend_bundle: SpendBundle):
        msg = OutboundMessage(
            NodeType.FULL_NODE,
            Message("wallet_transaction", spend_bundle),
            Delivery.BROADCAST,
        )
        async for reply in self.server.push_message(msg):
            self.log.info(reply)

    @api_request
    async def transaction_ack(self, id: bytes32):
        # TODO Remove from retry queue
        print(f"tx has been received by the fullnode {}")
