from __future__ import annotations

import logging
from itertools import chain
from typing import Any, Iterator, List, Optional, Tuple, Union

from clvm.EvalError import EvalError

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, CAT_MOD_HASH, construct_cat_puzzle
from chia.wallet.dao_wallet.dao_info import DAORules, ProposalType
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import MOD
from chia.wallet.singleton import get_singleton_struct_for_id
from chia.wallet.uncurried_puzzle import UncurriedPuzzle

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
DAO_CAT_LAUNCHER: Program = load_clvm("dao_cat_launcher.clsp")
P2_SINGLETON_MOD: Program = load_clvm("p2_singleton_via_delegated_puzzle.clsp")
P2_SINGLETON_MOD_HASH: bytes32 = P2_SINGLETON_MOD.get_tree_hash()
DAO_UPDATE_PROPOSAL_MOD: Program = load_clvm("dao_update_proposal.clsp")
DAO_UPDATE_PROPOSAL_MOD_HASH: bytes32 = DAO_UPDATE_PROPOSAL_MOD.get_tree_hash()
DAO_CAT_EVE: Program = load_clvm("dao_cat_eve.clsp")
P2_SINGLETON_AGGREGATOR_MOD: Program = load_clvm("p2_singleton_aggregator.clsp")

log = logging.Logger(__name__)


def create_cat_launcher_for_singleton_id(id: bytes32) -> Program:
    singleton_struct = get_singleton_struct_for_id(id)
    return DAO_CAT_LAUNCHER.curry(singleton_struct)


def curry_cat_eve(next_puzzle_hash: bytes32) -> Program:
    return DAO_CAT_EVE.curry(next_puzzle_hash)


def get_treasury_puzzle(dao_rules: DAORules, treasury_id: bytes32, cat_tail_hash: bytes32) -> Program:
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_HASH)))
    lockup_puzzle: Program = DAO_LOCKUP_MOD.curry(
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        cat_tail_hash,
    )
    proposal_self_hash = DAO_PROPOSAL_MOD.curry(
        DAO_PROPOSAL_TIMER_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        CAT_MOD_HASH,
        DAO_FINISHED_STATE_HASH,
        DAO_TREASURY_MOD_HASH,
        lockup_puzzle.get_tree_hash(),
        cat_tail_hash,
        treasury_id,
    ).get_tree_hash()

    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        singleton_struct,
        proposal_self_hash,
        dao_rules.proposal_minimum_amount,
        get_p2_singleton_puzzle(
            treasury_id
        ).get_tree_hash(),  # TODO: let people set this later - for now a hidden feature
    )
    puzzle = DAO_TREASURY_MOD.curry(
        DAO_TREASURY_MOD_HASH,
        proposal_validator,
        dao_rules.proposal_timelock,
        dao_rules.soft_close_length,
        dao_rules.attendance_required,
        dao_rules.pass_percentage,
        dao_rules.self_destruct_length,
        dao_rules.oracle_spend_delay,
    )
    return puzzle


def get_proposal_validator(treasury_puz: Program, proposal_minimum_amount: uint64) -> Program:
    _, uncurried_args = treasury_puz.uncurry()
    validator: Program = uncurried_args.rest().first()
    validator_args = validator.uncurry()[1]
    (
        singleton_struct,
        proposal_self_hash,
        _,
        p2_puzhash,
    ) = validator_args.as_iter()
    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        singleton_struct,
        proposal_self_hash,
        proposal_minimum_amount,
        p2_puzhash,
    )
    return proposal_validator


def get_update_proposal_puzzle(dao_rules: DAORules, proposal_validator: Program) -> Program:
    validator_args = uncurry_proposal_validator(proposal_validator)
    (
        singleton_struct,
        proposal_self_hash,
        _,
        proposal_excess_puzhash,
    ) = validator_args.as_iter()
    update_proposal = DAO_UPDATE_PROPOSAL_MOD.curry(
        DAO_TREASURY_MOD_HASH,
        DAO_PROPOSAL_VALIDATOR_MOD_HASH,
        singleton_struct,
        proposal_self_hash,
        dao_rules.proposal_minimum_amount,
        proposal_excess_puzhash,
        dao_rules.proposal_timelock,
        dao_rules.soft_close_length,
        dao_rules.attendance_required,
        dao_rules.pass_percentage,
        dao_rules.self_destruct_length,
        dao_rules.oracle_spend_delay,
    )
    return update_proposal


