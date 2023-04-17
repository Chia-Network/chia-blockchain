from __future__ import annotations

import logging
from typing import Iterator, List, Optional, Tuple

from clvm.casts import int_from_bytes

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import match_cat_puzzle
from chia.wallet.dao_wallet.dao_info import DAORules
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.singleton import create_fullpuz, get_innerpuzzle_from_puzzle
from chia.wallet.uncurried_puzzle import UncurriedPuzzle

CAT_MOD_HASH: bytes32 = CAT_MOD.get_tree_hash()
SINGLETON_MOD: Program = load_clvm("singleton_top_layer_v1_1.clvm")
SINGLETON_MOD_HASH: bytes32 = SINGLETON_MOD.get_tree_hash()
SINGLETON_LAUNCHER: Program = load_clvm("singleton_launcher.clvm")
SINGLETON_LAUNCHER_HASH: bytes32 = SINGLETON_LAUNCHER.get_tree_hash()
DAO_LOCKUP_MOD: Program = load_clvm("dao_lockup.clvm")
DAO_LOCKUP_MOD_HASH: bytes32 = DAO_LOCKUP_MOD.get_tree_hash()
DAO_PROPOSAL_TIMER_MOD: Program = load_clvm("dao_proposal_timer.clvm")
DAO_PROPOSAL_TIMER_MOD_HASH: bytes32 = DAO_PROPOSAL_TIMER_MOD.get_tree_hash()
DAO_PROPOSAL_MOD: Program = load_clvm("dao_proposal.clvm")
DAO_PROPOSAL_MOD_HASH: bytes32 = DAO_PROPOSAL_MOD.get_tree_hash()
DAO_PROPOSAL_VALIDATOR_MOD: Program = load_clvm("dao_proposal_validator.clvm")
DAO_PROPOSAL_VALIDATOR_MOD_HASH: bytes32 = DAO_PROPOSAL_VALIDATOR_MOD.get_tree_hash()
DAO_TREASURY_MOD: Program = load_clvm("dao_treasury.clvm")
DAO_TREASURY_MOD_HASH: bytes32 = DAO_TREASURY_MOD.get_tree_hash()
SPEND_P2_SINGLETON_MOD: Program = load_clvm("dao_spend_p2_singleton_v2.clvm")
SPEND_P2_SINGLETON_MOD_HASH: bytes32 = SPEND_P2_SINGLETON_MOD.get_tree_hash()
DAO_FINISHED_STATE: Program = load_clvm("dao_finished_state.clvm")
DAO_FINISHED_STATE_HASH: bytes32 = DAO_FINISHED_STATE.get_tree_hash()
DAO_RESALE_PREVENTION: Program = load_clvm("dao_resale_prevention_layer.clvm")
DAO_RESALE_PREVENTION_HASH: bytes32 = DAO_RESALE_PREVENTION.get_tree_hash()
DAO_CAT_TAIL: Program = load_clvm("genesis_by_coin_id_or_singleton.clvm")
DAO_CAT_TAIL_HASH: bytes32 = DAO_CAT_TAIL.get_tree_hash()
P2_CONDITIONS_MOD: Program = load_clvm("p2_conditions_curryable.clvm")
P2_CONDITIONS_MOD_HASH: bytes32 = P2_CONDITIONS_MOD.get_tree_hash()
DAO_SAFE_PAYMENT_MOD: Program = load_clvm("dao_safe_payment.clvm")
DAO_SAFE_PAYMENT_MOD_HASH: bytes32 = DAO_SAFE_PAYMENT_MOD.get_tree_hash()
P2_SINGLETON_MOD: Program = load_clvm("p2_singleton_via_delegated_puzzle.clsp")
P2_SINGLETON_MOD_HASH: bytes32 = P2_SINGLETON_MOD.get_tree_hash()

log = logging.Logger(__name__)


def create_new_proposal_puzzle(
    proposal_id: bytes32,
    cat_tail_hash: bytes32,
    treasury_id: bytes32,
    proposed_puzzle_hash: bytes32,
) -> Program:
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_HASH)))
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
        "s",
        proposed_puzzle_hash,
    )
    return puzzle


