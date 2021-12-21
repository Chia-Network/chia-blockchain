import logging
import time
import json

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


class NFTCoinInfo:
    coin: Coin
    lineage_proof: LineageProof
    transfer_program: Program


class NFTWalletInfo:
    my_did: bytes32
    did_wallet_id: int
    my_nft_coins: List[NFTCoinInfo]


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
        std_wallet_id = self.standard_wallet.wallet_id
        self.wallet_state_manager = wallet_state_manager
        my_did: bytes32 = await self.wallet_state_manager.wallets[did_wallet_id].did_info.origin_coin.name()
        self.nft_wallet_info = NFTWalletInfo(my_did, did_wallet_id, [])
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
        await self.wallet_state_manager.add_interested_puzzle_hash(my_did)
        await self.wallet_state_manager.wallet_node.subscribe_to_phs(my_did)

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

        data: Dict[str, Any] = {
            "data": {
                "action_data": {
                    "api_name": "request_puzzle_solution",
                    "height": height,
                    "coin_name": coin.parent_coin_info,
                    "received_coin": coin.name(),
                }
            }
        }

        data_str = dict_to_json_str(data)
        await self.wallet_state_manager.create_action(
            name="request_puzzle_solution",
            wallet_id=self.id(),
            wallet_type=self.type(),
            callback="puzzle_solution_received",
            done=False,
            data=data_str,
            in_transaction=True,
        )

    async def puzzle_solution_received(self, response: PuzzleSolutionResponse, action_id: int):
        coin_name = response.coin_name
        puzzle: Program = response.puzzle
        matched, curried_args = nft_puzzles.match_nft_puzzle(puzzle)
        if matched:
            nft_mod_hash, singleton_struct, current_owner, nft_transfer_program_hash = curried_args
            nft_transfer_program = nft_puzzles.get_transfer_program_from_solution(response.solution)
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
            inner_puzzle = nft_puzzles.create_nft_layer_puzzle(singleton_struct.rest().first(), current_owner, nft_transfer_program)
            await self.add_coin(
                coin_name,
                LineageProof(parent_coin.parent_coin_info, inner_puzzle.get_tree_hash(), parent_coin.amount),
                nft_transfer_program_hash,
            )
            await self.wallet_state_manager.action_store.action_done(action_id)
        else:
            # The parent is not an NFT which means we need to scrub all of its children from our DB
            child_coin_records = await self.wallet_state_manager.coin_store.get_coin_records_by_parent_id(coin_name)
            if len(child_coin_records) > 0:
                for record in child_coin_records:
                    if record.wallet_id == self.id():
                        await self.wallet_state_manager.coin_store.delete_coin_record(record.coin.name())
                        await self.remove_lineage(record.coin.name())
                        # We also need to make sure there's no record of the transaction
                        await self.wallet_state_manager.tx_store.delete_transaction_record(record.coin.name())

    async def add_coin(self, coin, lineage_proof, transfer_program):
        my_nft_coins = self.nft_wallet_info.my_nft_coins
        my_nft_coins.append(NFTCoinInfo(coin, lineage_proof, transfer_program))
        new_nft_wallet_info = NFTWalletInfo(self.nft_wallet_info.my_did, self.nft_wallet_info.did_wallet_id, my_nft_coins)
        await self.save_info(new_nft_wallet_info)
        return

    async def remove_coin(self, coin):
        my_nft_coins = self.nft_wallet_info.my_nft_coins
        for coin_info in my_nft_coins:
            if coin_info.coin == coin:
                my_nft_coins.remove(coin_info)
        new_nft_wallet_info = NFTWalletInfo(self.nft_wallet_info.my_did, self.nft_wallet_info.did_wallet_id, my_nft_coins)
        await self.save_info(new_nft_wallet_info)
        return

    async def save_info(self, nft_info: NFTWalletInfo, in_transaction):
        self.nft_wallet_info = nft_info
        current_info = self.wallet_info
        data_str = bytes(nft_info).hex()
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)