def get_dao_rules_from_update_proposal(puzzle: Program) -> DAORules:
    mod, curried_args = puzzle.uncurry()
    if mod != DAO_UPDATE_PROPOSAL_MOD:  # pragma: no cover
        raise ValueError("Not an update proposal.")
    (
        _,
        _,
        _,
        _,
        proposal_minimum_amount,
        _,
        proposal_timelock,
        soft_close_length,
        attendance_required,
        pass_percentage,
        self_destruct_length,
        oracle_spend_delay,
    ) = curried_args.as_iter()
    dao_rules = DAORules(
        uint64(proposal_timelock.as_int()),
        uint64(soft_close_length.as_int()),
        uint64(attendance_required.as_int()),
        uint64(pass_percentage.as_int()),
        uint64(self_destruct_length.as_int()),
        uint64(oracle_spend_delay.as_int()),
        uint64(proposal_minimum_amount.as_int()),
    )
    return dao_rules


def get_spend_p2_singleton_puzzle(treasury_id: bytes32, xch_conditions: Program, asset_conditions: Program) -> Program:
    # TODO: typecheck get_spend_p2_singleton_puzzle arguments
    # TODO: add tests for get_spend_p2_singleton_puzzle: pass xch_conditions as Puzzle, List and ConditionWithArgs
    #

    # CAT_MOD_HASH
    # CONDITIONS  ; XCH conditions, to be generated by the treasury
    # LIST_OF_TAILHASH_CONDITIONS  ; the delegated puzzlehash must be curried in to the proposal.
    #                        ; Puzzlehash is only run in the last coin for that asset
    #                        ; ((TAIL_HASH CONDITIONS) (TAIL_HASH CONDITIONS)... )
    # P2_SINGLETON_VIA_DELEGATED_PUZZLE_PUZHASH
    treasury_struct = Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_HASH)))
    puzzle: Program = SPEND_P2_SINGLETON_MOD.curry(
        treasury_struct,
        CAT_MOD_HASH,
        xch_conditions,
        asset_conditions,
        P2_SINGLETON_MOD.curry(treasury_struct, P2_SINGLETON_AGGREGATOR_MOD).get_tree_hash(),
    )
    return puzzle


def get_p2_singleton_puzzle(treasury_id: bytes32, asset_id: Optional[bytes32] = None) -> Program:
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_HASH)))
    inner_puzzle = P2_SINGLETON_MOD.curry(singleton_struct, P2_SINGLETON_AGGREGATOR_MOD)
    if asset_id:
        # CAT
        puzzle = CAT_MOD.curry(CAT_MOD_HASH, asset_id, inner_puzzle)
        return Program(puzzle)
    else:
        # XCH
        return inner_puzzle


def get_p2_singleton_puzhash(treasury_id: bytes32, asset_id: Optional[bytes32] = None) -> bytes32:
    puz = get_p2_singleton_puzzle(treasury_id, asset_id)
    assert puz is not None
    return puz.get_tree_hash()


def get_lockup_puzzle(
    cat_tail_hash: Union[bytes32, Program],
    previous_votes_list: Union[List[Optional[bytes32]], Program],
    innerpuz: Optional[Program],
) -> Program:
    self_hash: Program = DAO_LOCKUP_MOD.curry(
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        cat_tail_hash,
    )
    puzzle = self_hash.curry(
        self_hash.get_tree_hash(),
        previous_votes_list,  # TODO: maybe format check this in this function
        innerpuz,
    )
    return puzzle


def add_proposal_to_active_list(
    lockup_puzzle: Program, proposal_id: bytes32, inner_puzzle: Optional[Program] = None
) -> Program:
    curried_args, c_a = uncurry_lockup(lockup_puzzle)
    (
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_PUZHASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
    ) = c_a.as_iter()
    (SELF_HASH, ACTIVE_VOTES, INNERPUZ) = curried_args.as_iter()
    new_active_votes = Program.to(proposal_id).cons(ACTIVE_VOTES)  # (c proposal_id ACTIVE_VOTES)
    if inner_puzzle is None:
        inner_puzzle = INNERPUZ
    return get_lockup_puzzle(CAT_TAIL_HASH, new_active_votes, inner_puzzle)


