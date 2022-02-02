import logging
import time
import json
from dataclasses import dataclass
from chia.util.streamable import streamable, Streamable
from typing import Dict, Optional, List, Any, Set, Tuple
from blspy import AugSchemeMPL, G1Element
from secrets import token_bytes
from chia.protocols import wallet_protocol
from chia.protocols.wallet_protocol import CoinState
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64, uint32, uint8
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.nft_wallet import nft_puzzles
from chia.util.json_util import dict_to_json_str
from chia.protocols.wallet_protocol import PuzzleSolutionResponse
from chia.server.outbound_message import NodeType
from chia.server.ws_connection import WSChiaConnection


@dataclass(frozen=True)
@streamable
class NFTCoinInfo(Streamable):
    coin: Coin
    lineage_proof: LineageProof
    transfer_program: Program
    full_puzzle: Program


@dataclass(frozen=True)
@streamable
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

    @staticmethod
    async def create_new_nft_wallet(
        wallet_state_manager: Any,
        wallet: Wallet,
        did_wallet_id: int,
        name: str = None,
    ):
        """
        This must be called under the wallet state manager lock
        """
        self = NFTWallet()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        did_wallet = self.wallet_state_manager.wallets[did_wallet_id]
        my_did = did_wallet.did_info.origin_coin.name()
        self.nft_wallet_info = NFTWalletInfo(my_did, did_wallet_id, [], [])
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
        full_nodes: Dict[bytes32, WSChiaConnection] = self.wallet_state_manager.wallet_node.server.connection_by_type.get(NodeType.FULL_NODE, {})

        for node_id, node in full_nodes.copy().items():
            await self.wallet_state_manager.wallet_node.subscribe_to_phs([my_did], node)
        await self.wallet_state_manager.add_interested_puzzle_hash(my_did, self.wallet_id)
        return self

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = None,
    ):
        self = NFTWallet()
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

    def id(self):
        return self.wallet_info.id

    async def add_nft_coin(self, coin, spent_height):
        await self.coin_added(coin, spent_height)
        return

    async def coin_added(self, coin: Coin, height: uint32):
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f" NFT wallet has been notified that {coin} was added")
        wallet_node = self.wallet_state_manager.wallet_node
        server = wallet_node.server
        full_nodes: Dict[bytes32, WSChiaConnection] = server.connection_by_type.get(NodeType.FULL_NODE, {})
        cs: Optional[CoinSpend] = None
        coin_states: Optional[List[CoinState]] = await self.wallet_state_manager.get_coin_state([coin.parent_coin_info])
        assert coin_states is not None
        parent_coin = coin_states[0].coin
        for node_id in full_nodes:
            node = server.all_connections[node_id]
            cs: CoinSpend = await wallet_node.fetch_puzzle_solution(
                node, height, parent_coin
            )
            if cs is not None:
                break
        assert cs is not None
        await self.puzzle_solution_received(cs)

    async def puzzle_solution_received(self, coin_spend: CoinSpend):
        coin_name = coin_spend.coin.name()
        puzzle: Program = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
        solution: Program = Program.from_bytes(bytes(coin_spend.solution))
        matched, curried_args = nft_puzzles.match_nft_puzzle(puzzle)
        nft_transfer_program = None
        if matched:
            nft_mod_hash, singleton_struct, current_owner, nft_transfer_program_hash = curried_args
            # check if we already know this hash, if not then try to find reveal in solution
            for hash, reveal in self.nft_wallet_info.known_transfer_programs:
                if hash == bytes32(nft_transfer_program_hash.as_atom()):
                    nft_transfer_program = reveal
            if nft_transfer_program is None:
                attempt = nft_puzzles.get_transfer_program_from_solution(solution)
                if attempt is not None:
                    nft_transfer_program = attempt
                    await self.add_transfer_program(nft_transfer_program)
            assert nft_transfer_program is not None
            self.log.info(f"found the info for coin {coin_name}")
            parent_coin = None
            coin_record = await self.wallet_state_manager.coin_store.get_coin_record(coin_name)
            if coin_record is None:
                coin_states: Optional[List[CoinState]] = await self.wallet_state_manager.get_coin_state([coin_name])
                if coin_states is not None:
                    parent_coin = coin_states[0].coin
            if coin_record is not None:
                parent_coin = coin_record.coin
            if parent_coin is None:
                raise ValueError("Error in finding parent")
            inner_puzzle = nft_puzzles.create_nft_layer_puzzle(singleton_struct.rest().first().as_atom(), current_owner.as_atom(), nft_transfer_program_hash.as_atom())
            child_puzzle = nft_puzzles.create_full_puzzle(singleton_struct.rest().first().as_atom(), self.nft_wallet_info.my_did, nft_transfer_program_hash.as_atom())
            await self.add_coin(
                coin_spend.coin,
                LineageProof(parent_coin.parent_coin_info, inner_puzzle.get_tree_hash(), parent_coin.amount),
                nft_transfer_program,
                child_puzzle
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

    async def add_coin(self, coin: Coin, lineage_proof: LineageProof, transfer_program: Program, puzzle: Program):
        my_nft_coins = self.nft_wallet_info.my_nft_coins
        my_nft_coins.append(NFTCoinInfo(coin, lineage_proof, transfer_program, puzzle))
        new_nft_wallet_info = NFTWalletInfo(self.nft_wallet_info.my_did, self.nft_wallet_info.did_wallet_id, my_nft_coins, self.nft_wallet_info.known_transfer_programs)
        await self.save_info(new_nft_wallet_info, False)
        return

    async def remove_coin(self, coin: Coin):
        my_nft_coins = self.nft_wallet_info.my_nft_coins
        for coin_info in my_nft_coins:
            if coin_info.coin == coin:
                my_nft_coins.remove(coin_info)
        new_nft_wallet_info = NFTWalletInfo(self.nft_wallet_info.my_did, self.nft_wallet_info.did_wallet_id, my_nft_coins, self.nft_wallet_info.known_transfer_programs)
        await self.save_info(new_nft_wallet_info)
        return

    async def add_transfer_program(self, transfer_program: Program):
        my_transfer_programs = self.nft_wallet_info.known_transfer_programs
        my_transfer_programs.append((transfer_program.get_tree_hash(), transfer_program))
        new_nft_wallet_info = NFTWalletInfo(self.nft_wallet_info.my_did, self.nft_wallet_info.did_wallet_id, self.nft_wallet_info.my_nft_coins, my_transfer_programs)
        await self.save_info(new_nft_wallet_info, False)
        return

    def puzzle_for_pk(self, pk):
        # we don't use this puzzle - '(x pubkey)'
        # TODO: check we aren't bricking ourself if someone is stupid enough to actually send to this address
        return Program.to([8, pk])

    async def generate_new_nft(
        self,
        uri: str,
        percentage: uint64,
        backpayment_address: bytes32,
        amount: int = 1
    ) -> Optional[TransactionRecord]:
        """
        This must be called under the wallet state manager lock
        """
        coins = await self.standard_wallet.select_coins(amount)
        if coins is None:
            return None

        origin = coins.copy().pop()
        genesis_launcher_puz = nft_puzzles.LAUNCHER_PUZZLE
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), amount)

        nft_transfer_program = nft_puzzles.create_transfer_puzzle(uri, percentage, backpayment_address)
        eve_fullpuz = nft_puzzles.create_full_puzzle(
            launcher_coin.name(),
            self.nft_wallet_info.my_did,
            nft_transfer_program.get_tree_hash()
        )
        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([eve_fullpuz.get_tree_hash(), amount, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

        tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            amount, genesis_launcher_puz.get_tree_hash(), uint64(0), origin.name(), coins, None, False, announcement_set
        )

        genesis_launcher_solution = Program.to([eve_fullpuz.get_tree_hash(), amount, bytes(0x80)])

        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))

        eve_coin = Coin(launcher_coin.name(), eve_fullpuz.get_tree_hash(), amount)

        if tx_record is None or tx_record.spend_bundle is None:
            return None

        # EVE SPEND BELOW
        did_wallet = self.wallet_state_manager.wallets[self.nft_wallet_info.did_wallet_id]
        # 1 is a coin announcement
        messages = [(1, 'a')]
        message_sb = await did_wallet.create_message_spend(messages)
        if message_sb is None:
            raise ValueError("Unable to created DID message spend.")
        my_did_amount = message_sb.coin_solutions[0].coin.amount
        my_did_parent = message_sb.coin_solutions[0].coin.parent_coin_info

        innersol = Program.to([
            eve_coin.amount,
            did_wallet.did_info.current_inner.get_tree_hash(),
            my_did_amount,
            my_did_parent,
            0
        ])
        fullsol = Program.to(
            [
                [launcher_coin.parent_coin_info, launcher_coin.amount],
                eve_coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [CoinSpend(eve_coin, eve_fullpuz, fullsol)]
        eve_spend_bundle = SpendBundle(list_of_coinspends, AugSchemeMPL.aggregate([]))
        #eve_spend = await self.generate_eve_spend(eve_coin, , did_inner)
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
            name=token_bytes(),
            memos=[],
        )
        await self.standard_wallet.push_transaction(nft_record)
        await self.add_transfer_program(nft_transfer_program)
        return nft_record

    async def make_announce_spend(self, nft_coin_info: NFTCoinInfo):
        did_wallet = self.wallet_state_manager.wallets[self.nft_wallet_info.did_wallet_id]
        # 1 is a coin announcement
        messages = [(1, 'a')]
        message_sb = await did_wallet.create_message_spend(messages)
        if message_sb is None:
            raise ValueError("Unable to created DID message spend.")
        my_did_amount = message_sb.coin_solutions[0].coin.amount
        my_did_parent = message_sb.coin_solutions[0].coin.parent_coin_info

        innersol = Program.to([
            nft_coin_info.coin.amount,
            did_wallet.did_info.current_inner.get_tree_hash(),
            my_did_amount,
            my_did_parent,
            0
        ])
        fullsol = Program.to(
            [
                nft_coin_info.lineage_proof.as_list(),
                nft_coin_info.coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [CoinSpend(nft_coin_info.coin, nft_coin_info.full_puzzle, fullsol)]
        spend_bundle = SpendBundle(list_of_coinspends, AugSchemeMPL.aggregate([]))
        full_spend = SpendBundle.aggregate([spend_bundle, message_sb])
        await self.standard_wallet.push_transaction(nft_record)
        return full_spend

    async def transfer_nft(
        self,
        nft_coin_info: NFTCoinInfo,
        new_did,
        new_did_parent,
        new_did_inner_hash,
        new_did_amount,
        trade_price,
    ):
        did_wallet = self.wallet_state_manager.wallets[self.nft_wallet_info.did_wallet_id]
        # 1 is a coin announcement
        messages = [(1, bytes(trade_price) + bytes(new_did))]  # TODO: check this bytes concatenation is correct
        message_sb = await did_wallet.create_message_spend(messages)
        if message_sb is None:
            raise ValueError("Unable to created DID message spend.")
        my_did_amount = message_sb.coin_solutions[0].coin.amount
        my_did_parent = message_sb.coin_solutions[0].coin.parent_coin_info
        # my_did_inner_hash
        # my_did_amount
        # my_did_parent
        # new_did
        # new_did_parent
        # new_did_inner_hash
        # new_did_amount
        # trade_price
        # transfer_program_reveal
        # transfer_program_solution
        innersol = Program.to([
            nft_coin_info.coin.amount,
            did_wallet.did_info.current_inner.get_tree_hash(),
            my_did_amount,
            my_did_parent,
            new_did,
            new_did_parent,
            new_did_inner_hash,
            new_did_amount,
            trade_price,
            nft_coin_info.transfer_program,
            0,  # this should be expanded for other possible transfer_programs
        ])
        fullsol = Program.to(
            [
                nft_coin_info.lineage_proof.as_list(),
                nft_coin_info.coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [CoinSpend(nft_coin_info.coin, nft_coin_info.full_puzzle, fullsol)]
        spend_bundle = SpendBundle(list_of_coinspends, AugSchemeMPL.aggregate([]))
        full_spend = SpendBundle.aggregate([spend_bundle, message_sb])
        # this full spend should be aggregated with the DID announcement spend of the recipient DID
        return full_spend

    async def receive_nft(self, trade_price: uint64, nft_id: bytes32) -> SpendBundle:
        did_wallet = self.wallet_state_manager.wallets[self.nft_wallet_info.did_wallet_id]
        messages = [(1, bytes(trade_price) + bytes(nft_id))]  # TODO: check this bytes concatenation is correct
        message_sb = await did_wallet.create_message_spend(messages)
        if message_sb is None:
            raise ValueError("Unable to created DID message spend.")
        return message_sb

    async def get_current_nfts(self):
        return self.nft_wallet_info.my_nft_coins

    async def save_info(self, nft_info: NFTWalletInfo, in_transaction):
        self.nft_wallet_info = nft_info
        current_info = self.wallet_info
        data_str = json.dumps(nft_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)
