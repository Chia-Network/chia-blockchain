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

SINGLETON_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")
DAO_EPHEMERAL_VOTE_MOD = load_clvm("dao_ephemeral_vote.clvm")
DAO_LOCKUP_MOD = load_clvm("dao_lockup.clvm")
DAO_PROPOSAL_TIMER_MOD = load_clvm("dao_proposal_timer.clvm")
DAO_PROPOSAL_MOD = load_clvm("dao_proposal.clvm")
DAO_TREASURY_MOD = load_clvm("dao_treasury.clvm")


def test_proposal():
    # SINGLETON_STRUCT
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # CAT_MOD_HASH
    # EPHEMERAL_VOTE_PUZHASH  ; this is the mod already curried with what it needs - should still be a constant
    # CAT_TAIL
    # CURRENT_CAT_ISSUANCE
    # PROPOSAL_PASS_PERCENTAGE
    # TREASURY_ID
    # PROPOSAL_TIMELOCK
    # VOTES
    # INNERPUZ

    current_cat_issuance = 1000
    proposal_pass_percentage = 15
    CAT_TAIL = Program.to("tail").get_tree_hash()
    treasury_id = Program.to("treasury").get_tree_hash()
    LOCKUP_TIME = 200

    # LOCKUP_MOD_HASH
    # EPHEMERAL_VOTE_MODHASH
    # CAT_MOD_HASH
    # CAT_TAIL
    # LOCKUP_TIME

    EPHEMERAL_VOTE_PUZHASH = DAO_EPHEMERAL_VOTE_MOD.curry(
        DAO_LOCKUP_MOD.get_tree_hash(),
        DAO_EPHEMERAL_VOTE_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        LOCKUP_TIME,
    ).get_tree_hash()

    singleton_id = Program.to("singleton_id").get_tree_hash()
    singleton_struct = Program.to((SINGLETON_MOD, (singleton_id, SINGLETON_LAUNCHER)))
    full_proposal = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        EPHEMERAL_VOTE_PUZHASH,
        CAT_TAIL,
        current_cat_issuance,
        proposal_pass_percentage,
        treasury_id,
        LOCKUP_TIME,
        0,
        Program.to(1)
    )
    # vote_amount
    # vote_info
    # solution
    solution = Program.to([10, 1, 0])
    conds = full_proposal.run(solution)
    assert len(conds.as_python()) == 2
