from pathlib import Path
from typing import Dict, Optional, List, Set, Tuple
import clvm
from blspy import ExtendedPrivateKey, PublicKey
import logging
import src.protocols.wallet_protocol
from src.full_node import OutboundMessageGenerator
from src.protocols.wallet_protocol import ProofHash
from src.protocols.full_node_protocol import RespondTransaction
from src.server.outbound_message import OutboundMessage, NodeType, Message, Delivery
from src.server.server import ChiaServer
from src.types.full_block import additions_for_npc
from src.types.hashable.BLSSignature import BLSSignature
from src.types.hashable.Coin import Coin
from src.types.hashable.CoinRecord import CoinRecord
from src.types.hashable.CoinSolution import CoinSolution
from src.types.hashable.Program import Program
from src.types.hashable.SpendBundle import SpendBundle
from src.types.name_puzzle_condition import NPC
from src.types.sized_bytes import bytes32
from src.util.hash import std_hash
from src.util.api_decorators import api_request
from src.util.condition_tools import (
    conditions_for_solution,
    conditions_by_opcode,
    hash_key_pairs_for_conditions_dict,
)
from src.util.ints import uint32, uint64
from src.util.mempool_check_conditions import get_name_puzzle_conditions
from src.wallet.BLSPrivateKey import BLSPrivateKey
from src.wallet.puzzles.p2_conditions import puzzle_for_conditions
from src.wallet.puzzles.p2_delegated_puzzle import puzzle_for_pk
from src.wallet.puzzles.puzzle_utils import (
    make_assert_my_coin_id_condition,
    make_assert_time_exceeds_condition,
    make_assert_coin_consumed_condition,
    make_create_coin_condition,
)
from src.wallet.wallet_store import WalletStore


