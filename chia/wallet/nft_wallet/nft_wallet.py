import json
import logging
import time
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Set, Tuple, Type, TypeVar

from blspy import AugSchemeMPL, G1Element, G2Element
from clvm.casts import int_from_bytes, int_to_bytes

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
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet import nft_puzzles
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo, NFTWalletInfo
from chia.wallet.nft_wallet.nft_puzzles import NFT_METADATA_UPDATER, NFT_STATE_LAYER_MOD_HASH
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.outer_puzzles import AssetType, match_puzzle
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    solution_for_conditions,
)
from chia.wallet.puzzles.puzzle_utils import make_create_coin_condition
from chia.wallet.puzzles.singleton_top_layer_v1_1 import match_singleton_puzzle
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.debug_spend_bundle import disassemble
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo

_T_NFTWallet = TypeVar("_T_NFTWallet", bound="NFTWallet")


OFFER_MOD = load_clvm("settlement_payments.clvm")


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
        in_transaction: bool = False,
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
        wallet_info = await wallet_state_manager.user_store.create_wallet(
            "NFT Wallet" if not name else name,
            uint32(WalletType.NFT.value),
            info_as_string,
            in_transaction=in_transaction,
        )

        if wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_info = wallet_info
        self.wallet_id = self.wallet_info.id
        self.log.debug("NFT wallet id: %r and standard wallet id: %r", self.wallet_id, self.standard_wallet.wallet_id)

        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id, in_transaction=in_transaction)
        self.log.debug("Generated a new NFT wallet: %s", self.__dict__)
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
        name: Optional[str] = None,
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

    async def get_confirmed_balance(self, record_list=None) -> uint128:
        """The NFT wallet doesn't really have a balance."""
        return uint128(0)

    async def get_unconfirmed_balance(self, record_list=None) -> uint128:
        """The NFT wallet doesn't really have a balance."""
        return uint128(0)

    async def get_spendable_balance(self, unspent_records=None) -> uint128:
        """The NFT wallet doesn't really have a balance."""
        return uint128(0)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def get_max_send_amount(self, records=None):
        """This is the confirmed balance, which we set to 0 as the NFT wallet doesn't have one."""
        return uint128(0)

    def get_nft_coin_by_id(self, nft_coin_id: bytes32) -> NFTCoinInfo:
        for nft_coin in self.nft_wallet_info.my_nft_coins:
            if nft_coin.coin.name() == nft_coin_id:
                return nft_coin
        raise KeyError(f"Couldn't find coin with id: {nft_coin_id}")

    async def add_nft_coin(self, coin: Coin, spent_height: uint32, in_transaction: bool) -> None:
        await self.coin_added(coin, spent_height, in_transaction=in_transaction)

    async def coin_added(self, coin: Coin, height: uint32, in_transaction: bool) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"NFT wallet %s has been notified that {coin} was added", self.wallet_info.name)
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
        self.log.debug("Puzzle solution received to wallet: %s", self.wallet_info)
        coin_name = coin_spend.coin.name()
        puzzle: Program = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
        full_solution: Program = Program.from_bytes(bytes(coin_spend.solution))
        delegated_puz_solution: Program = Program.from_bytes(bytes(coin_spend.solution)).rest().rest().first().first()

        # At this point, the puzzle must be a NFT puzzle.
        # This method will be called only when the walle state manager uncurried this coin as a NFT puzzle.

        uncurried_nft = UncurriedNFT.uncurry(puzzle)
        self.log.info(
            f"found the info for NFT coin {coin_name} {uncurried_nft.inner_puzzle} {uncurried_nft.singleton_struct}"
        )
        singleton_id = bytes32(uncurried_nft.singleton_launcher_id.atom)
        metadata = uncurried_nft.metadata
        new_inner_puzzle = None
        update_condition = None
        parent_inner_puzhash = uncurried_nft.nft_state_layer.get_tree_hash()
        self.log.debug("Before spend metadata: %s %s \n%s", metadata, singleton_id, disassemble(delegated_puz_solution))

        if delegated_puz_solution.rest().as_python() == b"":
            conds = puzzle.run(full_solution)
        else:
            conds = delegated_puz_solution.rest().first().rest()

        # for condition in delegated_puz_solution.rest().first().rest().as_itexr():
        for condition in conds.as_iter():
            self.log.debug("Checking solution condition: %s", disassemble(condition))
            if condition.list_len() <= 2:
                # irrelevant condition
                continue
            condition_code = int_from_bytes(condition.first().atom)
            self.log.debug("Checking condition code: %r", condition_code)
            if condition_code == -24:
                # metadata update
                update_condition = condition
            elif condition_code == 51 and int_from_bytes(condition.rest().rest().first().atom) == 1:
                puzhash = bytes32(condition.rest().first().atom)
                memo = bytes32(condition.as_python()[-1][0])
                if memo != puzhash:
                    puzhash_for_derivation_record = memo
                else:
                    puzhash_for_derivation_record = puzhash

                self.log.debug("Got back puzhash from solution: %s", puzhash)
                derivation_record: Optional[
                    DerivationRecord
                ] = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
                    puzhash_for_derivation_record
                )
                if derivation_record is None:
                    # we potentially sent it somewhere
                    await self.remove_coin(coin_spend.coin, in_transaction=in_transaction)
                    return
                new_inner_puzzle = puzzle_for_pk(derivation_record.pubkey)
            else:
                raise ValueError("Invalid condition")
        if new_inner_puzzle is None:
            raise ValueError("Invalid puzzle")
        if update_condition is not None:
            metadata = nft_puzzles.update_metadata(metadata, update_condition)
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
            bytes32(uncurried_nft.metadata_updater_hash.atom),
            new_inner_puzzle,
        )
        self.log.debug(
            "Created NFT full puzzle with inner: %s",
            nft_puzzles.create_full_puzzle_with_nft_puzzle(singleton_id, uncurried_nft.inner_puzzle),
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
        self.log.info("Adding a new NFT to wallet: %s", child_coin)
        await self.add_coin(
            child_coin,
            child_puzzle,
            LineageProof(parent_coin.parent_coin_info, parent_inner_puzhash, parent_coin.amount),
            in_transaction=in_transaction,
        )

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
        self.wallet_state_manager.state_changed("nft_coin_added", self.wallet_info.id)
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
        self.wallet_state_manager.state_changed("nft_coin_removed", self.wallet_info.id)
        return

    def puzzle_for_pk(self, pk: G1Element) -> Program:
        if not self.nft_wallet_info.did_wallet_id:
            inner_puzzle = self.standard_wallet.puzzle_for_pk(bytes(pk))
        else:
            raise NotImplementedError
        provenance_puzzle = Program.to([NFT_STATE_LAYER_MOD_HASH, inner_puzzle])
        self.log.debug(
            "Wallet name %s generated a puzzle: %s", self.wallet_info.name, provenance_puzzle.get_tree_hash()
        )
        return provenance_puzzle

    async def generate_new_nft(
        self,
        metadata: Program,
        royalty_puzzle_hash: bytes32 = None,
        target_puzzle_hash: bytes32 = None,
        fee: uint64 = uint64(0),
    ) -> Optional[SpendBundle]:
        # TODO Set royalty address after NFT1 chialisp finished
        """
        This must be called under the wallet state manager lock
        """
        amount = uint64(1)
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
            fee,
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

        if not target_puzzle_hash:
            target_puzzle_hash = inner_puzzle.get_tree_hash()
        condition_list = [make_create_coin_condition(target_puzzle_hash, amount, [target_puzzle_hash])]
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
            fee_amount=fee,
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
            memos=list(compute_memos(full_spend).items()),
        )
        await self.standard_wallet.push_transaction(nft_record)
        return nft_record.spend_bundle

    async def sign(self, spend_bundle: SpendBundle) -> SpendBundle:
        sigs: List[G2Element] = []
        for spend in spend_bundle.coin_spends:
            try:
                uncurried_nft = UncurriedNFT.uncurry(spend.puzzle_reveal.to_program())
            except Exception as e:
                # This only happens while you changed the NFT chialisp but didn't update the UncurriedNFT class.
                self.log.error(e)
            else:
                self.log.debug("Found a NFT state layer to sign")
                puzzle_hash = uncurried_nft.inner_puzzle.get_tree_hash()
                keys = await self.wallet_state_manager.get_keys(puzzle_hash)
                assert keys
                _, private = keys
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

    async def _make_nft_transaction(
        self, nft_coin_info: NFTCoinInfo, inner_solution: Program, fee: uint64 = uint64(0)
    ) -> TransactionRecord:
        # Update NFT status
        await self.update_coin_status(nft_coin_info.coin.name(), True)
        coin = nft_coin_info.coin
        amount = coin.amount
        full_puzzle = nft_coin_info.full_puzzle
        lineage_proof = nft_coin_info.lineage_proof
        assert lineage_proof is not None
        self.log.debug("Inner solution: %r", disassemble(inner_solution))
        full_solution = Program.to(
            [
                [lineage_proof.parent_name, lineage_proof.inner_puzzle_hash, lineage_proof.amount],
                coin.amount,
                Program.to(
                    [
                        inner_solution,
                        amount,
                        0,
                    ]
                ),
            ]
        )
        list_of_coinspends = [CoinSpend(coin, full_puzzle.to_serialized_program(), full_solution)]
        spend_bundle = SpendBundle(list_of_coinspends, AugSchemeMPL.aggregate([]))
        spend_bundle = await self.sign(spend_bundle)
        full_spend = SpendBundle.aggregate([spend_bundle])
        self.log.debug("Memos are: %r", list(compute_memos(full_spend).items()))
        nft_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=full_puzzle.get_tree_hash(),
            amount=uint64(amount),
            fee_amount=fee,
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
            memos=list(compute_memos(full_spend).items()),
        )
        return nft_record

    async def update_metadata(
        self, nft_coin_info: NFTCoinInfo, key: str, uri: str, fee: uint64 = uint64(0)
    ) -> Optional[SpendBundle]:
        coin = nft_coin_info.coin

        uncurried_nft = UncurriedNFT.uncurry(nft_coin_info.full_puzzle)

        puzzle_hash = uncurried_nft.inner_puzzle.get_tree_hash()
        condition_list = [make_create_coin_condition(puzzle_hash, coin.amount, [puzzle_hash])]
        condition_list.append([int_to_bytes(-24), NFT_METADATA_UPDATER, (key, uri)])

        self.log.info(
            "Attempting to add urls to NFT coin %s in the metadata: %s", nft_coin_info, uncurried_nft.metadata
        )
        inner_solution = solution_for_conditions(condition_list)
        nft_tx_record = await self._make_nft_transaction(nft_coin_info, inner_solution, fee)
        await self.standard_wallet.push_transaction(nft_tx_record)
        self.wallet_state_manager.state_changed("nft_coin_updated", self.wallet_info.id)
        return nft_tx_record.spend_bundle

    async def transfer_nft(
        self,
        nft_coin_info: NFTCoinInfo,
        puzzle_hash: bytes32,
        did_hash=None,
        fee: uint64 = uint64(0),
    ) -> Optional[SpendBundle]:
        self.log.debug("Attempt to transfer a new NFT")
        coin = nft_coin_info.coin
        self.log.debug("Transfering NFT coin %r to puzhash: %s", nft_coin_info, puzzle_hash)

        amount = coin.amount
        condition_list = [make_create_coin_condition(puzzle_hash, amount, [bytes32(puzzle_hash)])]
        self.log.debug("Condition for new coin: %r", condition_list)
        inner_solution = solution_for_conditions(condition_list)
        nft_tx_record = await self._make_nft_transaction(nft_coin_info, inner_solution, fee)
        await self.standard_wallet.push_transaction(nft_tx_record)
        self.wallet_state_manager.state_changed("nft_coin_transferred", self.wallet_info.id)
        return nft_tx_record.spend_bundle

    def get_current_nfts(self) -> List[NFTCoinInfo]:
        return self.nft_wallet_info.my_nft_coins

    async def update_coin_status(
        self, coin_id: bytes32, pending_transaction: bool, in_transaction: bool = False
    ) -> None:
        my_nft_coins = self.nft_wallet_info.my_nft_coins
        target_nft: Optional[NFTCoinInfo] = None
        for coin_info in my_nft_coins:
            if coin_info.coin.name() == coin_id:
                target_nft = coin_info
                my_nft_coins.remove(coin_info)
        if target_nft is None:
            raise ValueError(f"NFT coin {coin_id} doesn't exist.")

        my_nft_coins.append(
            NFTCoinInfo(target_nft.coin, target_nft.lineage_proof, target_nft.full_puzzle, pending_transaction)
        )
        new_nft_wallet_info = NFTWalletInfo(
            my_nft_coins,
            self.nft_wallet_info.did_wallet_id,
        )
        await self.save_info(new_nft_wallet_info, in_transaction=in_transaction)

    async def save_info(self, nft_info: NFTWalletInfo, in_transaction: bool) -> None:
        self.nft_wallet_info = nft_info
        current_info = self.wallet_info
        data_str = json.dumps(nft_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)

    async def convert_puzzle_hash(self, puzhash: bytes32) -> bytes32:
        return puzhash

    def get_nft(self, launcher_id: bytes32) -> Optional[NFTCoinInfo]:
        for coin in self.nft_wallet_info.my_nft_coins:
            matched, curried_args = match_singleton_puzzle(coin.full_puzzle)
            if matched:
                singleton_struct, inner_puzzle = curried_args
                launcher: bytes32 = singleton_struct.as_python()[1]
                if launcher == launcher_id:
                    return coin
        return None

    def get_puzzle_info(self, asset_id: bytes32) -> PuzzleInfo:
        nft_coin: Optional[NFTCoinInfo] = self.get_nft(asset_id)
        if nft_coin is None:
            raise ValueError("An asset ID was specified that this wallet doesn't track")
        puzzle_info: Optional[PuzzleInfo] = match_puzzle(nft_coin.full_puzzle)
        if puzzle_info is None:
            raise ValueError("Internal Error: NFT wallet is tracking a non NFT coin")
        else:
            return puzzle_info

    async def get_coins_to_offer(self, asset_id: bytes32, amount: uint64) -> Set[Coin]:
        nft_coin: Optional[NFTCoinInfo] = self.get_nft(asset_id)
        if nft_coin is None:
            raise ValueError("An asset ID was specified that this wallet doesn't track")
        return set([nft_coin.coin])

    def match_puzzle_info(self, puzzle_driver: PuzzleInfo) -> bool:
        return (
            AssetType(puzzle_driver.type()) == AssetType.SINGLETON
            and self.get_nft(puzzle_driver["launcher_id"]) is not None
            and puzzle_driver.also() is not None
            and AssetType(puzzle_driver.also().type()) == AssetType.METADATA  # type: ignore
            and puzzle_driver.also().also() is None  # type: ignore
        )

    @classmethod
    async def create_from_puzzle_info(
        cls,
        wallet_state_manager: Any,
        wallet: Wallet,
        puzzle_driver: PuzzleInfo,
        name=None,
        in_transaction=False,
    ) -> Any:
        # Off the bat we don't support multiple profile but when we do this will have to change
        for wallet in wallet_state_manager.wallets.values():
            if wallet.type() == WalletType.NFT:
                return wallet

        # TODO: These are not the arguments to this function yet but they will be
        return await cls.create_new_nft_wallet(
            wallet_state_manager,
            wallet,
            name,
            in_transaction,
        )

    async def create_tandem_xch_tx(
        self, fee: uint64, announcement_to_assert: Optional[Announcement] = None
    ) -> TransactionRecord:
        chia_coins = await self.standard_wallet.select_coins(fee)
        chia_tx = await self.standard_wallet.generate_signed_transaction(
            uint64(0),
            (await self.standard_wallet.get_new_puzzlehash()),
            fee=fee,
            coins=chia_coins,
            coin_announcements_to_consume={announcement_to_assert} if announcement_to_assert is not None else None,
        )
        assert chia_tx.spend_bundle is not None
        return chia_tx

    async def generate_signed_transaction(
        self,
        amounts: List[uint64],
        puzzle_hashes: List[bytes32],
        fee: uint64 = uint64(0),
        coins: Set[Coin] = None,
        memos: Optional[List[List[bytes]]] = None,
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
        ignore_max_send_amount: bool = False,
    ) -> List[TransactionRecord]:
        if memos is None:
            memos = [[] for _ in range(len(puzzle_hashes))]

        if not (len(memos) == len(puzzle_hashes) == len(amounts)):
            raise ValueError("Memos, puzzle_hashes, and amounts must have the same length")

        payments = []
        for amount, puzhash, memo_list in zip(amounts, puzzle_hashes, memos):
            memos_with_hint: List[bytes] = [puzhash]
            memos_with_hint.extend(memo_list)
            payments.append(Payment(puzhash, amount, memos_with_hint))

        payment_sum = sum([p.amount for p in payments])

        unsigned_spend_bundle, chia_tx = await self.generate_unsigned_spendbundle(
            payments,
            fee,
            coins=coins,
            coin_announcements_to_consume=coin_announcements_to_consume,
            puzzle_announcements_to_consume=puzzle_announcements_to_consume,
        )
        spend_bundle = await self.sign(unsigned_spend_bundle)

        tx_list = [
            TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=puzzle_hashes[0],
                amount=uint64(payment_sum),
                fee_amount=fee,
                confirmed=False,
                sent=uint32(0),
                spend_bundle=spend_bundle,
                additions=spend_bundle.additions(),
                removals=spend_bundle.removals(),
                wallet_id=self.id(),
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=spend_bundle.name(),
                memos=list(compute_memos(spend_bundle).items()),
            )
        ]

        if chia_tx is not None:
            tx_list.append(
                TransactionRecord(
                    confirmed_at_height=chia_tx.confirmed_at_height,
                    created_at_time=chia_tx.created_at_time,
                    to_puzzle_hash=chia_tx.to_puzzle_hash,
                    amount=chia_tx.amount,
                    fee_amount=chia_tx.fee_amount,
                    confirmed=chia_tx.confirmed,
                    sent=chia_tx.sent,
                    spend_bundle=None,
                    additions=chia_tx.additions,
                    removals=chia_tx.removals,
                    wallet_id=chia_tx.wallet_id,
                    sent_to=chia_tx.sent_to,
                    trade_id=chia_tx.trade_id,
                    type=chia_tx.type,
                    name=chia_tx.name,
                    memos=[],
                )
            )

        return tx_list

    async def generate_unsigned_spendbundle(
        self,
        payments: List[Payment],
        fee: uint64 = uint64(0),
        coins: Set[Coin] = None,
        coin_announcements_to_consume: Optional[Set[Announcement]] = None,
        puzzle_announcements_to_consume: Optional[Set[Announcement]] = None,
    ) -> Tuple[SpendBundle, Optional[TransactionRecord]]:
        if coins is None:
            # Make sure the user is specifying which specific NFT coin to use
            raise ValueError("NFT spends require a selected coin")
        else:
            nft_coins = [c for c in self.nft_wallet_info.my_nft_coins if c.coin in coins]

        if coin_announcements_to_consume is not None:
            coin_announcements_bytes: Optional[Set[bytes32]] = {a.name() for a in coin_announcements_to_consume}
        else:
            coin_announcements_bytes = None

        if puzzle_announcements_to_consume is not None:
            puzzle_announcements_bytes: Optional[Set[bytes32]] = {a.name() for a in puzzle_announcements_to_consume}
        else:
            puzzle_announcements_bytes = None

        primaries: List = []
        for payment in payments:
            primaries.append({"puzzlehash": payment.puzzle_hash, "amount": payment.amount, "memos": payment.memos})

        chia_tx = None
        coin_spends = []
        first = True
        for coin_info in nft_coins:
            if first:
                first = False
                if fee > 0:
                    chia_tx = await self.create_tandem_xch_tx(fee)
                    innersol = self.standard_wallet.make_solution(
                        primaries=primaries,
                        coin_announcements_to_assert=coin_announcements_bytes,
                        puzzle_announcements_to_assert=puzzle_announcements_bytes,
                    )
                else:
                    innersol = self.standard_wallet.make_solution(
                        primaries=primaries,
                        coin_announcements_to_assert=coin_announcements_bytes,
                        puzzle_announcements_to_assert=puzzle_announcements_bytes,
                    )
            else:
                # What announcements do we need?
                innersol = self.standard_wallet.make_solution(
                    primaries=[],
                )

            nft_layer_solution = Program.to([innersol, coin_info.coin.amount])
            assert isinstance(coin_info.lineage_proof, LineageProof)
            singleton_solution = Program.to(
                [coin_info.lineage_proof.to_program(), coin_info.coin.amount, nft_layer_solution]
            )
            coin_spend = CoinSpend(coin_info.coin, coin_info.full_puzzle, singleton_solution)
            coin_spends.append(coin_spend)

        nft_spend_bundle = SpendBundle(coin_spends, G2Element())
        chia_spend_bundle = SpendBundle([], G2Element())
        if chia_tx is not None and chia_tx.spend_bundle is not None:
            chia_spend_bundle = chia_tx.spend_bundle

        unsigned_spend_bundle = SpendBundle.aggregate([nft_spend_bundle, chia_spend_bundle])

        return (unsigned_spend_bundle, chia_tx)
