from __future__ import annotations

from typing import Any, List, Optional, Tuple

import pytest
from chia_rs import AugSchemeMPL
from clvm.casts import int_to_bytes

from chia.clvm.spend_sim import SimClient, SpendSim, sim_and_client
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.cat_wallet.cat_utils import CAT_MOD
from chia.wallet.dao_wallet.dao_info import DAORules
from chia.wallet.dao_wallet.dao_utils import curry_singleton, get_p2_singleton_puzhash, get_treasury_puzzle
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.singleton import create_singleton_puzzle_hash

CAT_MOD_HASH: bytes32 = CAT_MOD.get_tree_hash()
SINGLETON_MOD: Program = load_clvm("singleton_top_layer_v1_1.clsp")
SINGLETON_MOD_HASH: bytes32 = SINGLETON_MOD.get_tree_hash()
SINGLETON_LAUNCHER: Program = load_clvm("singleton_launcher.clsp")
SINGLETON_LAUNCHER_HASH: bytes32 = SINGLETON_LAUNCHER.get_tree_hash()
DAO_LOCKUP_MOD: Program = load_clvm("dao_lockup.clsp")
DAO_LOCKUP_MOD_HASH: bytes32 = DAO_LOCKUP_MOD.get_tree_hash()
DAO_PROPOSAL_TIMER_MOD: Program = load_clvm("dao_proposal_timer.clsp")
DAO_PROPOSAL_TIMER_MOD_HASH: bytes32 = DAO_PROPOSAL_TIMER_MOD.get_tree_hash()
DAO_PROPOSAL_MOD: Program = load_clvm("dao_proposal.clsp")
DAO_PROPOSAL_MOD_HASH: bytes32 = DAO_PROPOSAL_MOD.get_tree_hash()
DAO_PROPOSAL_VALIDATOR_MOD: Program = load_clvm("dao_proposal_validator.clsp")
DAO_PROPOSAL_VALIDATOR_MOD_HASH: bytes32 = DAO_PROPOSAL_VALIDATOR_MOD.get_tree_hash()
DAO_TREASURY_MOD: Program = load_clvm("dao_treasury.clsp")
DAO_TREASURY_MOD_HASH: bytes32 = DAO_TREASURY_MOD.get_tree_hash()
SPEND_P2_SINGLETON_MOD: Program = load_clvm("dao_spend_p2_singleton_v2.clsp")
SPEND_P2_SINGLETON_MOD_HASH: bytes32 = SPEND_P2_SINGLETON_MOD.get_tree_hash()
DAO_FINISHED_STATE: Program = load_clvm("dao_finished_state.clsp")
DAO_FINISHED_STATE_HASH: bytes32 = DAO_FINISHED_STATE.get_tree_hash()
DAO_CAT_TAIL: Program = load_clvm(
    "genesis_by_coin_id_or_singleton.clsp", package_or_requirement="chia.wallet.cat_wallet.puzzles"
)
DAO_CAT_TAIL_HASH: bytes32 = DAO_CAT_TAIL.get_tree_hash()
P2_SINGLETON_MOD: Program = load_clvm("p2_singleton_via_delegated_puzzle.clsp")
P2_SINGLETON_MOD_HASH: bytes32 = P2_SINGLETON_MOD.get_tree_hash()
P2_SINGLETON_AGGREGATOR_MOD: Program = load_clvm("p2_singleton_aggregator.clsp")
P2_SINGLETON_AGGREGATOR_MOD_HASH: bytes32 = P2_SINGLETON_AGGREGATOR_MOD.get_tree_hash()
DAO_UPDATE_MOD: Program = load_clvm("dao_update_proposal.clsp")
DAO_UPDATE_MOD_HASH: bytes32 = DAO_UPDATE_MOD.get_tree_hash()


