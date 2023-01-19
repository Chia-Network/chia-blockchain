from __future__ import annotations

import dataclasses
import logging
import time
import traceback
from secrets import token_bytes
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from blspy import AugSchemeMPL, G1Element, G2Element

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.server.ws_connection import WSChiaConnection
from chia.wallet.lineage_proof import LineageProof
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    match_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.dao_cat_info import DAOCATInfo
from chia.wallet.cat_wallet.lineage_store import CATLineageStore
from chia.wallet.coin_selection import select_coins
from chia.wallet.dao_wallet.dao_utils import get_lockup_puzzle
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash, curry_and_treehash
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_state_manager import WalletStateManager

CAT_MOD_HASH = CAT_MOD.get_tree_hash()
CAT_MOD_HASH_HASH = Program.to(CAT_MOD_HASH).get_tree_hash()
QUOTED_MOD_HASH = calculate_hash_of_quoted_mod_hash(CAT_MOD_HASH)


class DAOCATWallet:
    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_info: WalletInfo
    dao_cat_info: DAOCATInfo
    standard_wallet: Wallet
    cost_of_single_tx: Optional[int]
    lineage_store: CATLineageStore

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DAO_CAT)

    @staticmethod
    async def get_or_create_wallet_for_cat(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        limitations_program_hash_hex: str,
        name: Optional[str] = None,
    ) -> DAOCATWallet:
        self = DAOCATWallet()
        self.cost_of_single_tx = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(__name__)

        limitations_program_hash_hex = bytes32.from_hexstr(limitations_program_hash_hex).hex()  # Normalize the format

        dao_wallet_id = None
        free_cat_wallet_id = None
        for id, w in wallet_state_manager.wallets.items():
            if w.type() == DAOCATWallet.type():
                assert isinstance(w, DAOCATWallet)
                if w.get_asset_id() == limitations_program_hash_hex:
                    self.log.warning("Not creating wallet for already existing DAO CAT wallet")
                    return w
            elif w.type() == CATWallet.type():
                assert isinstance(w, CATWallet)
                if w.get_asset_id() == limitations_program_hash_hex:
                    free_cat_wallet_id = w.id()
        assert free_cat_wallet_id is not None
        for id, w in wallet_state_manager.wallets.items():
            if w.type() == WalletType.DAO:
                if w.get_cat_wallet_id() == free_cat_wallet_id:
                    dao_wallet_id = w.id()
        assert dao_wallet_id is not None
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = CATWallet.default_wallet_name_for_unknown_cat(limitations_program_hash_hex)

        limitations_program_hash = bytes32(hexstr_to_bytes(limitations_program_hash_hex))

        self.dao_cat_info = DAOCATInfo(
            dao_wallet_id,
            free_cat_wallet_id,
            limitations_program_hash,
            None,
            [],
        )
        info_as_string = bytes(self.dao_cat_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(name, WalletType.DAO_CAT, info_as_string)

        self.lineage_store = await CATLineageStore.create(self.wallet_state_manager.db_wrapper, self.get_asset_id())
        await self.wallet_state_manager.add_new_wallet(self, self.id())
        return self

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"CAT wallet has been notified that {coin} was added")

        inner_puzzle = await self.inner_puzzle_for_cat_puzhash(coin.puzzle_hash)
        lineage_proof = LineageProof(coin.parent_coin_info, inner_puzzle.get_tree_hash(), uint64(coin.amount))
        breakpoint()
        await self.add_lineage(coin.name(), lineage_proof)

        lineage = await self.get_lineage_proof_for_coin(coin)

        if lineage is None:
            try:
                coin_state = await self.wallet_state_manager.wallet_node.get_coin_state(
                    [coin.parent_coin_info], peer=peer
                )
                assert coin_state[0].coin.name() == coin.parent_coin_info
                coin_spend = await self.wallet_state_manager.wallet_node.fetch_puzzle_solution(
                    coin_state[0].spent_height, coin_state[0].coin, peer
                )
                await self.puzzle_solution_received(coin_spend, parent_coin=coin_state[0].coin)
            except Exception as e:
                self.log.debug(f"Exception: {e}, traceback: {traceback.format_exc()}")

    # maybe we change this to return the full records and just add the clean ones ourselves later
    async def advanced_select_coins(self, amount: uint64, proposal_id: bytes32) -> Set[Coin]:
        coins = set()
        s = 0
        for coin in self.dao_cat_info.locked_coins:
            compatible = True
            for prev_vote in coin.previous_votes:
                if prev_vote == proposal_id:
                    compatible = False
                    break
            if compatible:
                coins.add(coin.coin)
                s += coin.coin.amount
                if s >= amount:
                    break
        assert sum(c.amount for c in coins) >= amount
        return coins

    def id(self) -> uint32:
        return self.wallet_info.id

    async def create_vote_spend(amount: uint64, proposal_id: bytes32, is_yes_vote: bool):

        return

    async def get_new_vote_state_puzzle(self, coins: Optional[List[Coin]] = None):
        innerpuz = await self.get_new_inner_puzzle()
        puzzle = get_lockup_puzzle(
            self.dao_cat_info.limitations_program_hash,
            [],
            innerpuz,
        )
        cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, self.dao_cat_info.limitations_program_hash, puzzle)
        await self.wallet_state_manager.add_interested_puzzle_hashes([puzzle.get_tree_hash()], [self.id()])
        await self.wallet_state_manager.add_interested_puzzle_hashes([cat_puzzle.get_tree_hash()], [self.id()])
        breakpoint()
        return puzzle

    async def exit_vote_state():

        return

    async def add_coin_to_tracked_list():

        return

    async def update_coin_in_tracked_list():

        return

    def get_asset_id(self):
        return bytes(self.dao_cat_info.limitations_program_hash).hex()

    async def get_new_inner_hash(self) -> bytes32:
        puzzle = await self.get_new_inner_puzzle()
        return puzzle.get_tree_hash()

    async def get_new_inner_puzzle(self) -> Program:
        return await self.standard_wallet.get_new_puzzle()

    # MH: I have a feeling we may want the real full puzzle here
    async def get_new_puzzlehash(self) -> bytes32:
        return await self.standard_wallet.get_new_puzzlehash()

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        inner_puzzle = self.standard_wallet.puzzle_for_pk(pubkey)
        cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, self.dao_cat_info.limitations_program_hash, inner_puzzle)
        return cat_puzzle

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        inner_puzzle_hash = self.standard_wallet.puzzle_hash_for_pk(pubkey)
        limitations_program_hash_hash = Program.to(self.dao_cat_info.limitations_program_hash).get_tree_hash()
        return curry_and_treehash(QUOTED_MOD_HASH, CAT_MOD_HASH_HASH, limitations_program_hash_hash, inner_puzzle_hash)

    def require_derivation_paths(self) -> bool:
        return True

    async def get_cat_spendable_coins(self, records: Optional[Set[WalletCoinRecord]] = None) -> List[WalletCoinRecord]:
        result: List[WalletCoinRecord] = []

        record_list: Set[WalletCoinRecord] = await self.wallet_state_manager.get_spendable_coins_for_wallet(
            self.id(), records
        )

        for record in record_list:
            lineage = await self.get_lineage_proof_for_coin(record.coin)
            if lineage is not None and not lineage.is_none():
                result.append(record)

        return result

    async def get_spendable_balance(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        coins = await self.get_cat_spendable_coins(records)
        amount = 0
        for record in coins:
            amount += record.coin.amount

        return uint128(amount)