def get_active_votes_from_lockup_puzzle(lockup_puzzle: Program) -> Program:
    curried_args, c_a = uncurry_lockup(lockup_puzzle)
    (
        _SINGLETON_MOD_HASH,
        _SINGLETON_LAUNCHER_HASH,
        _DAO_FINISHED_STATE_HASH,
        _CAT_MOD_HASH,
        _CAT_TAIL_HASH,
    ) = list(c_a.as_iter())
    (
        self_hash,
        ACTIVE_VOTES,
        _INNERPUZ,
    ) = curried_args.as_iter()
    return Program(ACTIVE_VOTES)


def get_innerpuz_from_lockup_puzzle(lockup_puzzle: Program) -> Optional[Program]:
    try:
        curried_args, c_a = uncurry_lockup(lockup_puzzle)
    except Exception as e:  # pragma: no cover
        log.debug("Could not uncurry inner puzzle from lockup: %s", e)
        return None
    (
        _SINGLETON_MOD_HASH,
        _SINGLETON_LAUNCHER_HASH,
        _DAO_FINISHED_STATE_HASH,
        _CAT_MOD_HASH,
        _CAT_TAIL_HASH,
    ) = list(c_a.as_iter())
    (
        self_hash,
        _ACTIVE_VOTES,
        INNERPUZ,
    ) = list(curried_args.as_iter())
    return Program(INNERPUZ)


def get_proposal_puzzle(
    *,
    proposal_id: bytes32,
    cat_tail_hash: bytes32,
    treasury_id: bytes32,
    votes_sum: uint64,
    total_votes: uint64,
    proposed_puzzle_hash: bytes32,
) -> Program:
    """
    spend_or_update_flag can take on the following values, ranked from safest to most dangerous:
    s for spend only
    u for update only
    d for dangerous (can do anything)
    """
    lockup_puzzle: Program = DAO_LOCKUP_MOD.curry(
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        cat_tail_hash,
    )
    # SINGLETON_STRUCT  ; (SINGLETON_MOD_HASH (SINGLETON_ID . LAUNCHER_PUZZLE_HASH))
    # PROPOSAL_TIMER_MOD_HASH  ; proposal timer needs to know which proposal created it, AND
    # CAT_MOD_HASH
    # DAO_FINISHED_STATE_MOD_HASH
    # TREASURY_MOD_HASH
    # LOCKUP_SELF_HASH
    # CAT_TAIL_HASH
    # TREASURY_ID
    # ; second hash
    # SELF_HASH
    # PROPOSED_PUZ_HASH  ; this is what runs if this proposal is successful - the inner puzzle of this proposal
    # YES_VOTES  ; yes votes are +1, no votes don't tally - we compare yes_votes/total_votes at the end
    # TOTAL_VOTES  ; how many people responded
    curry_one = DAO_PROPOSAL_MOD.curry(
        DAO_PROPOSAL_TIMER_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        CAT_MOD_HASH,
        DAO_FINISHED_STATE_HASH,
        DAO_TREASURY_MOD_HASH,
        lockup_puzzle.get_tree_hash(),
        cat_tail_hash,
        treasury_id,
    )
    puzzle = curry_one.curry(
        curry_one.get_tree_hash(),
        proposal_id,
        proposed_puzzle_hash,
        votes_sum,
        total_votes,
    )
    return puzzle


def get_proposal_timer_puzzle(
    cat_tail_hash: bytes32,
    proposal_id: bytes32,
    treasury_id: bytes32,
) -> Program:
    parent_singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_HASH)))
    lockup_puzzle: Program = DAO_LOCKUP_MOD.curry(
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_FINISHED_STATE_HASH,
        CAT_MOD_HASH,
        cat_tail_hash,
    )
    PROPOSAL_SELF_HASH = DAO_PROPOSAL_MOD.curry(
        DAO_PROPOSAL_TIMER_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        CAT_MOD_HASH,
        DAO_FINISHED_STATE_HASH,
        DAO_TREASURY_MOD_HASH,
        lockup_puzzle.get_tree_hash(),
        cat_tail_hash,
        treasury_id,
    ).get_tree_hash()

    puzzle: Program = DAO_PROPOSAL_TIMER_MOD.curry(
        PROPOSAL_SELF_HASH,
        parent_singleton_struct,
    )
    return puzzle