class Wallet:
    private_key: ExtendedPrivateKey
    key_config: Dict
    config: Dict
    server: Optional[ChiaServer]
    next_address: int = 0
    pubkey_num_lookup: Dict[bytes, int]
    tmp_coins: Set[Coin]
    wallet_store: WalletStore
    header_hash: List[bytes32]
    start_index: int

    unconfirmed_removals: Set[Coin]
    unconfirmed_removal_amount: int

    unconfirmed_additions: Set[Coin]
    unconfirmed_addition_amount: int

    # This dict maps coin_id to SpendBundle, it will contain duplicate values by design
    coin_spend_bundle_map: Dict[bytes32, SpendBundle]

    # Spendbundle_ID : Spendbundle
    pending_spend_bundles: Dict[bytes32, SpendBundle]
    log: logging.Logger

    # TODO Don't allow user to send tx until wallet is synced
    synced: bool

    # Queue of SpendBundles that FullNode hasn't acked yet.
    send_queue: Dict[bytes32, SpendBundle]

    @staticmethod
    async def create(config: Dict, key_config: Dict, name: str = None):
        self = Wallet()
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
        self.tmp_coins = set()
        pub_hex = self.private_key.get_public_key().serialize().hex()
        path = Path(f"wallet_db_{pub_hex}.db")
        self.wallet_store = await WalletStore.create(path)
        self.header_hash = []
        self.unconfirmed_additions = set()
        self.unconfirmed_removals = set()
        self.pending_spend_bundles = {}
        self.coin_spend_bundle_map = {}
        self.unconfirmed_addition_amount = 0
        self.unconfirmed_removal_amount = 0

        self.synced = False

        self.send_queue = {}
        self.server = None

        return self

    def get_next_public_key(self) -> PublicKey:
        pubkey = self.private_key.public_child(self.next_address).get_public_key()
        self.pubkey_num_lookup[pubkey.serialize()] = self.next_address
        self.next_address = self.next_address + 1
        return pubkey

    async def get_confirmed_balance(self) -> uint64:
        record_list: Set[
            CoinRecord
        ] = await self.wallet_store.get_coin_records_by_spent(False)
        amount: uint64 = uint64(0)

        for record in record_list:
            amount = uint64(amount + record.coin.amount)

        return uint64(amount)

    async def get_unconfirmed_balance(self) -> uint64:
        confirmed = await self.get_confirmed_balance()
        result = confirmed - self.unconfirmed_removal_amount + self.unconfirmed_addition_amount
        return uint64(result)

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
        return puzzlehash

    async def select_coins(self, amount) -> Optional[Set[Coin]]:

        if amount > await self.get_unconfirmed_balance():
            return None

        unspent: Set[
            CoinRecord
        ] = await self.wallet_store.get_coin_records_by_spent(False)
        sum = 0
        used_coins: Set = set()

        """
        Try to use coins from the store, if there isn't enough of "unused"
        coins use change coins that are not confirmed yet
        """
        for coinrecord in unspent:
            if sum >= amount:
                break
            if coinrecord.coin.name in self.unconfirmed_removals:
                continue
            sum += coinrecord.coin.amount
            used_coins.add(coinrecord.coin)

        """
        This happens when we couldn't use one of the coins because it's already used
        but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
        """
        if sum < amount:
            for coin in self.unconfirmed_additions:
                if sum > amount:
                    break
                if coin.name in self.unconfirmed_removals:
                    continue
                sum += coin.amount
                used_coins.add(coin)

        if sum >= amount:
            return used_coins
        else:
            # This shouldn't happen because of: if amount > self.get_unconfirmed_balance():
            return None

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
        utxos = await self.select_coins(amount + fee)
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
                    # add change coin into temp_utxo set
                    self.tmp_coins.add(Coin(coin.name(), changepuzzlehash, uint64(change)))
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
            err, con = conditions_for_solution(sexp)
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
        transaction = await self.generate_unsigned_transaction(
            amount, newpuzzlehash, fee
        )
        if len(transaction) == 0:
            return None
        return self.sign_transaction(transaction)

    async def coin_removed(self, coin_name: bytes32, index: uint32):
        self.log.info("remove coin")
        await self.wallet_store.set_spent(coin_name, index)

    async def coin_added(self, coin: Coin, index: uint32, coinbase: bool):
        self.log.info("add coin")
        coin_record: CoinRecord = CoinRecord(coin, index, uint32(0), False, coinbase)
        await self.wallet_store.add_coin_record(coin_record)

    async def _on_connect(self) -> OutboundMessageGenerator:
        """
        Whenever we connect to a FullNode we request new proof_hashes by sending last proof hash we have
        """
        self.log.info(f"Requesting proof hashes")
        request = ProofHash(std_hash(b"deadbeef"))
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("request_proof_hashes", request),
            Delivery.BROADCAST,
        )

    @api_request
    async def proof_hash(
        self, request: src.protocols.wallet_protocol.ProofHash
    ) -> OutboundMessageGenerator:
        """
        Received a proof hash from the FullNode
        """
        self.log.info(f"Received a new proof hash: {request}")
        reply_request = ProofHash(std_hash(b"a"))
        # TODO Store and decide if we want full proof for this proof hash
        yield OutboundMessage(
            NodeType.FULL_NODE,
            Message("request_full_proof_for_hash", reply_request),
            Delivery.RESPOND,
        )

    @api_request
    async def full_proof_for_hash(
        self, request: src.protocols.wallet_protocol.FullProofForHash
    ):
        """
        We've received a full proof for hash we requested
        """
        # TODO Validate full proof
        self.log.info(f"Received new proof: {request}")

    @api_request
    async def received_body(self, response: src.protocols.wallet_protocol.RespondBody):
        """
        Called when body is received from the FullNode
        """

        # Retry sending queued up transactions
        await self.retry_send_queue()

        additions: List[Coin] = []

        if self.can_generate_puzzle_hash(response.body.coinbase.puzzle_hash):
            await self.coin_added(response.body.coinbase, response.height, True)
        if self.can_generate_puzzle_hash(response.body.fees_coin.puzzle_hash):
            await self.coin_added(response.body.fees_coin, response.height, True)

        npc_list: List[NPC]
        if response.body.transactions:
            error, npc_list, cost = await get_name_puzzle_conditions(
                response.body.transactions
            )

            additions.extend(additions_for_npc(npc_list))

            for added_coin in additions:
                if self.can_generate_puzzle_hash(added_coin.puzzle_hash):
                    await self.coin_added(added_coin, response.height, False)

            for npc in npc_list:
                if self.can_generate_puzzle_hash(npc.puzzle_hash):
                    await self.coin_removed(npc.coin_name, response.height)

    @api_request
    async def new_tip(self, header: src.protocols.wallet_protocol.Header):
        self.log.info("new tip received")

    async def retry_send_queue(self):
        for key, val in self.send_queue:
            await self._send_transaction(val)

    def remove_from_queue(self, spendbundle_id: bytes32):
        if spendbundle_id in self.send_queue:
            del self.send_queue[spendbundle_id]

    async def push_transaction(self, spend_bundle: SpendBundle):
        """ Use this API to make transactions. """
        self.send_queue[spend_bundle.name()] = spend_bundle
        additions: List[Coin] = spend_bundle.additions()
        removals: List[Coin] = spend_bundle.removals()

        addition_amount = 0
        for coin in additions:
            if self.can_generate_puzzle_hash(coin.puzzle_hash):
                self.unconfirmed_additions.add(coin)
                self.coin_spend_bundle_map[coin.name()] = spend_bundle
                addition_amount += coin.amount

        removal_amount = 0
        for coin in removals:
            self.unconfirmed_removals.add(coin)
            self.coin_spend_bundle_map[coin.name()] = spend_bundle
            removal_amount += coin.amount

        # Update unconfirmed state
        self.unconfirmed_removal_amount += removal_amount
        self.unconfirmed_addition_amount += addition_amount

        self.pending_spend_bundles[spend_bundle.name()] = spend_bundle
        await self._send_transaction(spend_bundle)

    async def _send_transaction(self, spend_bundle: SpendBundle):
        """ Sends spendbundle to connected full Nodes."""

        msg = OutboundMessage(
            NodeType.FULL_NODE,
            Message("respond_transaction", RespondTransaction(spend_bundle)),
            Delivery.BROADCAST,
        )
        if self.server:
            async for reply in self.server.push_message(msg):
                self.log.info(reply)

    @api_request
    async def transaction_ack(self, ack: src.protocols.wallet_protocol.TransactionAck):
        if ack.status:
            self.remove_from_queue(ack.txid)
            self.log.info(f"SpendBundle has been received by the FullNode. id: {id}")
        else:
            self.log.info(f"SpendBundle has been rejected by the FullNode. id: {id}")

    async def requestLCA(self):
        msg = OutboundMessage(
            NodeType.FULL_NODE, Message("request_lca", None), Delivery.BROADCAST,
        )
        async for reply in self.server.push_message(msg):
            self.log.info(reply)
