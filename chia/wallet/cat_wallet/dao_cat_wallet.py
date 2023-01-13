from __future__ import annotations

import dataclasses
import logging
import time
import traceback
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.wallet.util.wallet_types import WalletType
from blspy import AugSchemeMPL, G2Element, G1Element
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    match_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.dao_cat_info import DAOCATInfo
from chia.wallet.coin_selection import select_coins


CAT_MOD_HASH = CAT_MOD.get_tree_hash()


class DAOCATWallet(CATWallet):
    dao_cat_info: DAOCATInfo

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DAO_CAT)

    # MH: at the moment this is mixing clean and dirty coins, meaning we'll have to search for the stored coin info again later
    # maybe we change this to return the full records and just add the clean ones ourselves later
    async def advanced_select_coins(self, amount: uint64, proposal_id: bytes32) -> Set[Coin]:
        coins = Set()
        sum = 0
        for coin in self.dao_cat_info.locked_coins:
            compatible = True
            for prev_vote in coin.previous_votes:
                if prev_vote == proposal_id:
                    compatible = False
                    break
            if compatible:
                coins.add(coin.coin)
                sum += coin.coin.amount
                if sum >= amount:
                    break
        # try and get already locked up coins first
        if sum >= amount:
            return coins
        coins = await select_coins(amount - sum(c.amount for c in coins))
        assert sum(c.amount for c in coins) >= amount
        # loop through our coins and check which ones haven't yet voted on that proposal and add them to coins set
        return coins

    async def create_vote_spend(amount: uint64, proposal_id: bytes32, is_yes_vote: bool):

        return

    async def enter_vote_state():

        return

    async def exit_vote_state():

        return
