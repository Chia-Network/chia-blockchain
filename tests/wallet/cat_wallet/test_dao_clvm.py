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
P2_SINGLETON_MOD = load_clvm("p2_singleton_or_delayed_puzhash.clvm")


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
    solution = Program.to([0, 0, [[51, 0xcafef00d, 200]]])
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
        200,
        Program.to(1)
    )
    conds = full_proposal.run(solution)
    assert len(conds.as_python()) == 4


def test_proposal_timer():
    current_cat_issuance = 1000
    proposal_pass_percentage = 15
    CAT_TAIL = Program.to("tail").get_tree_hash()
    treasury_id = Program.to("treasury").get_tree_hash()
    LOCKUP_TIME = 200
    EPHEMERAL_VOTE_PUZHASH = DAO_EPHEMERAL_VOTE_MOD.curry(
        DAO_LOCKUP_MOD.get_tree_hash(),
        DAO_EPHEMERAL_VOTE_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        LOCKUP_TIME,
    ).get_tree_hash()
    singleton_id = Program.to("singleton_id").get_tree_hash()
    singleton_struct = Program.to((SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER)))
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # CAT_MOD_HASH
    # EPHEMERAL_VOTE_PUZZLE_HASH
    # CAT_TAIL
    # CURRENT_CAT_ISSUANCE
    # PROPOSAL_TIMELOCK
    # PROPOSAL_PASS_PERCENTAGE
    # MY_PARENT_SINGLETON_STRUCT
    # TREASURY_ID
    proposal_timer_full = DAO_PROPOSAL_TIMER_MOD.curry(
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        EPHEMERAL_VOTE_PUZHASH,
        CAT_TAIL,
        current_cat_issuance,
        LOCKUP_TIME,
        proposal_pass_percentage,
        singleton_struct,
        treasury_id
    )

    # proposal_current_votes
    # proposal_innerpuzhash
    # proposal_parent_id
    # proposal_amount

    solution = Program.to([140, Program.to(1).get_tree_hash(), Program.to("parent").get_tree_hash(), 23])
    conds = proposal_timer_full.run(solution)
    assert len(conds.as_python()) == 4


def test_treasury():
    current_cat_issuance = 1000
    proposal_pass_percentage = 15
    CAT_TAIL = Program.to("tail").get_tree_hash()
    treasury_id = Program.to("treasury").get_tree_hash()
    LOCKUP_TIME = 200
    EPHEMERAL_VOTE_PUZHASH = DAO_EPHEMERAL_VOTE_MOD.curry(
        DAO_LOCKUP_MOD.get_tree_hash(),
        DAO_EPHEMERAL_VOTE_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        LOCKUP_TIME,
    ).get_tree_hash()
    singleton_id = Program.to("singleton_id").get_tree_hash()
    singleton_struct = Program.to((SINGLETON_MOD, (singleton_id, SINGLETON_LAUNCHER)))
    # SINGLETON_STRUCT
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # EPHEMERAL_VOTE_PUZHASH  ; this is the mod fully curried - effectively still a constant
    # P2_SINGLETON_MOD
    # CAT_MOD_HASH
    # CAT_TAIL
    # CURRENT_CAT_ISSUANCE
    # PROPOSAL_PASS_PERCENTAGE
    # PROPOSAL_TIMELOCK
    full_treasury_puz = DAO_TREASURY_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        EPHEMERAL_VOTE_PUZHASH,
        P2_SINGLETON_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        current_cat_issuance,
        proposal_pass_percentage,
        LOCKUP_TIME,
    )

    # spend_type  ; TODO: optimise this out
    # amount_or_new_puzhash
    # new_amount
    # my_puzhash_or_proposal_id
    # proposal_innerpuz
    # proposal_current_votes

    solution = Program.to([0, 200, 300, full_treasury_puz.get_tree_hash()])
    conds = full_treasury_puz.run(solution)
    assert len(conds.as_python()) == 3

    # solution = Program.to([1, ])


def test_ephemeral_vote():
    current_cat_issuance = 1000
    proposal_pass_percentage = 15
    CAT_TAIL = Program.to("tail").get_tree_hash()
    treasury_id = Program.to("treasury").get_tree_hash()
    LOCKUP_TIME = 200
    full_ephemeral_vote_puzzle = DAO_EPHEMERAL_VOTE_MOD.curry(
        DAO_LOCKUP_MOD.get_tree_hash(),
        DAO_EPHEMERAL_VOTE_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        LOCKUP_TIME,
    )
    # return_address
    # proposal_id
    # previous_votes
    # my_amount  ; this is the weight of your vote
    # vote_info  ; this is the information about what to do with your vote  - atm just 1 for yes or 0 for no
    solution = Program.to([0xcafef00d, 0xdeadbeef, [0xfadeddab], 20, 1, 0x12341234])
    conds = full_ephemeral_vote_puzzle.run(solution)
    assert len(conds.as_python()) == 4


def test_lockup():
    # LOCKUP_MOD_HASH
    # EPHEMERAL_VOTE_MODHASH
    # CAT_MOD_HASH
    # CAT_TAIL
    # RETURN_ADDRESS
    # PREVIOUS_VOTES
    # LOCKUP_TIME
    CAT_TAIL = Program.to("tail").get_tree_hash()
    LOCKUP_TIME = 200

    full_lockup_puz = DAO_LOCKUP_MOD.curry(
        DAO_LOCKUP_MOD.get_tree_hash(),
        DAO_EPHEMERAL_VOTE_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        [0xfadeddab],
        LOCKUP_TIME,
        0x12341234
    )
    # spend_type
    # my_id
    # my_amount
    # new_proposal_vote_id
    # vote_info
    solution = Program.to([1, 0xdeadbeef, 20, 0xbaddadab, 1])
    conds = full_lockup_puz.run(solution)
    assert len(conds.as_python()) == 5
