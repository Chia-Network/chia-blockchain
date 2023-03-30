from __future__ import annotations

import logging
from typing import Iterator, List, Optional

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.singleton import create_fullpuz

SINGLETON_MOD: Program = load_clvm("singleton_top_layer_v1_1.clvm")
SINGLETON_LAUNCHER: Program = load_clvm("singleton_launcher.clvm")
DAO_LOCKUP_MOD: Program = load_clvm("dao_lockup.clvm")
DAO_PROPOSAL_TIMER_MOD: Program = load_clvm("dao_proposal_timer.clvm")
DAO_PROPOSAL_MOD: Program = load_clvm("dao_proposal.clvm")
DAO_TREASURY_MOD: Program = load_clvm("dao_treasury.clvm")
P2_SINGLETON_MOD: Program = load_clvm("p2_singleton_or_delayed_puzhash.clvm")
DAO_FINISHED_STATE: Program = load_clvm("dao_finished_state.clvm")
DAO_RESALE_PREVENTION: Program = load_clvm("dao_resale_prevention_layer.clvm")
DAO_CAT_TAIL: Program = load_clvm("genesis_by_coin_id_or_proposal.clvm")

DAO_TREASURY_MOD_HASH = DAO_TREASURY_MOD.get_tree_hash()
DAO_PROPOSAL_MOD_HASH = DAO_PROPOSAL_MOD.get_tree_hash()
DAO_PROPOSAL_TIMER_MOD_HASH = DAO_PROPOSAL_TIMER_MOD.get_tree_hash()
DAO_LOCKUP_MOD_HASH = DAO_LOCKUP_MOD.get_tree_hash()
CAT_MOD_HASH = CAT_MOD.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()
SINGLETON_LAUNCHER_PUZHASH = SINGLETON_LAUNCHER.get_tree_hash()


log = logging.Logger(__name__)


def create_new_proposal_puzzle(
    proposal_id: bytes32,
    cat_tail_hash: bytes32,
    treasury_id: bytes32,
    proposed_puzzle_hash: bytes32,
) -> Program:
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_PUZHASH)))
    puzzle: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        cat_tail_hash,
        treasury_id,
        0,
        0,
        proposed_puzzle_hash,
    )
    return puzzle


def get_treasury_puzzle(
    treasury_id: bytes32,
    cat_tail_hash: bytes32,
    current_cat_issuance: uint64,
    attendance_required_percentage: uint64,
    proposal_pass_percentage: uint64,
    proposal_timelock: uint64,
) -> Program:
    # (
    # SINGLETON_STRUCT  ; ((SINGLETON_MOD_HASH, (SINGLETON_ID, LAUNCHER_PUZZLE_HASH)))
    # TREASURY_MOD_HASH
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # LOCKUP_MOD_HASH
    # CAT_MOD_HASH
    # CAT_TAIL_HASH
    # CURRENT_CAT_ISSUANCE
    # ATTENDANCE_REQUIRED_PERCENTAGE  ; percent of total potential votes needed to have a chance at passing
    # PASS_MARGIN  ; what percentage of votes should be yes (vs no) for a proposal to pass.
    #              ; PASS_MARGIN is represented as 0 - 10000 (default 5100)
    # PROPOSAL_TIMELOCK ; relative timelock -- how long proposals should live during this treasury's lifetime
    # )
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_PUZHASH)))
    puzzle = DAO_TREASURY_MOD.curry(
        Program.to(
            [
                singleton_struct,
                DAO_TREASURY_MOD_HASH,
                DAO_PROPOSAL_MOD_HASH,
                DAO_PROPOSAL_TIMER_MOD_HASH,
                DAO_LOCKUP_MOD_HASH,
                CAT_MOD_HASH,
                cat_tail_hash,
                current_cat_issuance,
                attendance_required_percentage,
                proposal_pass_percentage,
                proposal_timelock,
            ]
        )
    )
    return puzzle


def get_lockup_puzzle(cat_tail_hash: bytes32, previous_votes_list: List[bytes32], innerpuz: Program) -> Program:
    # PROPOSAL_MOD_HASH
    # SINGLETON_MOD_HASH
    # SINGLETON_LAUNCHER_PUZHASH
    # LOCKUP_MOD_HASH
    # CAT_MOD_HASH
    # CAT_TAIL_HASH
    # PREVIOUS_VOTES  ; "active votes" list
    # LOCKUP_TIME
    # INNERPUZ
    puzzle: Program = DAO_LOCKUP_MOD.curry(
        DAO_PROPOSAL_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_PUZHASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_MOD_HASH,
        cat_tail_hash,
        previous_votes_list,  # TODO: maybe format check this in this function
        innerpuz,
    )
    return puzzle