def test_finished_state() -> None:
    """
    Once a proposal has closed, it becomes a 'beacon' singleton which announces
    its proposal ID. This is referred to as the finished state and is used to
    confirm that a proposal has closed in order to release voting CATs from
    the lockup puzzle.
    """
    proposal_id = Program.to("proposal_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (proposal_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    finished_inner_puz = DAO_FINISHED_STATE.curry(singleton_struct, DAO_FINISHED_STATE_HASH)
    finished_full_puz = SINGLETON_MOD.curry(singleton_struct, finished_inner_puz)
    inner_sol = Program.to([1])

    conds = finished_inner_puz.run(inner_sol).as_python()
    assert conds[0][1] == finished_full_puz.get_tree_hash()
    assert conds[2][1] == finished_inner_puz.get_tree_hash()

    lineage = Program.to([proposal_id, finished_inner_puz.get_tree_hash(), 1])
    full_sol = Program.to([lineage, 1, inner_sol])

    conds = conditions_dict_for_solution(finished_full_puz, full_sol, INFINITE_COST)
    assert conds[ConditionOpcode.ASSERT_MY_PUZZLEHASH][0].vars[0] == finished_full_puz.get_tree_hash()
    assert conds[ConditionOpcode.CREATE_COIN][0].vars[0] == finished_full_puz.get_tree_hash()


def test_proposal() -> None:
    """
    This test covers the three paths for closing a proposal:
    - Close a passed proposal
    - Close a failed proposal
    - Self-destruct a broken proposal
    """
    proposal_pass_percentage: uint64 = uint64(5100)
    CAT_TAIL_HASH = Program.to("tail").get_tree_hash()
    treasury_id = Program.to("treasury").get_tree_hash()
    singleton_id = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    self_destruct_time = 1000  # number of blocks
    oracle_spend_delay = 10
    active_votes_list = [0xFADEDDAB]  # are the the ids of previously voted on proposals?
    acs: Program = Program.to(1)
    acs_ph: bytes32 = acs.get_tree_hash()

    dao_lockup_self = DAO_LOCKUP_MOD.curry(
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
    )

    proposal_curry_one = DAO_PROPOSAL_MOD.curry(
        DAO_PROPOSAL_TIMER_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        CAT_MOD_HASH,
        DAO_FINISHED_STATE_HASH,
        DAO_TREASURY_MOD_HASH,
        dao_lockup_self.get_tree_hash(),
        CAT_TAIL_HASH,
        treasury_id,
    )

    # make a lockup puz for the dao cat
    lockup_puz = dao_lockup_self.curry(
        dao_lockup_self.get_tree_hash(),
        active_votes_list,
        acs,  # innerpuz
    )

    dao_cat_puz: Program = CAT_MOD.curry(CAT_MOD_HASH, CAT_TAIL_HASH, lockup_puz)
    dao_cat_puzhash: bytes32 = dao_cat_puz.get_tree_hash()

    # Test Voting
    current_yes_votes = 20
    current_total_votes = 100
    full_proposal: Program = proposal_curry_one.curry(
        proposal_curry_one.get_tree_hash(),
        singleton_id,
        acs_ph,
        current_yes_votes,
        current_total_votes,
    )

    vote_amount = 10
    vote_type = 1  # yes vote
    vote_coin_id = Program.to("vote_coin").get_tree_hash()
    solution: Program = Program.to(
        [
            [vote_amount],  # vote amounts
            vote_type,  # vote type (yes)
            [vote_coin_id],  # vote coin ids
            [active_votes_list],  # previous votes
            [acs_ph],  # lockup inner puz hash
            0,  # inner puz reveal
            0,  # soft close len
            self_destruct_time,
            oracle_spend_delay,
            0,
            1,
        ]
    )

    # Run the proposal and check its conditions
    conditions = conditions_dict_for_solution(full_proposal, solution, INFINITE_COST)

    # Puzzle Announcement of vote_coin_ids
    assert bytes32(conditions[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT][0].vars[0]) == vote_coin_id

    # Assert puzzle announcement from dao_cat of proposal_id and all vote details
    apa_msg = Program.to([singleton_id, vote_amount, vote_type, vote_coin_id]).get_tree_hash()
    assert conditions[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0] == std_hash(dao_cat_puzhash + apa_msg)

    # Check that the proposal recreates itself with updated vote amounts
    next_proposal: Program = proposal_curry_one.curry(
        proposal_curry_one.get_tree_hash(),
        singleton_id,
        acs_ph,
        current_yes_votes + vote_amount,
        current_total_votes + vote_amount,
    )
    assert bytes32(conditions[ConditionOpcode.CREATE_COIN][0].vars[0]) == next_proposal.get_tree_hash()
    assert conditions[ConditionOpcode.CREATE_COIN][0].vars[1] == int_to_bytes(1)

    # Try to vote using multiple coin ids
    vote_coin_id_1 = Program.to("vote_coin_1").get_tree_hash()
    vote_coin_id_2 = Program.to("vote_coin_2").get_tree_hash()
    repeat_solution_1: Program = Program.to(
        [
            [vote_amount, 20],  # vote amounts
            vote_type,  # vote type (yes)
            [vote_coin_id_1, vote_coin_id_2],  # vote coin ids
            [active_votes_list, 0],  # previous votes
            [acs_ph, acs_ph],  # lockup inner puz hash
            0,  # inner puz reveal
            0,  # soft close len
            self_destruct_time,
            oracle_spend_delay,
            0,
            1,
        ]
    )

    conds_repeated = conditions_dict_for_solution(full_proposal, repeat_solution_1, INFINITE_COST)
    assert len(conds_repeated) == 5

    # Try to vote using repeated coin ids
    repeat_solution_2: Program = Program.to(
        [
            [vote_amount, vote_amount, 20],  # vote amounts
            vote_type,  # vote type (yes)
            [vote_coin_id_1, vote_coin_id_1, vote_coin_id_2],  # vote coin ids
            [active_votes_list],  # previous votes
            [acs_ph],  # lockup inner puz hash
            0,  # inner puz reveal
            0,  # soft close len
            self_destruct_time,
            oracle_spend_delay,
            0,
            1,
        ]
    )

    with pytest.raises(ValueError) as e_info:
        conditions_dict_for_solution(full_proposal, repeat_solution_2, INFINITE_COST)
    assert e_info.value.args[0] == "clvm raise"

    # Test Launch
    current_yes_votes = 0
    current_total_votes = 0
    launch_proposal: Program = proposal_curry_one.curry(
        proposal_curry_one.get_tree_hash(),
        singleton_id,
        acs_ph,
        current_yes_votes,
        current_total_votes,
    )
    vote_amount = 10
    vote_type = 1  # yes vote
    vote_coin_id = Program.to("vote_coin").get_tree_hash()
    solution = Program.to(
        [
            [vote_amount],  # vote amounts
            vote_type,  # vote type (yes)
            [vote_coin_id],  # vote coin ids
            # TODO: Check whether previous votes should be 0 in the first spend since
            # proposal looks at (f previous_votes) during loop_over_vote_coins
            [0],  # previous votes
            [acs_ph],  # lockup inner puz hash
            acs,  # inner puz reveal
            0,  # soft close len
            self_destruct_time,
            oracle_spend_delay,
            0,
            1,
        ]
    )
    # Run the proposal and check its conditions
    conditions = conditions_dict_for_solution(launch_proposal, solution, INFINITE_COST)
    # check that the timer is created
    timer_puz = DAO_PROPOSAL_TIMER_MOD.curry(
        proposal_curry_one.get_tree_hash(),
        singleton_struct,
    )
    timer_puzhash = timer_puz.get_tree_hash()
    assert conditions[ConditionOpcode.CREATE_COIN][1].vars[0] == timer_puzhash

    # Test exits

    # Test attempt to close a passing proposal
    current_yes_votes = 200
    current_total_votes = 350
    full_proposal = proposal_curry_one.curry(
        proposal_curry_one.get_tree_hash(),
        singleton_id,
        acs_ph,
        current_yes_votes,
        current_total_votes,
    )
    attendance_required = 200
    proposal_timelock = 20
    soft_close_length = 5
    solution = Program.to(
        [
            Program.to("validator_hash").get_tree_hash(),
            0,
            # Program.to("receiver_hash").get_tree_hash(), # not needed anymore?
            proposal_timelock,
            proposal_pass_percentage,
            attendance_required,
            0,
            soft_close_length,
            self_destruct_time,
            oracle_spend_delay,
            0,
            1,
        ]
    )

    conds = conditions_dict_for_solution(full_proposal, solution, INFINITE_COST)

    # make a matching treasury puzzle for the APA
    treasury_inner: Program = DAO_TREASURY_MOD.curry(
        DAO_TREASURY_MOD_HASH,
        Program.to("validator_hash"),
        proposal_timelock,
        soft_close_length,
        attendance_required,
        proposal_pass_percentage,
        self_destruct_time,
        oracle_spend_delay,
    )
    treasury: Program = SINGLETON_MOD.curry(
        Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_HASH))),
        treasury_inner,
    )
    treasury_puzhash = treasury.get_tree_hash()
    apa_msg = singleton_id

    timer_apa = std_hash(timer_puzhash + singleton_id)
    assert conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0] == timer_apa
    assert conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][1].vars[0] == std_hash(treasury_puzhash + apa_msg)

    # close a failed proposal
    full_proposal = proposal_curry_one.curry(
        proposal_curry_one.get_tree_hash(),
        singleton_id,
        acs_ph,
        20,  # failing number of yes votes
        current_total_votes,
    )
    solution = Program.to(
        [
            Program.to("validator_hash").get_tree_hash(),
            0,
            # Program.to("receiver_hash").get_tree_hash(), # not needed anymore?
            proposal_timelock,
            proposal_pass_percentage,
            attendance_required,
            0,
            soft_close_length,
            self_destruct_time,
            oracle_spend_delay,
            0,
            1,
        ]
    )
    conds = conditions_dict_for_solution(full_proposal, solution, INFINITE_COST)
    apa_msg = int_to_bytes(0)
    assert conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][1].vars[0] == std_hash(treasury_puzhash + apa_msg)
    assert conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0] == timer_apa

    finished_puz = DAO_FINISHED_STATE.curry(singleton_struct, DAO_FINISHED_STATE_HASH)
    assert conds[ConditionOpcode.CREATE_COIN][0].vars[0] == finished_puz.get_tree_hash()

    # self destruct a proposal
    attendance_required = 200
    solution = Program.to(
        [
            Program.to("validator_hash").get_tree_hash(),
            0,
            # Program.to("receiver_hash").get_tree_hash(), # not needed anymore?
            proposal_timelock,
            proposal_pass_percentage,
            attendance_required,
            0,
            soft_close_length,
            self_destruct_time,
            oracle_spend_delay,
            1,
            1,
        ]
    )
    conds = conditions_dict_for_solution(full_proposal, solution, INFINITE_COST)
    assert conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0] == std_hash(treasury_puzhash + apa_msg)
    assert conds[ConditionOpcode.CREATE_COIN][0].vars[0] == finished_puz.get_tree_hash()