def get_treasury_puzzle(dao_rules: DAORules) -> Program:
    puzzle = DAO_TREASURY_MOD.curry(
        DAO_TREASURY_MOD_HASH,
        DAO_PROPOSAL_VALIDATOR_MOD,
        dao_rules.proposal_timelock,
        dao_rules.soft_close_length,
        dao_rules.attendance_required,
        dao_rules.pass_percentage,
        dao_rules.self_destruct_length,
        dao_rules.oracle_spend_delay,
    )
    return puzzle


def create_announcement_condition_for_nft_spend(
    # treasury_id: bytes32, TODO: is treasury_id needed here?
    nft_id: bytes32,
    target_address: bytes32,
) -> Tuple[Program, Program]:
    # TODO: this delegated puzzle does not actually work with NFTs - need to copy more of the code later
    delegated_puzzle = Program.to([(1, [[51, target_address, 1]])])
    announcement_condition = Program.to([62, Program.to([nft_id, delegated_puzzle.get_tree_hash()]).get_tree_hash()])
    return announcement_condition, delegated_puzzle


def get_spend_p2_singleton_puzzle(
    treasury_id: bytes32, xch_conditions: Optional[List], asset_conditions: Optional[List[Tuple]]  # type: ignore
) -> Program:
    # TODO: typecheck get_spend_p2_singleton_puzzle arguments
    # TODO: add tests for get_spend_p2_singleton_puzzle: pass xch_conditions as Puzzle, List and ConditionWithArgs
    #
    # CAT_MOD_HASH
    # CONDITIONS  - this may also include announcements to spend an NFT
    # LIST_OF_TAILHASH_CONDITIONS
    # P2_SINGLETON_VIA_DELEGATED_PUZZLE_PUZHASH
    treasury_struct = Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_HASH)))
    puzzle: Program = SPEND_P2_SINGLETON_MOD.curry(
        [
            CAT_MOD_HASH,
            xch_conditions,
            asset_conditions,
            P2_SINGLETON_MOD.curry(treasury_struct),
        ]
    )

    return puzzle


def get_p2_singleton_puzhash(treasury_id: bytes32, asset_id: Optional[bytes32] = None) -> bytes32:
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_HASH)))
    inner_puzzle = P2_SINGLETON_MOD.curry(singleton_struct)
    if asset_id:
        # CAT
        puzzle = CAT_MOD.curry(CAT_MOD_HASH, asset_id, inner_puzzle)
        return puzzle.get_tree_hash()
    else:
        # XCH
        return inner_puzzle.get_tree_hash()


def get_lockup_puzzle(
    cat_tail_hash: bytes32, previous_votes_list: List[Optional[bytes32]], innerpuz: Program
) -> Program:
    puzzle: Program = DAO_LOCKUP_MOD.curry(
        DAO_PROPOSAL_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_MOD_HASH,
        cat_tail_hash,
        previous_votes_list,  # TODO: maybe format check this in this function
        innerpuz,
    )
    return puzzle


def get_latest_lockup_puzzle_for_coin_spend(parent_spend: CoinSpend, inner_puzzle: Optional[Program] = None) -> Program:
    puzzle = get_innerpuzzle_from_puzzle(parent_spend.puzzle_reveal)
    assert isinstance(puzzle, Program)
    solution = parent_spend.solution.to_program().rest().rest().first()
    if solution.first() == Program.to(0):
        return puzzle
    new_proposal_id = solution.rest().rest().rest().first().as_atom()
    return add_proposal_to_active_list(puzzle, new_proposal_id, inner_puzzle)


def add_proposal_to_active_list(
    lockup_puzzle: Program, proposal_id: bytes32, inner_puzzle: Optional[Program] = None
) -> Program:
    curried_args = uncurry_lockup(lockup_puzzle).as_iter()
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
    new_active_votes = Program.to(proposal_id).cons(ACTIVE_VOTES)  # (c proposal_id ACTIVE_VOTES)
    if inner_puzzle is None:
        inner_puzzle = INNERPUZ
    return get_lockup_puzzle(CAT_TAIL_HASH, new_active_votes, inner_puzzle)