def add_proposal_to_active_list(lockup_puzzle: Program, proposal_id: bytes32) -> Program:
    curried_args = uncurry_lockup(lockup_puzzle)
    (
        PROPOSAL_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_PUZHASH,
        LOCKUP_MOD_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
        ACTIVE_VOTES,
        INNERPUZ,
    ) = curried_args
    new_active_votes = ACTIVE_VOTES.cons(proposal_id)
    return get_lockup_puzzle(CAT_TAIL_HASH, new_active_votes, INNERPUZ)


def get_active_votes_from_lockup_puzzle(lockup_puzzle: Program) -> Program:
    curried_args = uncurry_lockup(lockup_puzzle)
    (
        PROPOSAL_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_PUZHASH,
        LOCKUP_MOD_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
        ACTIVE_VOTES,
        INNERPUZ,
    ) = curried_args
    return Program(ACTIVE_VOTES)


def get_innerpuz_from_lockup_puzzle(lockup_puzzle: Program) -> Program:
    curried_args = uncurry_lockup(lockup_puzzle)
    (
        PROPOSAL_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_PUZHASH,
        LOCKUP_MOD_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
        ACTIVE_VOTES,
        INNERPUZ,
    ) = curried_args
    return INNERPUZ


def get_proposal_puzzle(
    proposal_id: bytes32,
    cat_tail: bytes32,
    treasury_id: bytes32,
    votes_sum: int,
    total_votes: uint64,
    innerpuz: Program,
) -> Program:
    # SINGLETON_STRUCT  ; (SINGLETON_MOD_HASH, (SINGLETON_ID, LAUNCHER_PUZZLE_HASH))
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH ; proposal timer needs to know which proposal created it, AND
    # CAT_MOD_HASH
    # TREASURY_MOD_HASH
    # LOCKUP_MOD_HASH
    # CAT_TAIL_HASH
    # TREASURY_ID
    # YES_VOTES  ; yes votes are +1, no votes don't tally - we compare yes_votes/total_votes at the end
    # TOTAL_VOTES  ; how many people responded
    # INNERPUZ  ; this is what runs if this proposal is successful - the inner puzzle of this proposal. Rename as PROPOSAL_PUZZLE ?
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_PUZHASH)))
    puzzle = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        cat_tail,
        treasury_id,
        votes_sum,
        total_votes,
        innerpuz,
    )
    return puzzle


def get_proposal_timer_puzzle(
    cat_tail_hash: bytes32,
    proposal_id: bytes32,
    treasury_id: bytes32,
) -> Program:
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # CAT_MOD_HASH
    # CAT_TAIL_HASH
    # MY_PARENT_SINGLETON_STRUCT  ; ((SINGLETON_MOD_HASH, (PROPOSAL_SINGLETON_ID, LAUNCHER_PUZZLE_HASH)))
    # TREASURY_ID
    parent_singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_PUZHASH)))
    puzzle: Program = DAO_PROPOSAL_TIMER_MOD.curry(
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        cat_tail_hash,
        parent_singleton_struct,
        treasury_id,
    )
    return puzzle


# This takes the treasury puzzle and treasury solution, not the full puzzle and full solution
# This also returns the treasury puzzle and not the full puzzle
def get_new_puzzle_from_treasury_solution(puzzle_reveal: Program, solution: Program) -> Optional[Program | bytes32]:
    # my_amount         ; current amount
    # new_amount_change ; may be negative or positive. Is zero during eve spend
    # my_puzhash_or_proposal_id ; either the current treasury singleton puzzlehash OR proposal ID
    # announcement_messages_list_or_payment_nonce  ; this is a list of messages which the treasury will parrot -
    #                                              ; assert from the proposal and also create
    # new_puzhash  ; if this variable is 0 then we do the "add_money" spend case and all variables below are not needed
    # proposal_innerpuz
    # proposal_current_votes ; tally of yes votes
    # proposal_total_votes   ; total votes cast (by number of cat-mojos)
    # type  ; this is used for the recreating self type
    # extra_value  ; this is used for recreating self

    type = solution.rest().rest().rest().rest().rest().rest().rest().rest().first()
    if type == Program.to("n"):  # New puzzle hash
        return bytes32(solution.rest().rest().rest().rest().first().as_atom())
    elif type == Program.to("u"):  # Unchanged
        return puzzle_reveal
    elif type == Program.to("r"):  # Recurry by index
        curried_args = uncurry_treasury(puzzle_reveal)
        (
            singleton_struct,
            DAO_TREASURY_MOD_HASH,
            DAO_PROPOSAL_MOD_HASH,
            DAO_PROPOSAL_TIMER_MOD_HASH,
            DAO_LOCKUP_MOD_HASH,
            CAT_MOD_HASH,
            cat_tail_hash,
            current_cat_issuance,
            attendance_required_percentage,
            proposal_pass_percentage,
            proposal_timelock,
        ) = curried_args
        args_list = [
            singleton_struct,
            DAO_TREASURY_MOD_HASH,
            DAO_PROPOSAL_MOD_HASH,
            DAO_PROPOSAL_TIMER_MOD_HASH,
            DAO_LOCKUP_MOD_HASH,
            CAT_MOD_HASH,
            cat_tail_hash,
            current_cat_issuance,
            attendance_required_percentage,
            proposal_pass_percentage,
            proposal_timelock,
        ]
        replace_list = solution.rest().rest().rest().rest().first()
        while replace_list != Program.to(0):
            pair = replace_list.fist()
            args_list[pair.first().as_atom()] = pair.rest().first().as_atom()
            replace_list = replace_list.rest()
        puzzle = DAO_TREASURY_MOD.curry(Program.to(args_list))
        return puzzle

    return None