def test_proposal_timer() -> None:
    """
    The timer puzzle is created at the same time as a proposal, and enforces a relative time condition on proposals
    The closing time is passed in via the timer solution and confirmed via announcement from the proposal.
    It creates/asserts announcements to pair it with the finishing spend of a proposal.
    The timer puzzle only has one spend path so there is only one test case for this puzzle.
    """
    CAT_TAIL_HASH = Program.to("tail").get_tree_hash()
    treasury_id = Program.to("treasury").get_tree_hash()
    singleton_id = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    dao_lockup_self = DAO_LOCKUP_MOD.curry(
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
    )

    proposal_curry_one = DAO_PROPOSAL_MOD.curry(
        DAO_PROPOSAL_TIMER_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        CAT_MOD_HASH,
        DAO_FINISHED_STATE_HASH,
        DAO_TREASURY_MOD_HASH,
        dao_lockup_self.get_tree_hash(),
        CAT_TAIL_HASH,
        treasury_id,
    )

    proposal_timer_full: Program = DAO_PROPOSAL_TIMER_MOD.curry(
        proposal_curry_one.get_tree_hash(),
        singleton_struct,
    )

    timelock = int_to_bytes(101)
    parent_parent_id = Program.to("parent_parent").get_tree_hash()
    parent_amount = 2000
    solution: Program = Program.to(
        [
            140,  # yes votes
            180,  # total votes
            Program.to(1).get_tree_hash(),  # proposal innerpuz
            timelock,
            parent_parent_id,
            parent_amount,
        ]
    )
    # run the timer puzzle.
    conds = conditions_dict_for_solution(proposal_timer_full, solution, INFINITE_COST)
    assert len(conds) == 4

    # Validate the output conditions
    # Check the timelock is present
    assert conds[ConditionOpcode.ASSERT_HEIGHT_RELATIVE][0].vars[0] == timelock
    # Check the proposal id is announced by the timer puz
    assert conds[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT][0].vars[0] == singleton_id
    # Check the proposal puz announces the timelock
    expected_proposal_puzhash: bytes32 = create_singleton_puzzle_hash(
        proposal_curry_one.curry(
            proposal_curry_one.get_tree_hash(), singleton_id, Program.to(1).get_tree_hash(), 140, 180
        ).get_tree_hash(),
        singleton_id,
    )
    assert conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0] == std_hash(
        expected_proposal_puzhash + timelock
    )
    # Check the parent is a proposal
    expected_parent_puzhash: bytes32 = create_singleton_puzzle_hash(
        proposal_curry_one.curry(
            proposal_curry_one.get_tree_hash(),
            singleton_id,
            Program.to(1).get_tree_hash(),
            0,
            0,
        ).get_tree_hash(),
        singleton_id,
    )
    parent_id = std_hash(parent_parent_id + expected_parent_puzhash + int_to_bytes(parent_amount))
    assert conds[ConditionOpcode.ASSERT_MY_PARENT_ID][0].vars[0] == parent_id


