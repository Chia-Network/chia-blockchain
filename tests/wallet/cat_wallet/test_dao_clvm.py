from typing import List, Tuple, Optional, Dict

import pytest
from blspy import PrivateKey, AugSchemeMPL, G2Element
from clvm.casts import int_to_bytes
from chia.wallet.puzzles.load_clvm import load_clvm

from chia.clvm.spend_sim import SpendSim, SimClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.puzzles.cat_loader import CAT_MOD


def test_loading():
    DAO_EPHEMERAL_VOTE_MOD = load_clvm("dao_ephemeral_vote.clvm")
    DAO_LOCKUP_MOD = load_clvm("dao_lockup.clvm")
    DAO_PROPOSAL_TIMER_MOD = load_clvm("dao_proposal_timer.clvm")
    DAO_PROPOSAL_MOD = load_clvm("dao_proposal.clvm")
    DAO_TREASURY_MOD = load_clvm("dao_treasury.clvm")
    breakpoint()