def get_treasury_rules_from_puzzle(puzzle_reveal: Optional[Program]) -> DAORules:
    assert isinstance(puzzle_reveal, Program)
    curried_args = uncurry_treasury(puzzle_reveal)
    (
        _DAO_TREASURY_MOD_HASH,
        proposal_validator,
        proposal_timelock,
        soft_close_length,
        attendance_required,
        pass_percentage,
        self_destruct_length,
        oracle_spend_delay,
    ) = curried_args
    curried_args_prg = uncurry_proposal_validator(proposal_validator)
    (
        SINGLETON_STRUCT,
        PROPOSAL_SELF_HASH,
        PROPOSAL_MINIMUM_AMOUNT,
        PAYOUT_PUZHASH,
    ) = curried_args_prg.as_iter()
    return DAORules(
        uint64(proposal_timelock.as_int()),
        uint64(soft_close_length.as_int()),
        uint64(attendance_required.as_int()),
        uint64(pass_percentage.as_int()),
        uint64(self_destruct_length.as_int()),
        uint64(oracle_spend_delay.as_int()),
        uint64(PROPOSAL_MINIMUM_AMOUNT.as_int()),
    )


# This takes the treasury puzzle and treasury solution, not the full puzzle and full solution
# This also returns the treasury puzzle and not the full puzzle
def get_new_puzzle_from_treasury_solution(puzzle_reveal: Program, solution: Program) -> Optional[Program]:
    if solution.rest().rest().first() != Program.to(0):
        # Proposal Spend
        mod, curried_args = solution.at("rrf").uncurry()
        if mod == DAO_UPDATE_PROPOSAL_MOD:
            (
                DAO_TREASURY_MOD_HASH,
                DAO_VALIDATOR_MOD_HASH,
                TREASURY_SINGLETON_STRUCT,
                PROPOSAL_SELF_HASH,
                proposal_minimum_amount,
                PROPOSAL_EXCESS_PAYOUT_PUZ_HASH,
                proposal_timelock,
                soft_close_length,
                attendance_required,
                pass_percentage,
                self_destruct_length,
                oracle_spend_delay,
            ) = curried_args.as_iter()
            new_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
                TREASURY_SINGLETON_STRUCT, PROPOSAL_SELF_HASH, proposal_minimum_amount, PROPOSAL_EXCESS_PAYOUT_PUZ_HASH
            )
            return DAO_TREASURY_MOD.curry(
                DAO_TREASURY_MOD_HASH,
                new_validator,
                proposal_timelock,
                soft_close_length,
                attendance_required,
                pass_percentage,
                self_destruct_length,
                oracle_spend_delay,
            )
        else:
            return puzzle_reveal
    else:
        # Oracle Spend - treasury is unchanged
        return puzzle_reveal