def test_validator() -> None:
    """
    The proposal validator is run by the treasury when a passing proposal is closed.
    Its main purpose is to check that the proposal's vote amounts adehere to
    the DAO rules contained in the treasury (which are passed in from the
    treasury as Truth values). It creates a puzzle announcement of the
    proposal ID, that the proposal itself asserts. It also spends the value
    held in the proposal to the excess payout puzhash.

    The test cases covered are:
    - Executing a spend proposal in which the validator executes the spend of a
      `spend_p2_singleton` coin. This is just a proposal that spends some the treasury
    - Executing an update proposal that changes the DAO rules.
    """
    # Setup the treasury
    treasury_id = Program.to("treasury_id").get_tree_hash()
    treasury_struct: Program = Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_HASH)))

    # Setup the proposal
    proposal_id = Program.to("proposal_id").get_tree_hash()
    proposal_struct: Program = Program.to((SINGLETON_MOD.get_tree_hash(), (proposal_id, SINGLETON_LAUNCHER_HASH)))
    CAT_TAIL_HASH = Program.to("tail").get_tree_hash()
    acs: Program = Program.to(1)
    acs_ph: bytes32 = acs.get_tree_hash()

    p2_singleton = P2_SINGLETON_MOD.curry(treasury_struct, P2_SINGLETON_AGGREGATOR_MOD)
    p2_singleton_puzhash = p2_singleton.get_tree_hash()
    parent_id = Program.to("parent").get_tree_hash()
    locked_amount = 100000
    spend_amount = 1100
    conditions = [[51, 0xDABBAD00, 1000], [51, 0xCAFEF00D, 100]]

    # Setup the validator
    minimum_amt = 1
    excess_puzhash = bytes32(b"1" * 32)
    dao_lockup_self = DAO_LOCKUP_MOD.curry(
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
    )

    proposal_curry_one = DAO_PROPOSAL_MOD.curry(
        DAO_PROPOSAL_TIMER_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        CAT_MOD_HASH,
        DAO_FINISHED_STATE_HASH,
        DAO_TREASURY_MOD_HASH,
        dao_lockup_self.get_tree_hash(),
        CAT_TAIL_HASH,
        treasury_id,
    )
    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        treasury_struct,
        proposal_curry_one.get_tree_hash(),
        minimum_amt,
        excess_puzhash,
    )

    # Can now create the treasury inner puz
    treasury_inner = DAO_TREASURY_MOD.curry(
        DAO_TREASURY_MOD_HASH,
        proposal_validator,
        10,  # proposal len
        5,  # soft close
        1000,  # attendance
        5100,  # pass margin
        20,  # self_destruct len
        3,  # oracle delay
    )

    # Setup the spend_p2_singleton (proposal inner puz)
    spend_p2_singleton = SPEND_P2_SINGLETON_MOD.curry(
        treasury_struct, CAT_MOD_HASH, conditions, [], p2_singleton_puzhash  # tailhash conds
    )
    spend_p2_singleton_puzhash = spend_p2_singleton.get_tree_hash()

    parent_amt_list = [[parent_id, locked_amount]]
    cat_parent_amt_list: List[Optional[Any]] = []
    spend_p2_singleton_solution = Program.to([parent_amt_list, cat_parent_amt_list, treasury_inner.get_tree_hash()])

    output_conds = spend_p2_singleton.run(spend_p2_singleton_solution)

    proposal: Program = proposal_curry_one.curry(
        proposal_curry_one.get_tree_hash(),
        proposal_id,
        spend_p2_singleton_puzhash,
        950,
        1200,
    )
    full_proposal = SINGLETON_MOD.curry(proposal_struct, proposal)
    proposal_amt = 10
    proposal_coin_id = Coin(parent_id, full_proposal.get_tree_hash(), proposal_amt).name()
    solution = Program.to(
        [
            1000,
            5100,
            [proposal_coin_id, spend_p2_singleton_puzhash, 0],
            [proposal_id, 1200, 950, parent_id, proposal_amt],
            output_conds,
        ]
    )

    conds: Program = proposal_validator.run(solution)
    assert len(conds.as_python()) == 7 + len(conditions)

    # test update
    proposal = proposal_curry_one.curry(
        proposal_curry_one.get_tree_hash(),
        proposal_id,
        acs_ph,
        950,
        1200,
    )
    full_proposal = SINGLETON_MOD.curry(proposal_struct, proposal)
    proposal_coin_id = Coin(parent_id, full_proposal.get_tree_hash(), proposal_amt).name()
    solution = Program.to(
        [
            1000,
            5100,
            [proposal_coin_id, acs_ph, 0],
            [proposal_id, 1200, 950, parent_id, proposal_amt],
            [[51, 0xCAFEF00D, spend_amount]],
        ]
    )
    conds = proposal_validator.run(solution)
    assert len(conds.as_python()) == 3

    return


def test_spend_p2_singleton() -> None:
    # Curried values
    singleton_id = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_HASH)))
    p2_singleton_puzhash = P2_SINGLETON_MOD.curry(singleton_struct, P2_SINGLETON_AGGREGATOR_MOD).get_tree_hash()
    cat_tail_1 = Program.to("cat_tail_1").get_tree_hash()
    cat_tail_2 = Program.to("cat_tail_2").get_tree_hash()
    conditions = [[51, 0xCAFEF00D, 100], [51, 0xFEEDBEEF, 200]]
    list_of_tailhash_conds = [
        [cat_tail_1, [[51, 0x8BADF00D, 123], [51, 0xF00DF00D, 321]]],
        [cat_tail_2, [[51, 0x8BADF00D, 123], [51, 0xF00DF00D, 321]]],
    ]

    # Solution Values
    xch_parent_amt_list = [[b"x" * 32, 10], [b"y" * 32, 100]]
    cat_parent_amt_list = [
        [cat_tail_1, [["b" * 32, 100], [b"c" * 32, 400]]],
        [cat_tail_2, [[b"e" * 32, 100], [b"f" * 32, 400]]],
    ]
    # cat_parent_amt_list = []
    treasury_inner_puzhash = Program.to("treasury_inner").get_tree_hash()

    # Puzzle
    spend_p2_puz = SPEND_P2_SINGLETON_MOD.curry(
        singleton_struct, CAT_MOD_HASH, conditions, list_of_tailhash_conds, p2_singleton_puzhash
    )

    # Solution
    spend_p2_sol = Program.to([xch_parent_amt_list, cat_parent_amt_list, treasury_inner_puzhash])

    conds = spend_p2_puz.run(spend_p2_sol)
    assert conds

    # spend only cats
    conditions = []
    list_of_tailhash_conds = [
        [cat_tail_1, [[51, b"q" * 32, 123], [51, b"w" * 32, 321]]],
        [cat_tail_2, [[51, b"e" * 32, 123], [51, b"r" * 32, 321]]],
    ]
    xch_parent_amt_list = []
    cat_parent_amt_list = [
        [cat_tail_1, [[b"b" * 32, 100], [b"c" * 32, 400]]],
        [cat_tail_2, [[b"e" * 32, 100], [b"f" * 32, 400]]],
    ]
    treasury_inner_puzhash = Program.to("treasury_inner").get_tree_hash()

    # Puzzle
    spend_p2_puz = SPEND_P2_SINGLETON_MOD.curry(
        singleton_struct, CAT_MOD_HASH, conditions, list_of_tailhash_conds, p2_singleton_puzhash
    )

    # Solution
    spend_p2_sol = Program.to([xch_parent_amt_list, cat_parent_amt_list, treasury_inner_puzhash])
    conds = spend_p2_puz.run(spend_p2_sol)
    assert conds

    # test deduplicate cat_parent_amount_list
    cat_parent_amt_list = [
        [cat_tail_1, [[b"b" * 32, 100], [b"c" * 32, 400], [b"b" * 32, 100], [b"b" * 32, 100]]],
        [cat_tail_2, [[b"e" * 32, 100], [b"f" * 32, 400], [b"f" * 32, 400], [b"e" * 32, 100]]],
    ]

    spend_p2_sol = Program.to([xch_parent_amt_list, cat_parent_amt_list, treasury_inner_puzhash])
    dupe_conds = spend_p2_puz.run(spend_p2_sol)
    assert dupe_conds == conds


