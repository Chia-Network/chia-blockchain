import json
import logging
import time
from dataclasses import dataclass
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Set, Type, TypeVar

from blspy import AugSchemeMPL, G1Element, G2Element
from clvm.casts import int_from_bytes

from chia.clvm.singleton import SINGLETON_TOP_LAYER_MOD
from chia.protocols.wallet_protocol import CoinState
from chia.server.outbound_message import NodeType
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet import nft_puzzles
from chia.wallet.nft_wallet.nft_puzzles import LAUNCHER_PUZZLE, NFT_STATE_LAYER_MOD_HASH
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    solution_for_conditions,
)
from chia.wallet.puzzles.puzzle_utils import make_create_coin_condition
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.debug_spend_bundle import disassemble
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from tests.wallet.nft_wallet.test_nft_clvm import NFT_METADATA_UPDATER

_T_NFTWallet = TypeVar("_T_NFTWallet", bound="NFTWallet")

OFFER_MOD = load_clvm("settlement_payments.clvm")


@streamable
@dataclass(frozen=True)
class NFTCoinInfo(Streamable):
    coin: Coin
    lineage_proof: LineageProof
    full_puzzle: Program


@streamable
@dataclass(frozen=True)
class NFTWalletInfo(Streamable):
    my_nft_coins: List[NFTCoinInfo]
    did_wallet_id: Optional[uint32] = None


def create_fullpuz(innerpuz: Program, genesis_id: bytes32) -> Program:
    mod_hash = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
    # singleton_struct = (MOD_HASH . (LAUNCHER_ID . LAUNCHER_PUZZLE_HASH))
    singleton_struct = Program.to((mod_hash, (genesis_id, LAUNCHER_PUZZLE.get_tree_hash())))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, innerpuz)


class NFTWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    nft_wallet_info: NFTWalletInfo
    standard_wallet: Wallet
    wallet_id: int

    @classmethod
    async def create_new_nft_wallet(
        cls: Type[_T_NFTWallet],
        wallet_state_manager: Any,
        wallet: Wallet,
        did_wallet_id: uint32 = None,
        name: str = "",
    ) -> _T_NFTWallet:
        """
        This must be called under the wallet state manager lock
        """
        self = cls()
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        self.nft_wallet_info = NFTWalletInfo([], did_wallet_id)
        info_as_string = json.dumps(self.nft_wallet_info.to_json_dict())

        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "NFT Wallet", uint32(WalletType.NFT.value), info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
        self.log.debug("Generated a new NFT wallet: %s", self.__dict__)
        # await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_id)
        if not did_wallet_id:
            # default profile wallet
            self.log.debug("Standard NFT wallet created")

        else:
            # TODO: handle DID wallet puzhash
            raise NotImplementedError()
        return self

    @classmethod
    async def create(
        cls: Type[_T_NFTWallet],
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = "",
    ) -> _T_NFTWallet:
        self = cls()
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.wallet_id = wallet_info.id
        self.standard_wallet = wallet
        self.wallet_info = wallet_info
        self.nft_wallet_info = NFTWalletInfo.from_json_dict(json.loads(wallet_info.data))
        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.NFT)

    async def get_new_puzzle(self) -> Program:
        self.log.debug("Getting new puzzle for NFT wallet: %s", self.id())
        return self.puzzle_for_pk((await self.wallet_state_manager.get_unused_derivation_record(self.id())).pubkey)

    def id(self) -> uint32:
        return self.wallet_info.id

    async def add_nft_coin(self, coin: Coin, spent_height: uint32, in_transaction: bool) -> None:
        await self.coin_added(coin, spent_height, in_transaction=in_transaction)

    async def coin_added(self, coin: Coin, height: uint32, in_transaction: bool) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"NFT wallet has been notified that {coin} was added")
        for coin_info in self.nft_wallet_info.my_nft_coins:
            if coin_info.coin == coin:
                return
        wallet_node = self.wallet_state_manager.wallet_node
        server = wallet_node.server
        full_nodes: Dict[bytes32, WSChiaConnection] = server.connection_by_type.get(NodeType.FULL_NODE, {})
        cs: Optional[CoinSpend] = None
        coin_states: Optional[List[CoinState]] = await self.wallet_state_manager.wallet_node.get_coin_state(
            [coin.parent_coin_info]
        )
        if not coin_states:
            # farm coin
            return
        assert coin_states
        parent_coin = coin_states[0].coin
        for node_id in full_nodes:
            node = server.all_connections[node_id]
            cs = await wallet_node.fetch_puzzle_solution(node, height, parent_coin)
            if cs is not None:
                break
        assert cs is not None
        await self.puzzle_solution_received(cs, in_transaction=in_transaction)

    async def puzzle_solution_received(self, coin_spend: CoinSpend, in_transaction: bool) -> None:
        coin_name = coin_spend.coin.name()
        puzzle: Program = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
        solution: Program = Program.from_bytes(bytes(coin_spend.solution)).rest().rest().first().first()
        matched, singleton_curried_args, curried_args = nft_puzzles.match_nft_puzzle(puzzle)
        if matched:
            (_, metadata, metadata_updater_puzzle_hash, inner_puzzle) = curried_args
            params = singleton_curried_args.first()
            self.log.info(f"found the info for NFT coin {coin_name} {inner_puzzle} {params}")
            singleton_id = bytes32(params.rest().first().atom)
            new_inner_puzzle = inner_puzzle
            puzhash = None
            self.log.debug("Before spend metadata: %s %s \n%s", metadata, singleton_id, disassemble(solution))
            for condition in solution.rest().first().rest().as_iter():
                self.log.debug("Checking solution condition: %s", disassemble(condition))
                if condition.list_len() < 2:
                    # invalid condition
                    continue
                condition_code = int_from_bytes(condition.first().atom)
                self.log.debug("Checking condition code: %r", condition_code)
                if condition_code == -24:
                    # metadata update
                    # (-24 (meta updater puzzle) url)
                    metadata = condition.rest().rest().first() + metadata
                elif condition_code == 51:
                    puzhash = bytes32(condition.rest().first().atom)
                    record: DerivationRecord = (
                        await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(puzhash)
                    )
                    new_inner_puzzle = puzzle_for_pk(record.pubkey)

                else:
                    raise ValueError("Invalid condition")
            if new_inner_puzzle is None:
                raise ValueError("Invalid puzzle")
            parent_coin = None
            coin_record = await self.wallet_state_manager.coin_store.get_coin_record(coin_name)
            if coin_record is None:
                coin_states: Optional[List[CoinState]] = await self.wallet_state_manager.wallet_node.get_coin_state(
                    [coin_name]
                )
                if coin_states is not None:
                    parent_coin = coin_states[0].coin
            if coin_record is not None:
                parent_coin = coin_record.coin
            if parent_coin is None:
                raise ValueError("Error in finding parent")
            self.log.debug("Got back updated metadata: %s", metadata)
            child_puzzle: Program = nft_puzzles.create_full_puzzle(
                singleton_id,
                metadata,
                bytes32(metadata_updater_puzzle_hash.atom),
                new_inner_puzzle,
            )
            self.log.debug(
                "Created NFT full puzzle with inner: %s",
                nft_puzzles.create_full_puzzle_with_nft_puzzle(singleton_id, new_inner_puzzle),
            )
            self.log.debug(
                "Created NFT full puzzle with inner: %s",
                nft_puzzles.create_full_puzzle_with_nft_puzzle(singleton_id, inner_puzzle),
            )
            child_coin: Optional[Coin] = None
            for new_coin in coin_spend.additions():
                self.log.debug(
                    "Comparing addition: %s with %s, amount: %s ",
                    new_coin.puzzle_hash,
                    child_puzzle.get_tree_hash(),
                    new_coin.amount,
                )
                if new_coin.puzzle_hash == child_puzzle.get_tree_hash():
                    child_coin = new_coin
                    break
            else:
                raise ValueError("Invalid NFT spend on %r" % coin_name)

            await self.add_coin(
                child_coin,
                child_puzzle,
                LineageProof(parent_coin.parent_coin_info, inner_puzzle.get_tree_hash(), parent_coin.amount),
                in_transaction=in_transaction,
            )
        else:
            # The parent is not an NFT which means we need to scrub all of its children from our DB
            child_coin_records: List[
                WalletCoinRecord
            ] = await self.wallet_state_manager.coin_store.get_coin_records_by_parent_id(coin_name)
            if len(child_coin_records) > 0:
                for record in child_coin_records:
                    if record.wallet_id == self.id():
                        await self.wallet_state_manager.coin_store.delete_coin_record(record.coin.name())
                        # await self.remove_lineage(record.coin.name())
                        # We also need to make sure there's no record of the transaction
                        await self.wallet_state_manager.tx_store.delete_transaction_record(record.coin.name())

    async def add_coin(self, coin: Coin, puzzle: Program, lineage_proof: LineageProof, in_transaction: bool) -> None:
        my_nft_coins = self.nft_wallet_info.my_nft_coins
        for coin_info in my_nft_coins:
            if coin_info.coin == coin:
                my_nft_coins.remove(coin_info)

        my_nft_coins.append(NFTCoinInfo(coin, lineage_proof, puzzle))
        new_nft_wallet_info = NFTWalletInfo(
            my_nft_coins,
            self.nft_wallet_info.did_wallet_id,
        )
        await self.save_info(new_nft_wallet_info, in_transaction=in_transaction)
        await self.wallet_state_manager.add_interested_coin_ids([coin.name()], in_transaction=in_transaction)
        return

    async def remove_coin(self, coin: Coin, in_transaction: bool) -> None:
        my_nft_coins = self.nft_wallet_info.my_nft_coins
        for coin_info in my_nft_coins:
            if coin_info.coin == coin:
                my_nft_coins.remove(coin_info)
        new_nft_wallet_info = NFTWalletInfo(
            my_nft_coins,
            self.nft_wallet_info.did_wallet_id,
        )
        await self.save_info(new_nft_wallet_info, in_transaction=in_transaction)
        return

    def puzzle_for_pk(self, pk: G1Element) -> Program:
        if not self.nft_wallet_info.did_wallet_id:
            inner_puzzle = self.standard_wallet.puzzle_for_pk(bytes(pk))
        else:
            raise NotImplementedError
        provenance_puzzle = Program.to([NFT_STATE_LAYER_MOD_HASH, inner_puzzle])
        return provenance_puzzle

    async def generate_new_nft(self, metadata: Program) -> Optional[TransactionRecord]:
        """
        This must be called under the wallet state manager lock
        """
        amount = 1
        coins = await self.standard_wallet.select_coins(amount)
        if coins is None:
            return None
        self.log.debug("Attempt to generate a new NFT")
        origin = coins.copy().pop()
        genesis_launcher_puz = nft_puzzles.LAUNCHER_PUZZLE
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), uint64(amount))
        self.log.debug("Generating NFT with launcher coin %s and metadata: %s", launcher_coin, metadata)
        inner_puzzle = await self.standard_wallet.get_new_puzzle()
        # singleton eve
        eve_fullpuz = nft_puzzles.create_full_puzzle(
            launcher_coin.name(), metadata, NFT_METADATA_UPDATER.get_tree_hash(), inner_puzzle
        )
        # launcher announcement
        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([eve_fullpuz.get_tree_hash(), amount, []]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

        self.log.debug(
            "Creating transaction for launcher: %s and other coins: %s (%s)", origin, coins, announcement_set
        )
        # store the launcher transaction in the wallet state
        tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            uint64(amount),
            genesis_launcher_puz.get_tree_hash(),
            uint64(0),
            origin.name(),
            coins,
            None,
            False,
            announcement_set,
        )

        genesis_launcher_solution = Program.to([eve_fullpuz.get_tree_hash(), amount, []])

        # launcher spend to generate the singleton
        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))

        eve_coin = Coin(launcher_coin.name(), eve_fullpuz.get_tree_hash(), uint64(amount))

        if tx_record is None or tx_record.spend_bundle is None:
            return None

        condition_list = [make_create_coin_condition(inner_puzzle.get_tree_hash(), amount, [])]
        innersol = solution_for_conditions(condition_list)
        # EVE SPEND BELOW

        fullsol = Program.to(
            [
                [launcher_coin.parent_coin_info, launcher_coin.amount],
                eve_coin.amount,
                Program.to(
                    [
                        innersol,
                        amount,
                        0,
                    ]
                ),
            ]
        )
        list_of_coinspends = [CoinSpend(eve_coin, eve_fullpuz, fullsol)]
        eve_spend_bundle = SpendBundle(list_of_coinspends, AugSchemeMPL.aggregate([]))
        eve_spend_bundle = await self.sign(eve_spend_bundle)
        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, eve_spend_bundle, launcher_sb])
        nft_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=eve_fullpuz.get_tree_hash(),
            amount=uint64(amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=full_spend,
            additions=full_spend.additions(),
            removals=full_spend.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=bytes32(token_bytes()),
            memos=[],
        )
        await self.standard_wallet.push_transaction(nft_record)
        return nft_record

    async def generate_eve_spend(self, coin: Coin, full_puzzle: Program, innerpuz: Program, origin_coin: Coin):
        # innerpuz solution is (mode p2_solution)
        p2_solution = self.standard_wallet.make_solution(
            primaries=[
                {
                    "puzzlehash": innerpuz.get_tree_hash(),
                    "amount": uint64(coin.amount),
                    "memos": [innerpuz.get_tree_hash()],
                }
            ]
        )
        innersol = Program.to([1, p2_solution])
        # full solution is (lineage_proof my_amount inner_solution)
        fullsol = Program.to(
            [
                [origin_coin.parent_coin_info, origin_coin.amount],
                coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol)]
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        return await self.sign(unsigned_spend_bundle)

    async def sign(self, spend_bundle: SpendBundle) -> SpendBundle:
        sigs: List[G2Element] = []
        for spend in spend_bundle.coin_spends:
            matched, _, puzzle_args = nft_puzzles.match_nft_puzzle(spend.puzzle_reveal.to_program())
            self.log.debug("Checking if spend matches a NFT puzzle: %s", matched)
            if matched:
                self.log.debug("Found a NFT state layer to sign")
                (_, metadata, metadata_updater_puzzle_hash, inner_puzzle) = puzzle_args
                puzzle_hash = inner_puzzle.get_tree_hash()
                pubkey, private = await self.wallet_state_manager.get_keys(puzzle_hash)
                synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
                error, conditions, cost = conditions_dict_for_solution(
                    spend.puzzle_reveal.to_program(),
                    spend.solution.to_program(),
                    self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
                )

                if conditions is not None:
                    synthetic_pk = synthetic_secret_key.get_g1()
                    for pk, msg in pkm_pairs_for_conditions_dict(
                        conditions, spend.coin.name(), self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
                    ):
                        try:
                            assert bytes(synthetic_pk) == pk
                            sigs.append(AugSchemeMPL.sign(synthetic_secret_key, msg))
                        except AssertionError:
                            raise ValueError("This spend bundle cannot be signed by the NFT wallet")

        agg_sig = AugSchemeMPL.aggregate(sigs)
        return SpendBundle.aggregate([spend_bundle, SpendBundle([], agg_sig)])

    async def transfer_nft(
        self,
        nft_coin_info: NFTCoinInfo,
        puzzle_hash=None,
        did_hash=None,
    ):
        self.log.debug("Attempt to transfer a new NFT")
        coin = nft_coin_info.coin
        self.log.debug("Transfering NFT coin %s", coin)

        full_puzzle = nft_coin_info.full_puzzle
        amount = coin.amount
        condition_list = [make_create_coin_condition(puzzle_hash, amount, [])]
        innersol = solution_for_conditions(condition_list)
        lineage_proof = nft_coin_info.lineage_proof
        fullsol = Program.to(
            [
                [lineage_proof.parent_name, lineage_proof.inner_puzzle_hash, lineage_proof.amount],
                coin.amount,
                Program.to(
                    [
                        innersol,
                        amount,
                        0,
                    ]
                ),
            ]
        )
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol)]
        spend_bundle = SpendBundle(list_of_coinspends, AugSchemeMPL.aggregate([]))
        spend_bundle = await self.sign(spend_bundle)
        full_spend = SpendBundle.aggregate([spend_bundle])
        nft_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=full_puzzle.get_tree_hash(),
            amount=uint64(amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=full_spend,
            additions=full_spend.additions(),
            removals=full_spend.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=bytes32(token_bytes()),
            memos=[],
        )
        await self.standard_wallet.push_transaction(nft_record)
        return full_spend

    def get_current_nfts(self) -> List[NFTCoinInfo]:
        return self.nft_wallet_info.my_nft_coins

    async def save_info(self, nft_info: NFTWalletInfo, in_transaction: bool) -> None:
        self.nft_wallet_info = nft_info
        current_info = self.wallet_info
        data_str = json.dumps(nft_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)