# This takes the proposal puzzle and proposal solution, not the full puzzle and full solution
# This also returns the proposal puzzle and not the full puzzle
def get_new_puzzle_from_proposal_solution(puzzle_reveal: Program, solution: Program) -> Optional[Program | bytes32]:
    # vote_amount_or_solution  ; The qty of "votes" to add or subtract. ALWAYS POSITIVE.
    # vote_info_or_p2_singleton_mod_hash ; vote_info is whether we are voting YES or NO. XXX rename vote_type?
    # vote_coin_id_or_current_cat_issuance  ; this is either the coin ID we're taking a vote from OR...
    #                                     ; the total number of CATs in circulation according to the treasury
    # previous_votes_or_pass_margin  ; this is the active votes of the lockup we're communicating with
    #                              ; OR this is what percentage of the total votes must be YES - represented as an integer from 0 to 10,000 - typically this is set at 5100 (51%)
    # lockup_innerpuzhash_or_attendance_required  ; this is either the innerpuz of the locked up CAT we're taking a vote from OR
    #                                           ; the attendance required - the percentage of the current issuance which must have voted represented as 0 to 10,000 - this is announced by the treasury
    # proposal_timelock  ; we assert this from the treasury and announce it, so the timer knows what the the current timelock is
    #                  ; we only use this when closing out so set it to 0 and we will do the vote spend case
    if solution.rest().rest().rest().rest().rest().first() == Program.to(0):
        print()
        (
            SINGLETON_STRUCT,  # (SINGLETON_MOD_HASH, (SINGLETON_ID, LAUNCHER_PUZZLE_HASH))
            PROPOSAL_MOD_HASH,
            PROPOSAL_TIMER_MOD_HASH,
            CAT_MOD_HASH,
            TREASURY_MOD_HASH,
            LOCKUP_MOD_HASH,
            CAT_TAIL_HASH,
            TREASURY_ID,
            YES_VOTES,  # yes votes are +1, no votes don't tally - we compare yes_votes/total_votes at the end
            TOTAL_VOTES,  # how many people responded
            INNERPUZ,
        ) = uncurry_proposal(puzzle_reveal)
        added_votes = solution.first().as_atom()
        new_total_votes = TOTAL_VOTES.as_atom() + added_votes
        if solution.rest().first() == Program.to(0):
            new_yes_votes = YES_VOTES
        else:
            new_yes_votes = YES_VOTES.as_atom() + added_votes
        return DAO_PROPOSAL_MOD.curry(
            SINGLETON_STRUCT,
            DAO_PROPOSAL_MOD_HASH,
            DAO_PROPOSAL_TIMER_MOD_HASH,
            CAT_MOD_HASH,
            DAO_TREASURY_MOD_HASH,
            DAO_LOCKUP_MOD_HASH,
            CAT_TAIL_HASH,
            TREASURY_ID,
            new_yes_votes,
            new_total_votes,
            INNERPUZ,
        )
    else:
        return DAO_FINISHED_STATE


def get_finished_state_puzzle(proposal_id: bytes32) -> Program:
    return create_fullpuz(DAO_FINISHED_STATE, proposal_id)