def test_merge_p2_singleton() -> None:
    """
    The treasury funds are held by `p2_singleton_via_delegated` puzzles.
    Because a DAO can have a large number of these coins, it's possible to
    merge them together without requiring a treasury spend.
    There are two cases tested:
    - For the merge coins that do not create the single output coin, and
    - For the coin that does create the output.
    """
    # Setup a singleton struct
    singleton_inner: Program = Program.to(1)
    singleton_id = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_HASH)))

    # Setup p2_singleton_via_delegated puz
    my_id = Program.to("my_id").get_tree_hash()
    p2_singleton = P2_SINGLETON_MOD.curry(singleton_struct, P2_SINGLETON_AGGREGATOR_MOD)
    my_puzhash = p2_singleton.get_tree_hash()

    # Spend to delegated puz
    delegated_puz = Program.to(1)
    delegated_sol = Program.to([[51, 0xCAFEF00D, 300]])
    solution = Program.to([0, singleton_inner.get_tree_hash(), delegated_puz, delegated_sol, my_id])
    conds = conditions_dict_for_solution(p2_singleton, solution, INFINITE_COST)
    apa = std_hash(
        SINGLETON_MOD.curry(singleton_struct, singleton_inner).get_tree_hash()
        + Program.to([my_id, delegated_puz.get_tree_hash()]).get_tree_hash()
    )
    assert len(conds) == 4
    assert conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0] == apa
    assert conds[ConditionOpcode.CREATE_COIN][0].vars[1] == int_to_bytes(300)

    # Merge Spend (not output creator)
    output_parent_id = Program.to("output_parent").get_tree_hash()
    output_coin_amount = 100
    aggregator_sol = Program.to([my_id, my_puzhash, 300, 0, [output_parent_id, output_coin_amount]])
    merge_p2_singleton_sol = Program.to([aggregator_sol, 0, 0, 0, 0])
    conds = conditions_dict_for_solution(p2_singleton, merge_p2_singleton_sol, INFINITE_COST)
    assert len(conds) == 5
    assert conds[ConditionOpcode.ASSERT_MY_PUZZLEHASH][0].vars[0] == my_puzhash
    assert conds[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT][0].vars[0] == int_to_bytes(0)

    # Merge Spend (output creator)
    fake_parent_id = Program.to("fake_parent").get_tree_hash()
    merged_coin_id = Coin(fake_parent_id, my_puzhash, 200).name()
    merge_sol = Program.to([[my_id, my_puzhash, 100, [[fake_parent_id, my_puzhash, 200]], 0]])
    conds = conditions_dict_for_solution(p2_singleton, merge_sol, INFINITE_COST)
    assert len(conds) == 7
    assert conds[ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT][0].vars[0] == std_hash(merged_coin_id)
    assert conds[ConditionOpcode.CREATE_COIN][0].vars[1] == int_to_bytes(300)

    # Test merge and aggregate announcements match up
    parent_ids = [
        Program.to("fake_parent_1").get_tree_hash(),
        Program.to("fake_parent_2").get_tree_hash(),
        Program.to("fake_parent_3").get_tree_hash(),
    ]
    amounts = [1000, 2000, 3000]
    parent_puzhash_amounts = []
    merge_coin_ids: List[bytes32] = []
    for pid, amt in zip(parent_ids, amounts):
        parent_puzhash_amounts.append([pid, my_puzhash, amt])
        merge_coin_ids.append(Coin(pid, my_puzhash, amt).name())

    output_parent_amount = [output_parent_id, output_coin_amount]
    output_coin_id = Coin(output_parent_id, my_puzhash, output_coin_amount).name()

    agg_sol = Program.to([[output_coin_id, my_puzhash, output_coin_amount, parent_puzhash_amounts, 0]])
    agg_conds = conditions_dict_for_solution(p2_singleton, agg_sol, INFINITE_COST)
    # aggregator coin announces merge coin IDs
    agg_ccas = [std_hash(output_coin_id + x.vars[0]) for x in agg_conds[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT]]
    # aggregator coin asserts 0 from merge coins
    agg_acas = [x.vars[0] for x in agg_conds[ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT]]

    for coin_id, ppa in zip(merge_coin_ids, parent_puzhash_amounts):
        sol = Program.to([[coin_id, ppa[1], ppa[2], 0, output_parent_amount]])
        merge_conds = conditions_dict_for_solution(p2_singleton, sol, INFINITE_COST)
        # merge coin announces 0
        cca = std_hash(coin_id + merge_conds[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT][0].vars[0])
        # merge coin asserts my_id from aggregator
        aca = merge_conds[ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT][0].vars[0]
        assert aca in agg_ccas
        assert cca in agg_acas
        assert merge_conds[ConditionOpcode.ASSERT_MY_COIN_ID][0].vars[0] == coin_id

    return


