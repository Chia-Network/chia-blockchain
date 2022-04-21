import json
import logging
import time
from dataclasses import dataclass
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Set, Tuple, Type, TypeVar

from blspy import AugSchemeMPL, G1Element

from chia.protocols.wallet_protocol import CoinState
from chia.server.outbound_message import NodeType
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import Streamable, streamable
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    get_innerpuzzle_from_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet import nft_puzzles
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_sync_utils import subscribe_to_phs
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
    transfer_program: Program
    full_puzzle: Program


@streamable
@dataclass(frozen=True)
class NFTWalletInfo(Streamable):
    my_did: bytes32
    did_wallet_id: uint64
    my_nft_coins: List[NFTCoinInfo]
    known_transfer_programs: List[Tuple[bytes32, Program]]


class NFTWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    nft_wallet_info: NFTWalletInfo
    standard_wallet: Wallet
    wallet_id: int
    base_puzzle_program: Optional[Program]
    base_inner_puzzle_hash: Optional[Program]

    @classmethod
    async def create_new_nft_wallet(
        cls: Type[_T_NFTWallet],
        wallet_state_manager: Any,
        wallet: Wallet,
        did_wallet_id: int,
        name: str = "",
    ) -> _T_NFTWallet:
        """
        This must be called under the wallet state manager lock
        """
        self = cls()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        did_wallet = self.wallet_state_manager.wallets[did_wallet_id]
        my_did = did_wallet.did_info.origin_coin.name()
        self.nft_wallet_info = NFTWalletInfo(my_did, uint64(did_wallet_id), [], [])
        info_as_string = json.dumps(self.nft_wallet_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "NFT Wallet", WalletType.NFT.value, info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id
        # std_wallet_id = self.standard_wallet.wallet_id
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
        # TODO: check if I need both
        full_nodes: Dict[
            bytes32, WSChiaConnection
        ] = self.wallet_state_manager.wallet_node.server.connection_by_type.get(NodeType.FULL_NODE, {})

        for node_id, node in full_nodes.copy().items():
            await subscribe_to_phs([my_did], node, uint32(0))
        await self.wallet_state_manager.add_interested_puzzle_hashes([my_did], [self.wallet_id], in_transaction=False)
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
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.NFT)

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

    async def add_nft_coin(self, coin: Coin, spent_height: uint32, in_transaction: bool) -> None:
        await self.coin_added(coin, spent_height, in_transaction=in_transaction)
        return

    async def coin_added(self, coin: Coin, height: uint32, in_transaction: bool) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f" NFT wallet has been notified that {coin} was added")
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
        assert coin_states is not None
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
        solution: Program = Program.from_bytes(bytes(coin_spend.solution)).rest().rest().first()
        matched, curried_args = nft_puzzles.match_nft_puzzle(puzzle)
        nft_transfer_program = None
        if matched:
            (
                NFT_MOD_HASH,
                singleton_struct,
                current_owner,
                nft_transfer_program_hash,
                transfer_program_curry_params,
                metadata,
            ) = curried_args
            # check if we already know this hash, if not then try to find reveal in solution
            for hash, reveal in self.nft_wallet_info.known_transfer_programs:
                if hash == bytes32(nft_transfer_program_hash.as_atom()):
                    nft_transfer_program = reveal
            if nft_transfer_program is None:
                attempt = nft_puzzles.get_transfer_program_from_inner_solution(solution)
                if attempt is not None:
                    nft_transfer_program = attempt
                    await self.add_transfer_program(nft_transfer_program, in_transaction=in_transaction)

            assert nft_transfer_program is not None
            self.log.info(f"found the info for coin {coin_name}")
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
            inner_puzzle: Program = nft_puzzles.create_nft_layer_puzzle_with_curry_params(
                singleton_struct.rest().first().as_atom(),
                current_owner.as_atom(),
                nft_transfer_program_hash.as_atom(),
                metadata,
                transfer_program_curry_params,
            )
            child_coin: Optional[Coin] = None
            for new_coin in coin_spend.additions():
                if new_coin.amount % 2 == 1:
                    child_coin = new_coin
                    break
            assert child_coin is not None

            metadata = nft_puzzles.update_metadata(metadata, solution)
            # TODO: add smarter check for -22 to see if curry_params changed and use this for metadata too
            child_puzzle: Program = nft_puzzles.create_full_puzzle_with_curry_params(
                singleton_struct.rest().first().as_atom(),
                self.nft_wallet_info.my_did,
                nft_transfer_program_hash.as_atom(),
                metadata,
                transfer_program_curry_params,
            )

            assert child_puzzle.get_tree_hash() == child_coin.puzzle_hash
            await self.add_coin(
                child_coin,
                LineageProof(parent_coin.parent_coin_info, inner_puzzle.get_tree_hash(), parent_coin.amount),
                nft_transfer_program,
                child_puzzle,
                in_transaction=in_transaction,
            )
        else:
            # The parent is not an NFT which means we need to scrub all of its children from our DB
            child_coin_records = await self.wallet_state_manager.coin_store.get_coin_records_by_parent_id(coin_name)
            if len(child_coin_records) > 0:
                for record in child_coin_records:
                    if record.wallet_id == self.id():
                        await self.wallet_state_manager.coin_store.delete_coin_record(record.coin.name())
                        # await self.remove_lineage(record.coin.name())
                        # We also need to make sure there's no record of the transaction
                        await self.wallet_state_manager.tx_store.delete_transaction_record(record.coin.name())

    async def add_coin(
        self, coin: Coin, lineage_proof: LineageProof, transfer_program: Program, puzzle: Program, in_transaction: bool
    ) -> None:
        my_nft_coins = self.nft_wallet_info.my_nft_coins
        for coin_info in my_nft_coins:
            if coin_info.coin == coin:
                my_nft_coins.remove(coin_info)

        my_nft_coins.append(NFTCoinInfo(coin, lineage_proof, transfer_program, puzzle))
        new_nft_wallet_info = NFTWalletInfo(
            self.nft_wallet_info.my_did,
            self.nft_wallet_info.did_wallet_id,
            my_nft_coins,
            self.nft_wallet_info.known_transfer_programs,
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
            self.nft_wallet_info.my_did,
            self.nft_wallet_info.did_wallet_id,
            my_nft_coins,
            self.nft_wallet_info.known_transfer_programs,
        )
        await self.save_info(new_nft_wallet_info, in_transaction=in_transaction)
        return

    async def add_transfer_program(self, transfer_program: Program, in_transaction: bool) -> None:
        my_transfer_programs = self.nft_wallet_info.known_transfer_programs
        my_transfer_programs.append((transfer_program.get_tree_hash(), transfer_program))
        new_nft_wallet_info = NFTWalletInfo(
            self.nft_wallet_info.my_did,
            self.nft_wallet_info.did_wallet_id,
            self.nft_wallet_info.my_nft_coins,
            my_transfer_programs,
        )
        await self.save_info(new_nft_wallet_info, in_transaction=in_transaction)
        return

    def puzzle_for_pk(self, pk: G1Element) -> Program:
        # we don't use this puzzle - '(x pubkey)'
        # TODO: check we aren't bricking ourself if someone is stupid enough to actually send to this address
        prog: Program = Program.to([8, bytes(pk)])
        return prog

    async def generate_new_nft(
        self, metadata: Program, percentage: uint64, backpayment_address: bytes32
    ) -> Optional[TransactionRecord]:
        """
        This must be called under the wallet state manager lock
        """
        amount = 1
        coins = await self.standard_wallet.select_coins(amount)
        if coins is None:
            return None

        origin = coins.copy().pop()
        genesis_launcher_puz = nft_puzzles.LAUNCHER_PUZZLE
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), uint64(amount))

        nft_transfer_program = nft_puzzles.get_transfer_puzzle()
        eve_fullpuz = nft_puzzles.create_full_puzzle(
            launcher_coin.name(),
            self.nft_wallet_info.my_did,
            nft_transfer_program.get_tree_hash(),
            metadata,
            backpayment_address,
            percentage,
        )
        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([eve_fullpuz.get_tree_hash(), amount, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

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

        genesis_launcher_solution = Program.to([eve_fullpuz.get_tree_hash(), amount, bytes(0x80)])

        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))

        eve_coin = Coin(launcher_coin.name(), eve_fullpuz.get_tree_hash(), uint64(amount))

        if tx_record is None or tx_record.spend_bundle is None:
            return None

        # EVE SPEND BELOW
        did_wallet = self.wallet_state_manager.wallets[self.nft_wallet_info.did_wallet_id]
        # Create a puzzle announcement
        puzzle_announcements = ["a"]
        message_sb = await did_wallet.create_message_spend(puzzle_announcements=puzzle_announcements)
        if message_sb is None:
            raise ValueError("Unable to created DID message spend.")

        innersol = Program.to([did_wallet.did_info.current_inner.get_tree_hash(), 0])
        fullsol = Program.to(
            [
                [launcher_coin.parent_coin_info, launcher_coin.amount],
                eve_coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [CoinSpend(eve_coin, eve_fullpuz, fullsol)]
        eve_spend_bundle = SpendBundle(list_of_coinspends, AugSchemeMPL.aggregate([]))
        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, eve_spend_bundle, launcher_sb, message_sb])
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
        await self.add_transfer_program(nft_transfer_program, in_transaction=False)
        return nft_record

    async def make_announce_spend(self, nft_coin_info: NFTCoinInfo) -> SpendBundle:
        did_wallet = self.wallet_state_manager.wallets[self.nft_wallet_info.did_wallet_id]
        # Create a puzzle announcement
        puzzle_announcements = ["a"]
        message_sb = await did_wallet.create_message_spend(puzzle_announcements=puzzle_announcements)
        if message_sb is None:
            raise ValueError("Unable to created DID message spend.")

        innersol = Program.to(
            [
                did_wallet.did_info.current_inner.get_tree_hash(),
                0,
            ]
        )
        fullsol = Program.to(
            [
                nft_coin_info.lineage_proof.to_program(),
                nft_coin_info.coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [CoinSpend(nft_coin_info.coin, nft_coin_info.full_puzzle, fullsol)]
        spend_bundle = SpendBundle(list_of_coinspends, AugSchemeMPL.aggregate([]))
        full_spend = SpendBundle.aggregate([spend_bundle, message_sb])
        nft_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=nft_coin_info.coin.puzzle_hash,
            amount=uint64(nft_coin_info.coin.amount),
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

    async def transfer_nft(
        self,
        nft_coin_info: NFTCoinInfo,
        new_did,
        new_did_inner_hash,
        trade_prices_list,
        new_url=0,
    ):
        did_wallet = self.wallet_state_manager.wallets[self.nft_wallet_info.did_wallet_id]
        transfer_prog = nft_coin_info.transfer_program
        # (sha256tree1 (list transfer_program_solution new_did))
        transfer_program_solution = [trade_prices_list, new_url]  # TODO: Make this flexible for other transfer_programs
        puzzle_announcements = [Program.to([transfer_program_solution, bytes(new_did)]).get_tree_hash()]
        message_sb = await did_wallet.create_message_spend(puzzle_announcements=puzzle_announcements)
        if message_sb is None:
            raise ValueError("Unable to created DID message spend.")
        # my_did_inner_hash
        # new_did
        # new_did_inner_hash
        # transfer_program_reveal
        # transfer_program_solution

        innersol = Program.to(
            [
                did_wallet.did_info.current_inner.get_tree_hash(),
                new_did,
                new_did_inner_hash,
                transfer_prog,
                transfer_program_solution,  # this should be expanded for other possible transfer_programs
            ]
        )
        fullsol = Program.to(
            [
                nft_coin_info.lineage_proof.to_program(),
                nft_coin_info.coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [CoinSpend(nft_coin_info.coin, nft_coin_info.full_puzzle, fullsol)]
        spend_bundle = SpendBundle(list_of_coinspends, AugSchemeMPL.aggregate([]))
        full_spend = SpendBundle.aggregate([spend_bundle, message_sb])
        # this full spend should be aggregated with the DID announcement spend of the recipient DID
        if Program.to(trade_prices_list) == Program.to(0):
            nft_record = TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=did_wallet.did_info.origin_coin.name(),
                amount=uint64(nft_coin_info.coin.amount),
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

    async def receive_nft(self, sending_sb: SpendBundle, fee: uint64 = uint64(0)) -> SpendBundle:
        trade_price_list_discovered = None
        nft_id = None

        for coin_spend in sending_sb.coin_spends:
            if nft_puzzles.match_nft_puzzle(Program.from_bytes(bytes(coin_spend.puzzle_reveal)))[0]:
                inner_sol = Program.from_bytes(bytes(coin_spend.solution)).rest().rest().first()
                trade_price_list_discovered = nft_puzzles.get_trade_prices_list_from_inner_solution(inner_sol)
                nft_id = nft_puzzles.get_nft_id_from_puzzle(Program.from_bytes(bytes(coin_spend.puzzle_reveal)))
                royalty_address = nft_puzzles.get_royalty_address_from_puzzle(
                    Program.from_bytes(bytes(coin_spend.puzzle_reveal))
                )
                royalty_percentage = nft_puzzles.get_percentage_from_puzzle(
                    Program.from_bytes(bytes(coin_spend.puzzle_reveal))
                )

        assert trade_price_list_discovered is not None
        assert nft_id is not None

        did_wallet = self.wallet_state_manager.wallets[self.nft_wallet_info.did_wallet_id]
        if trade_price_list_discovered == Program.to(0):
            nft_record = TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=did_wallet.did_info.origin_coin.name(),
                amount=uint64(coin_spend.coin.amount),
                fee_amount=uint64(0),
                confirmed=False,
                sent=uint32(0),
                spend_bundle=sending_sb,
                additions=sending_sb.additions(),
                removals=sending_sb.removals(),
                wallet_id=self.wallet_info.id,
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.OUTGOING_TX.value),
                name=bytes32(token_bytes()),
                memos=[],
            )
            await self.standard_wallet.push_transaction(nft_record)

        backpayment_amount = 0
        sb_list = [sending_sb]

        for pair in trade_price_list_discovered.as_iter():
            if len(pair.as_python()) == 1:
                backpayment_amount += pair.first().as_int()
            elif len(pair.as_python()) >= 2:
                asset_id = pair.rest().first().as_atom()
                amount = (pair.first().as_int() * royalty_percentage) // 10000
                cat_wallet = await self.wallet_state_manager.get_wallet_for_asset_id(asset_id.hex())
                assert cat_wallet is not None  # TODO: catch this neater, maybe
                settlement_ph: bytes32 = construct_cat_puzzle(CAT_MOD, asset_id, OFFER_MOD).get_tree_hash()
                cat_tx_list = await cat_wallet.generate_signed_transaction([amount], [OFFER_MOD.get_tree_hash()])
                cat_sb = cat_tx_list[0].spend_bundle
                sb_list.append(cat_sb)
                coin = None
                spendable_cc_list = []
                # breakpoint()
                # Generate the spend of the royalty amount
                # TODO: refactor this out of the NFTWallet
                for coin in cat_sb.additions():
                    if coin.puzzle_hash == settlement_ph:
                        nonce = nft_id
                        for cs in cat_sb.coin_spends:
                            if cs.coin.name() == coin.parent_coin_info:
                                cat_inner: Program = get_innerpuzzle_from_puzzle(cs.puzzle_reveal)
                                new_spendable_cc = SpendableCAT(
                                    coin,
                                    asset_id,
                                    OFFER_MOD,
                                    Program.to([(nonce, [[royalty_address, amount]])]),
                                    lineage_proof=LineageProof(
                                        cs.coin.parent_coin_info, cat_inner.get_tree_hash(), cs.coin.amount
                                    ),
                                )
                                spendable_cc_list.append(new_spendable_cc)
                                break

                cat_spend_bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cc_list)
                sb_list.append(cat_spend_bundle)
                # spend_list.append(CoinSpend(coin, construct_cat_puzzle(CAT_MOD, asset_id, OFFER_MOD), ))
        # offers_sb = SpendBundle(spend_list, AugSchemeMPL.aggregate([]))
        # sb_list.append(offers_sb)
        puzzle_announcements = [Program.to(trade_price_list_discovered.get_tree_hash() + bytes(nft_id))]
        message_sb = await did_wallet.create_message_spend(puzzle_announcements=puzzle_announcements)
        if message_sb is None:
            raise ValueError("Unable to created DID message spend.")
        sb_list.append(message_sb)
        if backpayment_amount % 2 != 1:
            backpayment_amount += 1
        relative_amount = (fee + backpayment_amount) * -1
        standard_sb = await self.standard_wallet.create_spend_bundle_relative_chia(relative_amount)
        sb_list.append(standard_sb)
        full_spend = SpendBundle.aggregate(sb_list)
        nft_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=did_wallet.did_info.origin_coin.name(),
            amount=uint64(coin_spend.coin.amount),
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
