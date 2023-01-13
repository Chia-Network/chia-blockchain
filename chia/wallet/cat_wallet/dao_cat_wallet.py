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


CAT_MOD_HASH = CAT_MOD.get_tree_hash()


class DAOCATWallet(CATWallet):
    dao_cat_info: DAOCATInfo

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DAO_CAT)

    async def select_coin(amount, proposal_id):
        # for loop through our coins and check which ones haven't yet voted on that proposal
        return

    async def create_vote_spend(amount: uint64, proposal_id: bytes32, is_yes_vote: bool):

        return

    async def enter_vote_state():

        return

    async def exit_vote_state():

        return