# This takes the proposal puzzle and proposal solution, not the full puzzle and full solution
# This also returns the proposal puzzle and not the full puzzle
def get_new_puzzle_from_proposal_solution(puzzle_reveal: Program, solution: Program) -> Optional[Program]:
    # Check if soft_close_length is in solution. If not, then add votes, otherwise close proposal
    if len(solution.as_python()) == 1:
        return puzzle_reveal  # we're finished, shortcut this function

    if solution.at("rrrrrrf") == Program.to(0):
        c_a, curried_args = uncurry_proposal(puzzle_reveal)
        assert isinstance(curried_args, Program)
        (
            DAO_PROPOSAL_TIMER_MOD_HASH,
            SINGLETON_MOD_HASH,
            SINGLETON_LAUNCHER_PUZHASH,
            CAT_MOD_HASH,
            DAO_FINISHED_STATE_HASH,
            DAO_TREASURY_MOD_HASH,
            lockup_self_hash,
            cat_tail_hash,
            treasury_id,
        ) = curried_args.as_iter()
        assert isinstance(c_a, Program)
        (
            curry_one,
            proposal_id,
            proposed_puzzle_hash,
            yes_votes,
            total_votes,
        ) = c_a.as_iter()

        added_votes = 0
        for vote_amount in solution.first().as_iter():
            added_votes += vote_amount.as_int()

        new_total_votes = total_votes.as_int() + added_votes

        if solution.at("rf") == Program.to(0):
            # Vote Type: NO
            new_yes_votes = yes_votes.as_int()
        else:
            # Vote Type: YES
            new_yes_votes = yes_votes.as_int() + added_votes
        return get_proposal_puzzle(
            proposal_id=bytes32(proposal_id.as_atom()),
            cat_tail_hash=bytes32(cat_tail_hash.as_atom()),
            treasury_id=bytes32(treasury_id.as_atom()),
            votes_sum=uint64(new_yes_votes),
            total_votes=uint64(new_total_votes),
            proposed_puzzle_hash=bytes32(proposed_puzzle_hash.as_atom()),
        )
    else:
        # we are in the finished state, puzzle is the same as ever
        mod, currieds = puzzle_reveal.uncurry()  # uncurry to self_hash
        # check if our parent was the last non-finished state
        if mod.uncurry()[0] == DAO_PROPOSAL_MOD:
            c_a, curried_args = uncurry_proposal(puzzle_reveal)
            (
                DAO_PROPOSAL_TIMER_MOD_HASH,
                SINGLETON_MOD_HASH,
                SINGLETON_LAUNCHER_PUZHASH,
                CAT_MOD_HASH,
                DAO_FINISHED_STATE_HASH,
                DAO_TREASURY_MOD_HASH,
                lockup_self_hash,
                cat_tail_hash,
                treasury_id,
            ) = curried_args.as_iter()
            (
                curry_one,
                proposal_id,
                proposed_puzzle_hash,
                yes_votes,
                total_votes,
            ) = c_a.as_iter()
        else:  # pragma: no cover
            SINGLETON_STRUCT, dao_finished_hash = currieds.as_iter()
            proposal_id = SINGLETON_STRUCT.rest().first()
        return get_finished_state_inner_puzzle(bytes32(proposal_id.as_atom()))


def get_finished_state_inner_puzzle(proposal_id: bytes32) -> Program:
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_HASH)))
    finished_inner_puz: Program = DAO_FINISHED_STATE.curry(singleton_struct, DAO_FINISHED_STATE_HASH)
    return finished_inner_puz


def get_finished_state_puzzle(proposal_id: bytes32) -> Program:
    return curry_singleton(proposal_id, get_finished_state_inner_puzzle(proposal_id))


def get_proposed_puzzle_reveal_from_solution(solution: Program) -> Program:
    prog = Program.from_bytes(bytes(solution))
    return prog.at("rrfrrrrrf")


def get_asset_id_from_puzzle(puzzle: Program) -> Optional[bytes32]:
    mod, curried_args = puzzle.uncurry()
    if mod == MOD:  # pragma: no cover
        return None
    elif mod == CAT_MOD:
        return bytes32(curried_args.at("rf").as_atom())
    elif mod == SINGLETON_MOD:  # pragma: no cover
        return bytes32(curried_args.at("frf").as_atom())
    else:
        raise ValueError("DAO received coin with unknown puzzle")  # pragma: no cover


def uncurry_proposal_validator(proposal_validator_program: Program) -> Program:
    try:
        mod, curried_args = proposal_validator_program.uncurry()
    except ValueError as e:  # pragma: no cover
        log.debug("Cannot uncurry treasury puzzle: error: %s", e)
        raise e

    if mod != DAO_PROPOSAL_VALIDATOR_MOD:  # pragma: no cover
        raise ValueError("Not a Treasury mod.")
    return curried_args


def uncurry_treasury(treasury_puzzle: Program) -> List[Program]:
    try:
        mod, curried_args = treasury_puzzle.uncurry()
    except ValueError as e:  # pragma: no cover
        log.debug("Cannot uncurry treasury puzzle: error: %s", e)
        raise e

    if mod != DAO_TREASURY_MOD:  # pragma: no cover
        raise ValueError("Not a Treasury mod.")
    return list(curried_args.as_iter())