def get_active_votes_from_lockup_puzzle(lockup_puzzle: Program) -> Program:
    curried_args = uncurry_lockup(lockup_puzzle)
    (
        _PROPOSAL_MOD_HASH,
        _SINGLETON_MOD_HASH,
        _SINGLETON_LAUNCHER_HASH,
        _LOCKUP_MOD_HASH,
        _CAT_MOD_HASH,
        _CAT_TAIL_HASH,
        ACTIVE_VOTES,
        _INNERPUZ,
    ) = list(curried_args.as_iter())
    return Program(ACTIVE_VOTES)


def get_innerpuz_from_lockup_puzzle(lockup_puzzle: Program) -> Program:
    curried_args = uncurry_lockup(lockup_puzzle)
    (
        _PROPOSAL_MOD_HASH,
        _SINGLETON_MOD_HASH,
        _SINGLETON_LAUNCHER_HASH,
        _LOCKUP_MOD_HASH,
        _CAT_MOD_HASH,
        _CAT_TAIL_HASH,
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
    spend_or_update_flag: str,
    proposed_puzzle_hash: bytes32,
) -> Program:
    """
    spend_or_update_flag can take on the following values, ranked from safest to most dangerous:
    s for spend only
    u for update only
    d for dangerous (can do anything)
    """
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_HASH)))
    puzzle = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        cat_tail_hash,
        treasury_id,
        votes_sum,
        total_votes,
        spend_or_update_flag,
        proposed_puzzle_hash,
    )
    return puzzle


def get_proposal_timer_puzzle(
    cat_tail_hash: bytes32,
    proposal_id: bytes32,
    treasury_id: bytes32,
) -> Program:
    parent_singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_HASH)))
    puzzle: Program = DAO_PROPOSAL_TIMER_MOD.curry(
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        cat_tail_hash,
        parent_singleton_struct,
        treasury_id,
    )
    return puzzle


def get_treasury_rules_from_puzzle(puzzle_reveal: Program) -> DAORules:
    curried_args = uncurry_treasury(puzzle_reveal)
    (
        _DAO_TREASURY_MOD_HASH,
        _DAO_PROPOSAL_VALIDATOR_MOD,
        proposal_timelock,
        soft_close_length,
        attendance_required,
        pass_percentage,
        self_destruct_length,
        oracle_spend_delay,
    ) = curried_args
    return DAORules(
        uint64(int_from_bytes(proposal_timelock.as_atom())),
        uint64(int_from_bytes(soft_close_length.as_atom())),
        uint64(int_from_bytes(attendance_required.as_atom())),
        uint64(int_from_bytes(pass_percentage.as_atom())),
        uint64(int_from_bytes(self_destruct_length.as_atom())),
        uint64(int_from_bytes(oracle_spend_delay.as_atom())),
    )


# This takes the treasury puzzle and treasury solution, not the full puzzle and full solution
# This also returns the treasury puzzle and not the full puzzle
def get_new_puzzle_from_treasury_solution(puzzle_reveal: Program, solution: Program) -> Optional[Program]:
    # curried_args = uncurry_treasury(puzzle_reveal)
    # (
    #     DAO_TREASURY_MOD_HASH,
    #     DAO_PROPOSAL_VALIDATOR_MOD,
    #     proposal_timelock,
    #     soft_close_length,
    #     attendance_required_percentage,
    #     proposal_pass_percentage,
    #     proposal_self_destruct_length,
    #     oracle_spend_delay,
    # ) = curried_args
    if solution.first() != Program.to(0):
        # Proposal Spend
        # first check if we are running a spend or update proposal
        # if it's a spend proposal then the treasury puzzle is unchanged
        if solution.at("rrrf").as_atom() == b"s":
            return puzzle_reveal
        elif solution.at("rrrf").as_atom() == b"u":
            # it's an update proposal get the new treasury values from delegated_puzzle_reveal in sol
            # TODO handle update proposals - need an example proposal to work from
            raise ValueError("Update proposal not supported yet")
        else:
            raise ValueError("Invalid spend_or_update_flag in treasury solution")
    else:
        # Oracle Spend - treasury is unchanged
        return puzzle_reveal


