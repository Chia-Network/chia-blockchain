import json
import logging
import time
from dataclasses import dataclass
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Set, Tuple, Type, TypeVar

from blspy import AugSchemeMPL, G1Element, G2Element
from clvm.casts import int_to_bytes

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
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import Streamable, streamable
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet import nft_puzzles
from chia.wallet.nft_wallet.nft_puzzles import (
    LAUNCHER_PUZZLE,
    NFT_METADATA_UPDATER,
    NFT_STATE_LAYER_MOD_HASH,
    create_ownership_layer_puzzle,
    create_ownership_layer_transfer_solution,
    get_metadata_and_p2_puzhash,
)
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    solution_for_conditions,
)
from chia.wallet.puzzles.puzzle_utils import make_create_coin_condition
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.debug_spend_bundle import disassemble
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_info import WalletInfo

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
    did_id: Optional[bytes32] = None


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
    did_id: Optional[bytes32]

    @classmethod
    async def create_new_nft_wallet(
        cls: Type[_T_NFTWallet],
        wallet_state_manager: Any,
        wallet: Wallet,
        did_id: Optional[bytes32] = None,
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
        self.nft_wallet_info = NFTWalletInfo([], did_id)
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
        if not did_id:
            # default profile wallet
            self.log.debug("Standard NFT wallet created")
            self.did_id = None
        else:
            self.did_id = did_id
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
        solution: Program = Program.from_bytes(bytes(coin_spend.solution)).rest().rest().first().first()
        # At this point, the puzzle must be a NFT puzzle.
        # This method will be called only when the wallet state manager uncurried this coin as a NFT puzzle.

        uncurried_nft = UncurriedNFT.uncurry(puzzle)
        self.log.info(
            f"found the info for NFT coin {coin_name} {uncurried_nft.inner_puzzle} {uncurried_nft.singleton_struct}"
        )
        singleton_id = bytes32(uncurried_nft.singleton_launcher_id.atom)
        parent_inner_puzhash = uncurried_nft.nft_state_layer.get_tree_hash()
        p2_puzzle_hash, metadata = get_metadata_and_p2_puzhash(uncurried_nft, solution)
        self.log.debug("Got back puzhash from solution: %s", p2_puzzle_hash)
        derivation_record: Optional[
            DerivationRecord
        ] = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(p2_puzzle_hash)
        if derivation_record is None:
            # we transferred it to another wallet, remove the coin from our wallet
            await self.remove_coin(coin_spend.coin, in_transaction=in_transaction)
            return
        p2_puzzle = puzzle_for_pk(derivation_record.pubkey)
        if p2_puzzle is None:
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
            raise ValueError("Error finding parent")
        self.log.debug("Got back updated metadata: %s", metadata)
        child_puzzle: Program = nft_puzzles.create_full_puzzle(
            singleton_id,
            Program.to(metadata),
            bytes32(uncurried_nft.metadata_updater_hash.atom),
            p2_puzzle,
        )
        self.log.debug(
            "Created NFT full puzzle with inner: %s",
            nft_puzzles.create_full_puzzle_with_nft_puzzle(singleton_id, uncurried_nft.inner_puzzle),
        )
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
            self.nft_wallet_info.did_id,
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
            self.nft_wallet_info.did_id,
        )
        await self.save_info(new_nft_wallet_info, in_transaction=in_transaction)
        self.wallet_state_manager.state_changed("nft_coin_removed", self.wallet_info.id)
        return

    def puzzle_for_pk(self, pk: G1Element) -> Program:
        inner_puzzle = self.standard_wallet.puzzle_for_pk(bytes(pk))
        provenance_puzzle = Program.to([NFT_STATE_LAYER_MOD_HASH, inner_puzzle])
        self.log.debug(
            "Wallet name %s generated a puzzle: %s", self.wallet_info.name, provenance_puzzle.get_tree_hash()
        )
        return provenance_puzzle

    async def get_did_approval_info(
        self,
        nft_id: bytes32,
    ) -> Tuple[bytes32, SpendBundle]:
        """Get DID spend with announcement created we need to transfer NFT with did with current inner hash of DID

        We also store `did_id` and then iterate to find the did wallet as we'd otherwise have to subscribe to
        any changes to DID wallet and storing wallet_id is not guaranteed to be consistent on wallet crash/reset.
        """
        for _, wallet in self.wallet_state_manager.wallets.items():
            self.log.debug("Checking wallet type %s", wallet.type())
            if wallet.type() == WalletType.DISTRIBUTED_ID:
                self.log.debug("Found a DID wallet, checking did: %r == %r", wallet.get_my_DID(), self.did_id)
                if bytes32.fromhex(wallet.get_my_DID()) == self.did_id:
                    self.log.debug("Creating announcement from DID for nft_id: %s", nft_id)
                    did_bundle = await wallet.create_message_spend(puzzle_announcements=[nft_id])
                    self.log.debug("Sending DID announcement from puzzle: %s", did_bundle.removals())
                    did_inner_hash = wallet.did_info.current_inner.get_tree_hash()
                    break
        else:
            raise ValueError(f"Missing DID Wallet for did_id: {self.did_id}")
        return did_inner_hash, did_bundle

    async def generate_new_nft(
        self,
        metadata: Program,
        target_puzzle_hash: Optional[bytes32] = None,
        royalty_puzzle_hash: Optional[bytes32] = None,
        percentage=0,
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
        # nft_id == singleton_id == launcher_id == launcher_coin.name()
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), uint64(amount))
        self.log.debug("Generating NFT with launcher coin %s and metadata: %s", launcher_coin, metadata)

        p2_inner_puzzle = await self.standard_wallet.get_new_puzzle()

        if self.did_id:
            self.log.debug("Creating NFT using DID: %s", self.did_id)
            inner_puzzle = create_ownership_layer_puzzle(launcher_coin.name(), self.did_id, p2_inner_puzzle, percentage)
            self.log.debug("Got back ownership inner puzzle: %s", disassemble(inner_puzzle))
        else:
            inner_puzzle = p2_inner_puzzle
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

        bundles_to_agg = [tx_record.spend_bundle, launcher_sb]

        if not target_puzzle_hash:
            target_puzzle_hash = inner_puzzle.get_tree_hash()
        record: DerivationRecord
        # Create inner solution for eve spend
        if self.did_id:
            record = await self.wallet_state_manager.get_current_derivation_record_for_wallet(self.id())
            self.log.debug("Got back a pubkey record: %s", record)
            if not record:
                record = await self.wallet_state_manager.get_unused_derivation_record(self.id(), False)
            did_inner_hash, did_bundle = await self.get_did_approval_info(launcher_coin.name())
            pubkey = record.pubkey
            self.log.debug("Going to use this pubkey for NFT mint: %s", pubkey)
            innersol = create_ownership_layer_transfer_solution(self.did_id, did_inner_hash, [], pubkey)
            bundles_to_agg.append(did_bundle)
            self.log.debug("Created an inner DID NFT solution: %s", disassemble(innersol))
        else:
            condition_list = [make_create_coin_condition(target_puzzle_hash, amount, [target_puzzle_hash])]
            innersol = solution_for_conditions(condition_list)
        # full solution for eve spend
        fullsol = Program.to(
            [
                [launcher_coin.parent_coin_info, launcher_coin.amount],
                eve_coin.amount,
                [
                    innersol,
                    amount,
                ],
            ]
        )
        self.log.debug(
            "Going to spend eve fullpuz with a solution: \n\n%s\n=================================\n\n%s",
            disassemble(eve_fullpuz),
            disassemble(fullsol),
        )
        list_of_coinspends = [CoinSpend(eve_coin, eve_fullpuz, fullsol)]
        eve_spend_bundle = SpendBundle(list_of_coinspends, AugSchemeMPL.aggregate([]))
        puzzle_hashes_to_sign = [p2_inner_puzzle.get_tree_hash()]
        if record:
            puzzle_hashes_to_sign.append(record.puzzle_hash)
        eve_spend_bundle = await self.sign(eve_spend_bundle, puzzle_hashes_to_sign)
        bundles_to_agg.append(eve_spend_bundle)
        full_spend = SpendBundle.aggregate(bundles_to_agg)
        full_spend.debug()
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

    async def sign(self, spend_bundle: SpendBundle, puzzle_hashes) -> SpendBundle:
        sigs: List[G2Element] = []
        for spend in spend_bundle.coin_spends:
            pks = {}
            for ph in puzzle_hashes:
                keys = await self.wallet_state_manager.get_keys(ph)
                assert keys
                pks[bytes(keys[0])] = private = keys[1]
                synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
                synthetic_pk = synthetic_secret_key.get_g1()
                pks[bytes(synthetic_pk)] = synthetic_secret_key
            error, conditions, cost = conditions_dict_for_solution(
                spend.puzzle_reveal.to_program(),
                spend.solution.to_program(),
                self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
            )
            if conditions is not None:
                for pk, msg in pkm_pairs_for_conditions_dict(
                    conditions, spend.coin.name(), self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
                ):
                    try:
                        sk = pks.get(pk)
                        if sk:
                            self.log.debug("Found key, signing for pk: %s", pk)
                            sigs.append(AugSchemeMPL.sign(sk, msg))
                        else:
                            self.log.warning("Couldn't find key for: %s", pk)
                    except AssertionError:
                        raise ValueError("This spend bundle cannot be signed by the NFT wallet")

        agg_sig = AugSchemeMPL.aggregate(sigs)
        return SpendBundle.aggregate([spend_bundle, SpendBundle([], agg_sig)])

    async def _make_nft_transaction(
        self,
        nft_coin_info: NFTCoinInfo,
        inner_solution: Program,
        puzzle_hashes_to_sign: List[bytes32],
        fee: uint64 = uint64(0),
    ) -> TransactionRecord:

        coin = nft_coin_info.coin
        amount = coin.amount
        full_puzzle = nft_coin_info.full_puzzle
        lineage_proof = nft_coin_info.lineage_proof
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
        spend_bundle = await self.sign(spend_bundle, puzzle_hashes_to_sign)
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
        condition_list = [
            make_create_coin_condition(puzzle_hash, coin.amount, [puzzle_hash]),
            [int_to_bytes(-24), NFT_METADATA_UPDATER, (key, uri)],
        ]

        self.log.info(
            "Attempting to add urls to NFT coin %s in the metadata: %s", nft_coin_info, uncurried_nft.metadata
        )
        inner_solution = solution_for_conditions(condition_list)
        nft_tx_record = await self._make_nft_transaction(nft_coin_info, inner_solution, [puzzle_hash], fee)
        await self.standard_wallet.push_transaction(nft_tx_record)
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
        nft_tx_record = await self._make_nft_transaction(nft_coin_info, inner_solution, [puzzle_hash], fee)
        await self.standard_wallet.push_transaction(nft_tx_record)
        return nft_tx_record.spend_bundle

    def get_current_nfts(self) -> List[NFTCoinInfo]:
        return self.nft_wallet_info.my_nft_coins

    async def save_info(self, nft_info: NFTWalletInfo, in_transaction: bool) -> None:
        self.nft_wallet_info = nft_info
        current_info = self.wallet_info
        data_str = json.dumps(nft_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)