def get_cat_tail_hash_from_treasury_puzzle(treasury_puzzle: Program) -> bytes32:
    curried_args = uncurry_treasury(treasury_puzzle)
    (
        singleton_struct,
        DAO_TREASURY_MOD_HASH,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_MOD_HASH,
        cat_tail_hash,
        current_cat_issuance,
        attendance_required_percentage,
        proposal_pass_percentage,
        proposal_timelock,
    ) = curried_args
    return bytes32(cat_tail_hash.as_atom())


def uncurry_treasury(treasury_puzzle: Program) -> List[Program]:
    try:
        mod, curried_args = treasury_puzzle.uncurry()
    except ValueError as e:
        log.debug("Cannot uncurry treasury puzzle: error: %s", e)
        raise e

    if mod != DAO_TREASURY_MOD:
        raise ValueError("Not a Treasury mod.")
    return curried_args.first().as_iter()


def uncurry_proposal(proposal_puzzle: Program) -> Program:
    try:
        mod, curried_args = proposal_puzzle.uncurry()
    except ValueError as e:
        log.debug("Cannot uncurry proposal puzzle: error: %s", e)
        raise e

    if mod != DAO_PROPOSAL_MOD:
        raise ValueError("Not a dao proposal mod.")
    # SINGLETON_STRUCT  ; (SINGLETON_MOD_HASH, (SINGLETON_ID, LAUNCHER_PUZZLE_HASH))
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH ; proposal timer needs to know which proposal created it, AND
    # CAT_MOD_HASH
    # TREASURY_MOD_HASH
    # LOCKUP_MOD_HASH
    # CAT_TAIL_HASH
    # TREASURY_ID
    # YES_VOTES  ; yes votes are +1, no votes don't tally - we compare yes_votes/total_votes at the end
    # TOTAL_VOTES  ; how many people responded
    # INNERPUZ
    return curried_args


def uncurry_lockup(lockup_puzzle: Program) -> Program:
    try:
        mod, curried_args = lockup_puzzle.uncurry()
    except ValueError as e:
        log.debug("Cannot uncurry lockup puzzle: error: %s", e)
        raise e

    if mod != DAO_LOCKUP_MOD:
        raise ValueError("Not a dao cat lockup mod.")
    # PROPOSAL_MOD_HASH
    # SINGLETON_MOD_HASH
    # SINGLETON_LAUNCHER_PUZHASH
    # LOCKUP_MOD_HASH
    # CAT_MOD_HASH
    # CAT_TAIL_HASH
    # ACTIVE_VOTES  ; "active votes" list
    # INNERPUZ
    return curried_args


def generate_cat_tail(genesis_coin_id: bytes32, treasury_id: bytes32) -> Program:
    # GENESIS_ID
    # DAO_TREASURY_ID
    # SINGLETON_MOD_HASH
    # SINGLETON_LAUNCHER_PUZHASH
    # DAO_PROPOSAL_MOD_HASH
    puzzle = DAO_CAT_TAIL.curry(
        genesis_coin_id, treasury_id, SINGLETON_MOD_HASH, SINGLETON_LAUNCHER_PUZHASH, DAO_PROPOSAL_MOD_HASH
    )
    return puzzle


def curry_singleton(singleton_id: bytes32, innerpuz: bytes32) -> Program:
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_PUZHASH)))
    return SINGLETON_MOD.curry(singleton_struct, innerpuz)


# This is for use in the WalletStateManager to determine the type of coin received
def match_treasury_puzzle(mod: Program, curried_args: Program) -> Optional[Iterator[Program]]:
    """
        Given a puzzle test if it's a Treasury, if it is, return the curried arguments
    :param mod: Puzzle
    :param curried_args: Puzzle
    :return: Curried parameters
    """
    try:
        if mod == SINGLETON_MOD:
            mod, curried_args = curried_args.rest().first().uncurry()
            if mod == DAO_TREASURY_MOD:
                return curried_args.first().as_iter()
    except Exception:
        import traceback

        print(f"exception: {traceback.format_exc()}")
    return None


# This is for use in the WalletStateManager to determine the type of coin received
def match_proposal_puzzle(mod: Program, curried_args: Program) -> Optional[Program]:
    """
        Given a puzzle test if it's a Proposal, if it is, return the curried arguments
    :param puzzle: Puzzle
    :param curried_args: Puzzle
    :return: Curried parameters
    """
    try:
        if mod == SINGLETON_MOD:
            mod, curried_args = curried_args.rest().first().uncurry()
            if mod == DAO_PROPOSAL_MOD:
                return curried_args.as_iter()
    except Exception:
        import traceback

        print(f"exception: {traceback.format_exc()}")
    return None