def uncurry_proposal(proposal_puzzle: Program) -> Tuple[Program, Program]:
    try:
        mod, curried_args = proposal_puzzle.uncurry()
    except ValueError as e:  # pragma: no cover
        log.debug("Cannot uncurry proposal puzzle: error: %s", e)
        raise e
    try:
        mod, c_a = mod.uncurry()
    except ValueError as e:  # pragma: no cover
        log.debug("Cannot uncurry lockup puzzle: error: %s", e)
        raise e
    if mod != DAO_PROPOSAL_MOD:
        raise ValueError("Not a dao proposal mod.")
    return curried_args, c_a


def uncurry_lockup(lockup_puzzle: Program) -> Tuple[Program, Program]:
    try:
        mod, curried_args = lockup_puzzle.uncurry()
    except ValueError as e:  # pragma: no cover
        log.debug("Cannot uncurry lockup puzzle: error: %s", e)
        raise e
    try:
        mod, c_a = mod.uncurry()
    except ValueError as e:  # pragma: no cover
        log.debug("Cannot uncurry lockup puzzle: error: %s", e)
        raise e
    if mod != DAO_LOCKUP_MOD:
        log.debug("Puzzle is not a dao cat lockup mod")
    return curried_args, c_a


# This is the proposed puzzle
def get_proposal_args(puzzle: Program) -> Tuple[ProposalType, Program]:
    try:
        mod, curried_args = puzzle.uncurry()
    except ValueError as e:  # pragma: no cover
        log.debug("Cannot uncurry spend puzzle: error: %s", e)
        raise e
    if mod == SPEND_P2_SINGLETON_MOD:
        return ProposalType.SPEND, curried_args
    elif mod == DAO_UPDATE_PROPOSAL_MOD:
        return ProposalType.UPDATE, curried_args
    else:
        raise ValueError("Unrecognised proposal type")


def generate_cat_tail(genesis_coin_id: bytes32, treasury_id: bytes32) -> Program:
    dao_cat_launcher = create_cat_launcher_for_singleton_id(treasury_id).get_tree_hash()
    puzzle = DAO_CAT_TAIL.curry(genesis_coin_id, dao_cat_launcher)
    return puzzle


def curry_singleton(singleton_id: bytes32, innerpuz: Program) -> Program:
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_HASH)))
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
    except ValueError:  # pragma: no cover
        # We just pass here to prevent spamming logs with error messages when WSM checks incoming coins
        pass
    return None


# This is for use in the WalletStateManager to determine the type of coin received
def match_proposal_puzzle(mod: Program, curried_args: Program) -> Optional[Iterator[Program]]:
    """
    Given a puzzle test if it's a Proposal, if it is, return the curried arguments
    :param curried_args: Puzzle
    :return: Curried parameters
    """
    try:
        if mod == SINGLETON_MOD:
            c_a, curried_args = uncurry_proposal(curried_args.rest().first())
            assert c_a is not None and curried_args is not None
            ret = chain(c_a.as_iter(), curried_args.as_iter())
            return ret
    except ValueError:
        # We just pass here to prevent spamming logs with error messages when WSM checks incoming coins
        pass
    return None


def match_finished_puzzle(mod: Program, curried_args: Program) -> Optional[Iterator[Program]]:
    """
    Given a puzzle test if it's a Proposal, if it is, return the curried arguments
    :param curried_args: Puzzle
    :return: Curried parameters
    """
    try:
        if mod == SINGLETON_MOD:
            mod, curried_args = curried_args.rest().first().uncurry()
            if mod == DAO_FINISHED_STATE:
                return curried_args.as_iter()
    except ValueError:  # pragma: no cover
        # We just pass here to prevent spamming logs with error messages when WSM checks incoming coins
        pass
    return None


# This is used in WSM to determine whether we have a dao funding spend
def match_funding_puzzle(
    uncurried: UncurriedPuzzle, solution: Program, coin: Coin, dao_ids: List[bytes32] = []
) -> Optional[bool]:
    if not dao_ids:
        return None
    try:
        if uncurried.mod == CAT_MOD:
            conditions = solution.at("frfr").as_iter()
        elif uncurried.mod == MOD:
            conditions = solution.at("rfr").as_iter()
        elif uncurried.mod == SINGLETON_MOD:
            inner_puz, _ = uncurried.args.at("rf").uncurry()
            if inner_puz == DAO_TREASURY_MOD:
                delegated_puz = solution.at("rrfrrf")
                delegated_mod, delegated_args = delegated_puz.uncurry()
                if delegated_puz.uncurry()[0] == SPEND_P2_SINGLETON_MOD:
                    if coin.puzzle_hash == delegated_args.at("rrrrf").as_atom():  # pragma: no cover
                        return True
            return None  # pragma: no cover
        else:
            return None
        fund_puzhashes = [get_p2_singleton_puzhash(dao_id) for dao_id in dao_ids]
        for cond in conditions:
            if (cond.list_len() == 4) and (cond.first().as_int() == 51):
                if cond.at("rrrff") in fund_puzhashes:
                    return True
    except (ValueError, EvalError):
        # We just pass here to prevent spamming logs with error messages when WSM checks incoming coins
        pass
    return None