def test_treasury() -> None:
    """
    The treasury has two spend paths:
    - Proposal Path: when a proposal is being closed the treasury spend runs the
      validator and the actual proposed code (if passed)
    - Oracle Path: The treasury can make announcements about itself that are
      used to close invalid proposals
    """
    # Setup the treasury
    treasury_id = Program.to("treasury_id").get_tree_hash()
    treasury_struct: Program = Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_HASH)))
    CAT_TAIL_HASH = Program.to("tail").get_tree_hash()

    proposal_id = Program.to("singleton_id").get_tree_hash()
    proposal_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_HASH)))
    p2_singleton = P2_SINGLETON_MOD.curry(treasury_struct, P2_SINGLETON_AGGREGATOR_MOD)
    p2_singleton_puzhash = p2_singleton.get_tree_hash()
    parent_id = Program.to("parent").get_tree_hash()
    locked_amount = 100000
    oracle_spend_delay = 10
    self_destruct_time = 1000
    proposal_length = 40
    soft_close_length = 5
    attendance = 1000
    pass_margin = 5100
    conditions = [[51, 0xDABBAD00, 1000], [51, 0xCAFEF00D, 100]]

    # Setup the validator
    minimum_amt = 1
    excess_puzhash = bytes32(b"1" * 32)
    dao_lockup_self = DAO_LOCKUP_MOD.curry(
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
    )

    proposal_curry_one = DAO_PROPOSAL_MOD.curry(
        DAO_PROPOSAL_TIMER_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        CAT_MOD_HASH,
        DAO_FINISHED_STATE_HASH,
        DAO_TREASURY_MOD_HASH,
        dao_lockup_self.get_tree_hash(),
        CAT_TAIL_HASH,
        treasury_id,
    )
    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        treasury_struct,
        proposal_curry_one.get_tree_hash(),
        minimum_amt,
        excess_puzhash,
    )

    # Can now create the treasury inner puz
    treasury_inner = DAO_TREASURY_MOD.curry(
        DAO_TREASURY_MOD_HASH,
        proposal_validator,
        proposal_length,
        soft_close_length,
        attendance,
        pass_margin,
        self_destruct_time,
        oracle_spend_delay,
    )

    # Setup the spend_p2_singleton (proposal inner puz)
    spend_p2_singleton = SPEND_P2_SINGLETON_MOD.curry(
        treasury_struct, CAT_MOD_HASH, conditions, [], p2_singleton_puzhash  # tailhash conds
    )
    spend_p2_singleton_puzhash = spend_p2_singleton.get_tree_hash()

    parent_amt_list = [[parent_id, locked_amount]]
    cat_parent_amt_list: List[Optional[Any]] = []
    spend_p2_singleton_solution = Program.to([parent_amt_list, cat_parent_amt_list, treasury_inner.get_tree_hash()])

    proposal: Program = proposal_curry_one.curry(
        proposal_curry_one.get_tree_hash(),
        proposal_id,
        spend_p2_singleton_puzhash,
        950,
        1200,
    )
    full_proposal = SINGLETON_MOD.curry(proposal_struct, proposal)

    # Oracle spend
    solution: Program = Program.to([0, 0, 0, 0, 0, treasury_struct])
    conds: Program = treasury_inner.run(solution)
    assert len(conds.as_python()) == 3

    # Proposal Spend
    proposal_amt = 10
    proposal_coin_id = Coin(parent_id, full_proposal.get_tree_hash(), proposal_amt).name()
    solution = Program.to(
        [
            [proposal_coin_id, spend_p2_singleton_puzhash, 0, "s"],
            [proposal_id, 1200, 950, parent_id, proposal_amt],
            spend_p2_singleton,
            spend_p2_singleton_solution,
        ]
    )
    conds = treasury_inner.run(solution)
    assert len(conds.as_python()) == 10 + len(conditions)


def test_lockup() -> None:
    """
    The lockup puzzle tracks the voting records of DAO CATs. When a proposal is
    voted on, the proposal ID is added to a list, against which, future votes
    are checked.
    This test checks the addition of new votes to the lockup, and that you can't
    re-vote on a proposal twice.
    """
    CAT_TAIL_HASH = Program.to("tail").get_tree_hash()

    INNERPUZ = Program.to(1)
    previous_votes = [0xFADEDDAB]

    dao_lockup_self = DAO_LOCKUP_MOD.curry(
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
    )

    full_lockup_puz: Program = dao_lockup_self.curry(
        dao_lockup_self.get_tree_hash(),
        previous_votes,
        INNERPUZ,
    )
    my_id = Program.to("my_id").get_tree_hash()
    lockup_coin_amount = 20

    # Test adding vote
    new_proposal = 0xBADDADAB
    new_vote_list = [new_proposal, 0xFADEDDAB]
    child_puzhash = dao_lockup_self.curry(
        dao_lockup_self.get_tree_hash(),
        new_vote_list,
        INNERPUZ,
    ).get_tree_hash()
    message = Program.to([new_proposal, lockup_coin_amount, 1, my_id]).get_tree_hash()
    generated_conditions = [[51, child_puzhash, lockup_coin_amount], [62, message]]
    solution: Program = Program.to(
        [
            my_id,
            generated_conditions,
            20,
            new_proposal,
            INNERPUZ.get_tree_hash(),  # fake proposal curry vals
            1,
            20,
            child_puzhash,
            0,
        ]
    )
    conds: Program = full_lockup_puz.run(solution)
    assert len(conds.as_python()) == 6

    # Test Re-voting on same proposal fails
    new_proposal = 0xBADDADAB
    new_vote_list = [new_proposal, 0xBADDADAB]
    child_puzhash = dao_lockup_self.curry(
        dao_lockup_self.get_tree_hash(),
        new_vote_list,
        INNERPUZ,
    ).get_tree_hash()
    message = Program.to([new_proposal, lockup_coin_amount, 1, my_id]).get_tree_hash()
    generated_conditions = [[51, child_puzhash, lockup_coin_amount], [62, message]]
    revote_solution: Program = Program.to(
        [
            my_id,
            generated_conditions,
            20,
            new_proposal,
            INNERPUZ.get_tree_hash(),  # fake proposal curry vals
            1,
            20,
            child_puzhash,
            0,
        ]
    )
    with pytest.raises(ValueError) as e_info:
        conds = full_lockup_puz.run(revote_solution)
    assert e_info.value.args[0] == "clvm raise"

    # Test vote removal
    solution = Program.to(
        [
            0,
            generated_conditions,
            20,
            [0xFADEDDAB],
            INNERPUZ.get_tree_hash(),
            0,
            0,
            0,
            0,
        ]
    )
    conds = full_lockup_puz.run(solution)
    assert len(conds.as_python()) == 3

    new_innerpuz = Program.to("new_inner")
    new_innerpuzhash = new_innerpuz.get_tree_hash()
    child_lockup = dao_lockup_self.curry(
        dao_lockup_self.get_tree_hash(),
        previous_votes,
        new_innerpuz,
    ).get_tree_hash()
    message = Program.to([0, 0, 0, my_id]).get_tree_hash()
    spend_conds = [[51, child_lockup, lockup_coin_amount], [62, message]]
    transfer_sol = Program.to(
        [
            my_id,
            spend_conds,
            lockup_coin_amount,
            0,
            INNERPUZ.get_tree_hash(),  # fake proposal curry vals
            0,
            0,
            INNERPUZ.get_tree_hash(),
            new_innerpuzhash,
        ]
    )
    conds = full_lockup_puz.run(transfer_sol)
    assert conds.at("rrrrfrf").as_atom() == child_lockup