# This takes the proposal puzzle and proposal solution, not the full puzzle and full solution
# This also returns the proposal puzzle and not the full puzzle
def get_new_puzzle_from_proposal_solution(puzzle_reveal: Program, solution: Program) -> Optional[Program]:
    # Check if soft_close_length is in solution. If not, then add votes, otherwise close proposal
    if solution.at("rrrrrrf") != Program.to(0):
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
            SPEND_OR_UPDATE_FLAG,
            INNERPUZ_HASH,
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
            SPEND_OR_UPDATE_FLAG,
            INNERPUZ_HASH,
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
    return list(curried_args.as_iter())


def uncurry_proposal(proposal_puzzle: Program) -> Program:
    try:
        mod, curried_args = proposal_puzzle.uncurry()
    except ValueError as e:
        log.debug("Cannot uncurry proposal puzzle: error: %s", e)
        raise e

    if mod != DAO_PROPOSAL_MOD:
        raise ValueError("Not a dao proposal mod.")
    return curried_args


def uncurry_lockup(lockup_puzzle: Program) -> Program:
    try:
        mod, curried_args = lockup_puzzle.uncurry()
    except ValueError as e:
        log.debug("Cannot uncurry lockup puzzle: error: %s", e)
        raise e

    if mod != DAO_LOCKUP_MOD:
        raise ValueError("Not a dao cat lockup mod.")
    return curried_args


def generate_cat_tail(genesis_coin_id: bytes32, treasury_id: bytes32) -> Program:
    puzzle = DAO_CAT_TAIL.curry(
        genesis_coin_id, treasury_id, SINGLETON_MOD_HASH, SINGLETON_LAUNCHER_HASH, DAO_PROPOSAL_MOD_HASH
    )
    return puzzle


# TODO: move curry_singleton to chia.wallet.singleton
# TODO: Is this correct? See create_fullpuz
# TODO: innerpuz type: is innerpuz a full reveal, or a hash?
def curry_singleton(singleton_id: bytes32, innerpuz: Program) -> Program:
    singleton_struct = Program.to((SINGLETON_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_HASH)))
    return SINGLETON_MOD.curry(singleton_struct, innerpuz)


def get_curry_vals_from_proposal_puzzle(proposal_puzzle: Program) -> Tuple[Program, Program, Program, Program]:
    curried_args = uncurry_proposal(proposal_puzzle).as_iter()
    (
        SINGLETON_STRUCT,
        PROPOSAL_MOD_HASH,
        PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        TREASURY_MOD_HASH,
        LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        TREASURY_ID,
        YES_VOTES,
        TOTAL_VOTES,
        SPEND_OR_UPDATE_FLAG,
        PROPOSED_PUZ_HASH,
    ) = curried_args
    return YES_VOTES, TOTAL_VOTES, SPEND_OR_UPDATE_FLAG, PROPOSED_PUZ_HASH


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
                return curried_args.first().as_iter()  # type: ignore[no-any-return]
    except ValueError:
        import traceback

        print(f"exception: {traceback.format_exc()}")

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
            mod, curried_args = curried_args.rest().first().uncurry()
            if mod == DAO_PROPOSAL_MOD:
                return curried_args.as_iter()  # type: ignore[no-any-return]
    except ValueError:
        import traceback

        print(f"exception: {traceback.format_exc()}")
    return None


# This is used in WSM to determine whether we have a dao funding spend
def match_funding_puzzle(uncurried: UncurriedPuzzle, solution: Program) -> Optional[bool]:
    # TODO: handle case where solution is for existing p2_singleton
    try:
        if match_cat_puzzle(uncurried):
            conditions = solution.at("frfr").as_iter()
        else:
            conditions = solution.at("rfr").as_iter()
        for cond in conditions:
            if (cond.list_len() == 4) and (cond.first().as_int() == 51):
                maybe_treasury_id = cond.at("rrrff")
                if cond.at("rf") == get_p2_singleton_puzhash(maybe_treasury_id):
                    return True
    except ValueError:
        import traceback

        print(f"exception: {traceback.format_exc()}")
    return None