def match_dao_cat_puzzle(uncurried: UncurriedPuzzle) -> Optional[Iterator[Program]]:
    try:
        if uncurried.mod == CAT_MOD:
            arg_list = list(uncurried.args.as_iter())
            inner_puz = get_innerpuz_from_lockup_puzzle(uncurried.args.at("rrf"))
            if inner_puz is not None:
                dao_cat_args: Iterator[Program] = Program.to(arg_list).as_iter()
                return dao_cat_args
    except ValueError:
        # We just pass here to prevent spamming logs with error messages when WSM checks incoming coins
        pass
    return None


def generate_simple_proposal_innerpuz(
    treasury_id: bytes32,
    recipient_puzhashes: List[bytes32],
    amounts: List[uint64],
    asset_types: List[Optional[bytes32]] = [None],
) -> Program:
    if len(recipient_puzhashes) != len(amounts) != len(asset_types):  # pragma: no cover
        raise ValueError("Mismatch in the number of recipients, amounts, or asset types")
    xch_conds: List[Any] = []
    cat_conds: List[Any] = []
    seen_assets = set()
    for recipient_puzhash, amount, asset_type in zip(recipient_puzhashes, amounts, asset_types):
        if asset_type:
            if asset_type in seen_assets:
                asset_conds = [x for x in cat_conds if x[0] == asset_type][0]
                asset_conds[1].append([51, recipient_puzhash, amount, [recipient_puzhash]])
            else:
                cat_conds.append([asset_type, [[51, recipient_puzhash, amount, [recipient_puzhash]]]])
                seen_assets.add(asset_type)
        else:
            xch_conds.append([51, recipient_puzhash, amount])
    puzzle = get_spend_p2_singleton_puzzle(treasury_id, Program.to(xch_conds), Program.to(cat_conds))
    return puzzle


async def generate_update_proposal_innerpuz(
    current_treasury_innerpuz: Program,
    new_dao_rules: DAORules,
    new_proposal_validator: Optional[Program] = None,
) -> Program:
    if not new_proposal_validator:
        assert isinstance(current_treasury_innerpuz, Program)
        new_proposal_validator = get_proposal_validator(
            current_treasury_innerpuz, new_dao_rules.proposal_minimum_amount
        )
    return get_update_proposal_puzzle(new_dao_rules, new_proposal_validator)


async def generate_mint_proposal_innerpuz(
    treasury_id: bytes32,
    cat_tail_hash: bytes32,
    amount_of_cats_to_create: uint64,
    cats_new_innerpuzhash: bytes32,
) -> Program:
    if amount_of_cats_to_create % 2 == 1:  # pragma: no cover
        raise ValueError("Minting proposals must mint an even number of CATs")
    cat_launcher = create_cat_launcher_for_singleton_id(treasury_id)

    # cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
    # cat_tail_hash = cat_wallet.cat_info.limitations_program_hash
    eve_puz_hash = curry_cat_eve(cats_new_innerpuzhash)
    full_puz = construct_cat_puzzle(CAT_MOD, cat_tail_hash, eve_puz_hash)
    xch_conditions = [
        [
            51,
            cat_launcher.get_tree_hash(),
            uint64(amount_of_cats_to_create),
            [cats_new_innerpuzhash],
        ],  # create cat_launcher coin
        [
            60,
            Program.to([ProposalType.MINT.value, full_puz.get_tree_hash()]).get_tree_hash(),
        ],  # make an announcement for the launcher to assert
    ]
    puzzle = get_spend_p2_singleton_puzzle(treasury_id, Program.to(xch_conditions), Program.to([]))
    return puzzle