def test_proposal_lifecycle() -> None:
    """
    This test covers the whole lifecycle of a proposal and treasury.
    Its main function is to check that the announcement pairs between treasury
    and proposal are accurate.
    It covers the spend proposal and update proposal types.
    """
    proposal_pass_percentage: uint64 = uint64(5100)
    attendance_required: uint64 = uint64(1000)
    proposal_timelock: uint64 = uint64(40)
    soft_close_length: uint64 = uint64(5)
    self_destruct_time: uint64 = uint64(1000)
    oracle_spend_delay: uint64 = uint64(10)
    min_amt: uint64 = uint64(1)
    CAT_TAIL_HASH = Program.to("tail").get_tree_hash()

    dao_rules = DAORules(
        proposal_timelock=proposal_timelock,
        soft_close_length=soft_close_length,
        attendance_required=attendance_required,
        pass_percentage=proposal_pass_percentage,
        self_destruct_length=self_destruct_time,
        oracle_spend_delay=oracle_spend_delay,
        proposal_minimum_amount=min_amt,
    )

    # Setup the treasury
    treasury_id = Program.to("treasury_id").get_tree_hash()
    treasury_singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_HASH)))
    treasury_amount = 1

    # setup the p2_singleton
    p2_singleton = P2_SINGLETON_MOD.curry(treasury_singleton_struct, P2_SINGLETON_AGGREGATOR_MOD)
    p2_singleton_puzhash = p2_singleton.get_tree_hash()
    parent_id = Program.to("parent").get_tree_hash()
    locked_amount = 100000
    conditions = [[51, 0xDABBAD00, 1000], [51, 0xCAFEF00D, 100]]

    excess_puzhash = get_p2_singleton_puzhash(treasury_id)
    dao_lockup_self = DAO_LOCKUP_MOD.curry(
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
    )

    proposal_curry_one = DAO_PROPOSAL_MOD.curry(
        DAO_PROPOSAL_TIMER_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        CAT_MOD_HASH,
        DAO_FINISHED_STATE_HASH,
        DAO_TREASURY_MOD_HASH,
        dao_lockup_self.get_tree_hash(),
        CAT_TAIL_HASH,
        treasury_id,
    )
    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        treasury_singleton_struct,
        proposal_curry_one.get_tree_hash(),
        min_amt,
        excess_puzhash,
    )

    treasury_inner_puz: Program = DAO_TREASURY_MOD.curry(
        DAO_TREASURY_MOD_HASH,
        proposal_validator,
        proposal_timelock,
        soft_close_length,
        attendance_required,
        proposal_pass_percentage,
        self_destruct_time,
        oracle_spend_delay,
    )
    treasury_inner_puzhash = treasury_inner_puz.get_tree_hash()

    calculated_treasury_puzhash = get_treasury_puzzle(dao_rules, treasury_id, CAT_TAIL_HASH).get_tree_hash()
    assert treasury_inner_puzhash == calculated_treasury_puzhash

    full_treasury_puz = SINGLETON_MOD.curry(treasury_singleton_struct, treasury_inner_puz)
    full_treasury_puzhash = full_treasury_puz.get_tree_hash()

    # Setup the spend_p2_singleton (proposal inner puz)
    spend_p2_singleton = SPEND_P2_SINGLETON_MOD.curry(
        treasury_singleton_struct, CAT_MOD_HASH, conditions, [], p2_singleton_puzhash  # tailhash conds
    )
    spend_p2_singleton_puzhash = spend_p2_singleton.get_tree_hash()

    parent_amt_list = [[parent_id, locked_amount]]
    cat_parent_amt_list: List[Optional[Any]] = []
    spend_p2_singleton_solution = Program.to([parent_amt_list, cat_parent_amt_list, treasury_inner_puzhash])

    # Setup Proposal
    proposal_id = Program.to("proposal_id").get_tree_hash()
    proposal_singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_HASH)))

    current_votes = 1200
    yes_votes = 950
    proposal: Program = proposal_curry_one.curry(
        proposal_curry_one.get_tree_hash(),
        proposal_id,
        spend_p2_singleton_puzhash,
        yes_votes,
        current_votes,
    )
    full_proposal: Program = SINGLETON_MOD.curry(proposal_singleton_struct, proposal)
    full_proposal_puzhash: bytes32 = full_proposal.get_tree_hash()
    proposal_amt = 11
    proposal_coin_id = Coin(parent_id, full_proposal_puzhash, proposal_amt).name()

    treasury_solution: Program = Program.to(
        [
            [proposal_coin_id, spend_p2_singleton_puzhash, 0],
            [proposal_id, current_votes, yes_votes, parent_id, proposal_amt],
            spend_p2_singleton,
            spend_p2_singleton_solution,
        ]
    )

    proposal_solution = Program.to(
        [
            proposal_validator.get_tree_hash(),
            0,
            proposal_timelock,
            proposal_pass_percentage,
            attendance_required,
            0,
            soft_close_length,
            self_destruct_time,
            oracle_spend_delay,
            0,
            proposal_amt,
        ]
    )

    # lineage_proof my_amount inner_solution
    lineage_proof = [treasury_id, treasury_inner_puzhash, treasury_amount]
    full_treasury_solution = Program.to([lineage_proof, treasury_amount, treasury_solution])
    full_proposal_solution = Program.to([lineage_proof, proposal_amt, proposal_solution])

    # Run the puzzles
    treasury_conds = conditions_dict_for_solution(full_treasury_puz, full_treasury_solution, INFINITE_COST)
    proposal_conds = conditions_dict_for_solution(full_proposal, full_proposal_solution, INFINITE_COST)

    # Announcements
    treasury_aca = treasury_conds[ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT][0].vars[0]
    proposal_cca = proposal_conds[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT][0].vars[0]
    assert std_hash(proposal_coin_id + proposal_cca) == treasury_aca

    treasury_cpas = [
        std_hash(full_treasury_puzhash + cond.vars[0])
        for cond in treasury_conds[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT]
    ]
    proposal_apas = [cond.vars[0] for cond in proposal_conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT]]
    assert treasury_cpas[1] == proposal_apas[1]

    # Test Proposal to update treasury
    # Set up new treasury params
    new_proposal_pass_percentage: uint64 = uint64(2500)
    new_attendance_required: uint64 = uint64(500)
    new_proposal_timelock: uint64 = uint64(900)
    new_soft_close_length: uint64 = uint64(10)
    new_self_destruct_time: uint64 = uint64(1000)
    new_oracle_spend_delay: uint64 = uint64(20)
    new_minimum_amount: uint64 = uint64(10)
    proposal_excess_puzhash: bytes32 = get_p2_singleton_puzhash(treasury_id)

    new_dao_rules = DAORules(
        proposal_timelock=new_proposal_timelock,
        soft_close_length=new_soft_close_length,
        attendance_required=new_attendance_required,
        pass_percentage=new_proposal_pass_percentage,
        self_destruct_length=new_self_destruct_time,
        oracle_spend_delay=new_oracle_spend_delay,
        proposal_minimum_amount=new_minimum_amount,
    )

    update_proposal = DAO_UPDATE_MOD.curry(
        DAO_TREASURY_MOD_HASH,
        DAO_PROPOSAL_VALIDATOR_MOD_HASH,
        treasury_singleton_struct,
        proposal_curry_one.get_tree_hash(),
        new_minimum_amount,
        proposal_excess_puzhash,
        new_proposal_timelock,
        new_soft_close_length,
        new_attendance_required,
        new_proposal_pass_percentage,
        new_self_destruct_time,
        new_oracle_spend_delay,
    )
    update_proposal_puzhash = update_proposal.get_tree_hash()
    update_proposal_sol = Program.to([])

    proposal = proposal_curry_one.curry(
        proposal_curry_one.get_tree_hash(),
        proposal_id,
        update_proposal_puzhash,
        yes_votes,
        current_votes,
    )
    full_proposal = SINGLETON_MOD.curry(proposal_singleton_struct, proposal)
    full_proposal_puzhash = full_proposal.get_tree_hash()
    proposal_coin_id = Coin(parent_id, full_proposal_puzhash, proposal_amt).name()

    treasury_solution = Program.to(
        [
            [proposal_coin_id, update_proposal_puzhash, 0, "u"],
            [proposal_id, current_votes, yes_votes, parent_id, proposal_amt],
            update_proposal,
            update_proposal_sol,
        ]
    )

    proposal_solution = Program.to(
        [
            proposal_validator.get_tree_hash(),
            0,
            proposal_timelock,
            proposal_pass_percentage,
            attendance_required,
            0,
            soft_close_length,
            self_destruct_time,
            oracle_spend_delay,
            0,
            proposal_amt,
        ]
    )

    lineage_proof = [treasury_id, treasury_inner_puzhash, treasury_amount]
    full_treasury_solution = Program.to([lineage_proof, treasury_amount, treasury_solution])
    full_proposal_solution = Program.to([lineage_proof, proposal_amt, proposal_solution])

    treasury_conds = conditions_dict_for_solution(full_treasury_puz, full_treasury_solution, INFINITE_COST)
    proposal_conds = conditions_dict_for_solution(full_proposal, full_proposal_solution, INFINITE_COST)

    treasury_aca = treasury_conds[ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT][0].vars[0]
    proposal_cca = proposal_conds[ConditionOpcode.CREATE_COIN_ANNOUNCEMENT][0].vars[0]
    assert std_hash(proposal_coin_id + proposal_cca) == treasury_aca

    treasury_cpas = [
        std_hash(full_treasury_puzhash + cond.vars[0])
        for cond in treasury_conds[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT]
    ]
    proposal_apas = [cond.vars[0] for cond in proposal_conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT]]
    assert treasury_cpas[1] == proposal_apas[1]

    new_treasury_inner = update_proposal.run(update_proposal_sol).at("frf").as_atom()
    expected_treasury_inner = get_treasury_puzzle(new_dao_rules, treasury_id, CAT_TAIL_HASH)
    assert new_treasury_inner == expected_treasury_inner.get_tree_hash()

    expected_treasury_hash = curry_singleton(treasury_id, expected_treasury_inner).get_tree_hash()
    assert treasury_conds[ConditionOpcode.CREATE_COIN][1].vars[0] == expected_treasury_hash


async def do_spend(
    sim: SpendSim,
    sim_client: SimClient,
    coins: List[Coin],
    puzzles: List[Program],
    solutions: List[Program],
) -> Tuple[MempoolInclusionStatus, Optional[Err]]:
    spends = []
    for coin, puzzle, solution in zip(coins, puzzles, solutions):
        spends.append(make_spend(coin, puzzle, solution))
    spend_bundle = SpendBundle(spends, AugSchemeMPL.aggregate([]))
    result = await sim_client.push_tx(spend_bundle)
    await sim.farm_block()
    return result


@pytest.mark.anyio
async def test_singleton_aggregator() -> None:
    async with sim_and_client() as (sim, sim_client):
        aggregator = P2_SINGLETON_AGGREGATOR_MOD
        aggregator_hash = aggregator.get_tree_hash()
        await sim.farm_block(aggregator_hash)
        await sim.farm_block(aggregator_hash)
        for i in range(5):
            await sim.farm_block()

        coin_records = await sim_client.get_coin_records_by_puzzle_hash(aggregator_hash)
        coins = [c.coin for c in coin_records]

        output_coin = coins[0]
        output_sol = Program.to(
            [
                output_coin.name(),
                output_coin.puzzle_hash,
                output_coin.amount,
                [[c.parent_coin_info, c.puzzle_hash, c.amount] for c in coins[1:]],
            ]
        )
        merge_sols = [
            Program.to([c.name(), c.puzzle_hash, c.amount, [], [output_coin.parent_coin_info, output_coin.amount]])
            for c in coins[1:]
        ]

        res = await do_spend(sim, sim_client, coins, [aggregator] * 4, [output_sol, *merge_sols])
        assert res[0] == MempoolInclusionStatus.SUCCESS

        await sim.rewind(uint32(sim.block_height - 1))

        # Spend a merge coin with empty output details
        output_sol = Program.to(
            [
                output_coin.name(),
                output_coin.puzzle_hash,
                output_coin.amount,
                [],
                [],
            ]
        )
        res = await do_spend(sim, sim_client, [output_coin], [aggregator], [output_sol])
        assert res[0] == MempoolInclusionStatus.FAILED

        # Try to steal treasury coins with a phoney output
        acs = Program.to(1)
        acs_ph = acs.get_tree_hash()
        await sim.farm_block(acs_ph)
        bad_coin = (await sim_client.get_coin_records_by_puzzle_hash(acs_ph))[0].coin
        bad_sol = Program.to(
            [
                [ConditionOpcode.CREATE_COIN, acs_ph, sum(c.amount for c in coins)],
                *[[ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, std_hash(c.name())] for c in coins],
                [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, 0],
            ]
        )

        merge_sols = [
            Program.to([c.name(), c.puzzle_hash, c.amount, [], [bad_coin.parent_coin_info, bad_coin.amount]])
            for c in coins
        ]

        res = await do_spend(sim, sim_client, [bad_coin, *coins], [acs] + [aggregator] * 4, [bad_sol, *merge_sols])
        assert res[0] == MempoolInclusionStatus.FAILED
