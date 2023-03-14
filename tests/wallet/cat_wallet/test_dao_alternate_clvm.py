from __future__ import annotations
import pytest
from typing import List

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm

from clvm.casts import int_from_bytes

SINGLETON_MOD: Program = load_clvm("singleton_top_layer_v1_1.clvm")
SINGLETON_LAUNCHER: Program = load_clvm("singleton_launcher.clvm")
DAO_LOCKUP_MOD: Program = load_clvm("dao_lockup.clvm")
DAO_PROPOSAL_TIMER_MOD: Program = load_clvm("dao_alternate_proposal_timer.clvm")
DAO_PROPOSAL_MOD: Program = load_clvm("dao_alternate_proposal.clvm")
DAO_PROPOSAL_VALIDATOR_MOD: Program = load_clvm("dao_alternate_proposal_validator.clvm")
DAO_MONEY_RECEIVER_MOD: Program = load_clvm("dao_alternate_money_receiver.clvm")
DAO_TREASURY_MOD: Program = load_clvm("dao_alternate_treasury.clvm")
# P2_SINGLETON_MOD: Program = load_clvm("p2_singleton_or_delayed_puzhash.clvm")
SPEND_P2_SINGLETON_MOD: Program = load_clvm("dao_spend_p2_singleton.clvm")
DAO_FINISHED_STATE: Program = load_clvm("dao_finished_state.clvm")
DAO_RESALE_PREVENTION: Program = load_clvm("dao_resale_prevention_layer.clvm")
DAO_CAT_TAIL: Program = load_clvm("genesis_by_coin_id_or_treasury.clvm")
P2_CONDITIONS_MOD: Program = load_clvm("p2_conditions_curryable.clvm")
DAO_SAFE_PAYMENT_MOD: Program = load_clvm("dao_safe_payment.clvm")
P2_SINGLETON_MOD: Program = load_clvm("p2_singleton_via_delegated_puzzle.clsp")


def test_proposal() -> None:
    # SINGLETON_STRUCT  ; (SINGLETON_MOD_HASH (SINGLETON_ID . LAUNCHER_PUZZLE_HASH))
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH ; proposal timer needs to know which proposal created it, AND
    # CAT_MOD_HASH
    # TREASURY_MOD_HASH
    # LOCKUP_MOD_HASH
    # CAT_TAIL_HASH
    # TREASURY_ID
    # YES_VOTES  ; yes votes are +1, no votes don't tally - we compare yes_votes/total_votes at the end
    # TOTAL_VOTES  ; how many people responded
    # SPEND_OR_UPDATE_FLAG  ; this is either 's' or 'u' - other types can be added in the future
    # PROPOSED_PUZ_HASH  ; this is what runs if this proposal is successful - the inner puzzle of this proposal

    proposal_pass_percentage: uint64 = uint64(5100)
    CAT_TAIL_HASH: Program = Program.to("tail").get_tree_hash()
    treasury_id: Program = Program.to("treasury").get_tree_hash()
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    self_destruct_time = 1209600

    full_proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        treasury_id,
        20,
        100,
        's',
        Program.to(1).get_tree_hash(),
    )

    # Test Voting
    solution: Program = Program.to(
        [
            [10], # vote amounts
            1,  # vote type (yes)
            [Program.to("vote_coin").get_tree_hash()], # vote coin ids
            [[0xFADEDDAB]], # previous votes (should be a number?)
            [0xCAFEF00D],  # lockup inner puz hash
            0, # inner puz reveal
            0, # soft close len
            self_destruct_time,
            0,
        ]
    )
    conds: Program = full_proposal.run(solution)
    # assert len(conds.as_python()) == 3

    # Test exit
    # vote_amounts_or_proposal_validator_hash  ; The qty of "votes" to add or subtract. ALWAYS POSITIVE.
    # vote_info_or_money_receiver_hash ; vote_info is whether we are voting YES or NO. XXX rename vote_type?
    # vote_coin_id_or_proposal_timelock_length  ; this is either the coin ID we're taking a vote from
    # previous_votes_or_pass_margin  ; this is the active votes of the lockup we're communicating with
    #                              ; OR this is what percentage of the total votes must be YES - represented as an integer from 0 to 10,000 - typically this is set at 5100 (51%)
    # lockup_innerpuzhash_or_attendance_required  ; this is either the innerpuz of the locked up CAT we're taking a vote from OR
    #                                           ; the attendance required - the percentage of the current issuance which must have voted represented as 0 to 10,000 - this is announced by the treasury
    # innerpuz_reveal  ; this is only added during the first vote
    # soft_close_length  ; revealed by the treasury

    # Test attempt to close a passing proposal
    full_proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        treasury_id,
        200, # yes votes
        350, # total votes
        's',
        Program.to(1).get_tree_hash(),
    )
    attendance_required = 200

    solution = Program.to(
        [
            Program.to("validator_hash").get_tree_hash(),
            Program.to("receiver_hash").get_tree_hash(), # not needed anymore?
            20, # timelock length
            proposal_pass_percentage,
            attendance_required,
            Program.to(1),
            5,
            self_destruct_time,
            0,
        ]
    )

    conds = full_proposal.run(solution)
    assert len(conds.as_python()) == 6

    # close a failed proposal
    full_proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        treasury_id,
        20, # yes votes
        350, # total votes
        's',
        Program.to(1).get_tree_hash(),
    )
    attendance_required = 200
    solution = Program.to(
        [
            Program.to("validator_hash").get_tree_hash(),
            Program.to("receiver_hash").get_tree_hash(), # not needed anymore?
            20, # timelock length
            proposal_pass_percentage,
            attendance_required,
            Program.to(1),
            5,
            self_destruct_time,
            0,
        ]
    )
    conds = full_proposal.run(solution)
    assert len(conds.as_python()) == 3

    # self destruct a proposal
    attendance_required = 200
    solution = Program.to(
        [
            Program.to("validator_hash").get_tree_hash(),
            Program.to("receiver_hash").get_tree_hash(), # not needed anymore?
            20, # timelock length
            proposal_pass_percentage,
            attendance_required,
            Program.to(1),
            5,
            self_destruct_time,
            1,
        ]
    )
    conds = full_proposal.run(solution)
    assert len(conds.as_python()) == 3

def test_proposal_timer() -> None:
    CAT_TAIL: Program = Program.to("tail").get_tree_hash()
    treasury_id: Program = Program.to("treasury").get_tree_hash()
    # LOCKUP_TIME: uint64 = uint64(200)
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # CAT_MOD_HASH
    # CAT_TAIL_HASH
    # (@ MY_PARENT_SINGLETON_STRUCT (SINGLETON_MOD_HASH SINGLETON_ID . LAUNCHER_PUZZLE_HASH))
    # TREASURY_ID
    proposal_timer_full: Program = DAO_PROPOSAL_TIMER_MOD.curry(
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        singleton_struct,
        treasury_id,
    )

    # proposal_yes_votes
    # proposal_total_votes
    # proposal_innerpuzhash
    # proposal_parent_id
    # proposal_amount
    # proposal_timelock
    # parent_parent

    solution: Program = Program.to(
        [
            140,
            180,
            Program.to(1).get_tree_hash(),
            Program.to("parent").get_tree_hash(),
            23,
            200,
            Program.to("parent_parent").get_tree_hash(),
        ]
    )
    conds: Program = proposal_timer_full.run(solution)
    assert len(conds.as_python()) == 4


def test_validator() -> None:
    # SINGLETON_STRUCT  ; (SINGLETON_MOD_HASH (SINGLETON_ID . LAUNCHER_PUZZLE_HASH))
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # CAT_MOD_HASH
    # LOCKUP_MOD_HASH
    # TREASURY_MOD_HASH
    # CAT_TAIL_HASH
    # ATTENDANCE_REQUIRED
    # PASS_MARGIN
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    CAT_TAIL_HASH: Program = Program.to("tail").get_tree_hash()

    treasury_puzzle_hash = Program.to("treasury").get_tree_hash()
    treasury_amount = 401
    delegated_puzzle = Program.to(1)
    delegated_conditions = [[51, 0xcafef00d, 40], [51, 0xdabbad00, 60]]
    spend_amount = 100
    safe_puzzle = DAO_SAFE_PAYMENT_MOD.curry(singleton_struct, delegated_conditions, spend_amount)
    safe_puzzle_hash = safe_puzzle.get_tree_hash()
    output_conds = safe_puzzle.run(Program.to([treasury_puzzle_hash, treasury_amount]))

    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        DAO_SAFE_PAYMENT_MOD.get_tree_hash(),
    )
    # (announcement_source delegated_puzzle_hash announcement_args)
    # (
    #   proposal_id
    #   total_votes
    #   yes_votes
    #   spend_amount
    # )
    # spend_or_update_flag
    # conditions
    proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        singleton_id,
        950,
        1200,
        's',
        safe_puzzle_hash,
    )
    full_proposal = SINGLETON_MOD.curry(singleton_struct, proposal)
    solution = Program.to([
        1000,
        5100,
        [full_proposal.get_tree_hash(), safe_puzzle_hash, 0, 's'],
        [singleton_id, 1200, 950, spend_amount],
        output_conds
    ])
    conds: Program = proposal_validator.run(solution)
    assert len(conds.as_python()) == 3 + len(delegated_conditions)

    # test update
    proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        singleton_id,
        950,
        1200,
        'u',
        Program.to(1).get_tree_hash(),
    )
    full_proposal = SINGLETON_MOD.curry(singleton_struct, proposal)
    solution = Program.to([
        [full_proposal.get_tree_hash(), Program.to(1).get_tree_hash(), 0, 'u'],
        [singleton_id, 1200, 950, spend_amount],
        [[51, 0xcafe00d, 40]]
    ])
    conds: Program = proposal_validator.run(solution)
    cds = conds.as_python()
    assert len(conds.as_python()) == 2

    return


def test_receiver() -> None:
    # MINIMUM_INPUT_AMOUNT  ; this is a minimum of -1 to prevent money being removed, but can be increased to prevent DoS/spam
    # MY_SINGLETON_STRUCT
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()

    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    money_receiver = DAO_MONEY_RECEIVER_MOD.curry(-1, singleton_struct, 1)
    # my_amount
    # my_treasury_puzzle_hash
    # amount_change
    # input_coins
    solution = Program.to([201, 0xCAFEF00D, 20, [Program.to("coin_id").get_tree_hash()]])
    conds: Program = money_receiver.run(solution)
    assert len(conds.as_python()) == 6
    return


def test_spend_p2_singleton() -> None:
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )

    # Test that p2_singleton_via_delegated_puzzle will run
    p2_singleton = P2_SINGLETON_MOD.curry(singleton_struct)
    p2_singleton_puzhash = p2_singleton.get_tree_hash()
    parent_id = Program.to("parent").get_tree_hash()
    locked_amount = 100000
    singleton_inner_hash = Program.to(1).get_tree_hash()
    deleg_puz = Program.to(1)
    deleg_conds = Program.to([[51,0xcafef00d, 1000]])
    conds = p2_singleton.run(Program.to([singleton_inner_hash, deleg_puz, deleg_conds]))
    assert len(conds.as_python()) == 3

    spend_amount = 1100
    conditions = [[51, 0xDABBAD00, 1000], [51, 0xCAFEF00D, 100]]

    spend_p2_singleton = SPEND_P2_SINGLETON_MOD.curry(conditions, spend_amount, p2_singleton_puzhash)
    spend_p2_singleton_puzhash = spend_p2_singleton.get_tree_hash()
    solution = Program.to([[[parent_id, locked_amount]]])

    output_conditions = spend_p2_singleton.run(solution)
    assert len(output_conditions.as_python()) == 5

    # now use the p2_singleton with the proposal validator
    total_votes = 1200
    yes_votes = 950
    attendance_required = 1000
    pass_margin = 5100
    CAT_TAIL_HASH: Program = Program.to("tail").get_tree_hash()
    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        SPEND_P2_SINGLETON_MOD.get_tree_hash(),
        p2_singleton_puzhash,
    )
    proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        singleton_id,
        yes_votes,
        total_votes,
        's',
        spend_p2_singleton_puzhash,
    )
    full_proposal = SINGLETON_MOD.curry(singleton_struct, proposal)
    validator_solution = Program.to([
        attendance_required,
        pass_margin,
        [full_proposal.get_tree_hash(), spend_p2_singleton_puzhash, 0, 's'],
        [singleton_id, total_votes, yes_votes, spend_amount],
        output_conditions
    ])
    conds = proposal_validator.run(validator_solution).as_python()
    assert output_conditions == conds


def test_treasury() -> None:
    CAT_TAIL_HASH: Program = Program.to("tail").get_tree_hash()
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    p2_singleton = P2_SINGLETON_MOD.curry(singleton_struct)
    p2_singleton_puzhash = p2_singleton.get_tree_hash()
    parent_id = Program.to("parent").get_tree_hash()
    locked_amount = 100000
    spend_amount = 1100
    conditions = [[51, 0xDABBAD00, 1000], [51, 0xCAFEF00D, 100]]

    spend_p2_singleton = SPEND_P2_SINGLETON_MOD.curry(conditions, spend_amount, p2_singleton_puzhash)
    spend_p2_singleton_puzhash = spend_p2_singleton.get_tree_hash()
    spend_p2_singleton_solution = Program.to([[[parent_id, locked_amount]]])

    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        SPEND_P2_SINGLETON_MOD.get_tree_hash(),
        p2_singleton_puzhash,
    )

    # PROPOSAL_VALIDATOR
    # PROPOSAL_LENGTH
    # PROPOSAL_SOFTCLOSE_LENGTH
    # ATTENDANCE_REQUIRED
    # PASS_MARGIN
    # PROPOSAL_SELF_DESTRUCT_TIME
    self_destruct_time = 1209600 # 2 weeks
    full_treasury_puz: Program = DAO_TREASURY_MOD.curry(
        proposal_validator,
        40,
        5,
        1000,
        5100,
        self_destruct_time
    )

    treasury_puzzle_hash = full_treasury_puz.get_tree_hash()

    # (@ proposal_announcement (announcement_source delegated_puzzle_hash announcement_args spend_or_update_flag))
    # proposal_validator_solution
    # delegated_puzzle_reveal  ; this is the reveal of the puzzle announced by the proposal
    # delegated_solution  ; this is not secure unless the delegated puzzle secures it
    proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        singleton_id,
        950,
        1200,
        's',
        spend_p2_singleton_puzhash,
    )
    full_proposal = SINGLETON_MOD.curry(singleton_struct, proposal)

    # Oracle spend
    solution: Program = Program.to(
        [
           "o"
        ]
    )
    conds: Program = full_treasury_puz.run(solution)
    assert len(conds.as_python()) == 2
    # (@ proposal_announcement (announcement_source delegated_puzzle_hash announcement_args spend_or_update_flag))
    # proposal_validator_solution
    # delegated_puzzle_reveal  ; this is the reveal of the puzzle announced by the proposal
    # delegated_solution  ; this is not secure unless the delegated puzzle secures it
    solution: Program = Program.to(
        [
            "p",
            [full_proposal.get_tree_hash(), spend_p2_singleton_puzhash, 0, 's'],
            [singleton_id, 1200, 950, spend_amount],
            spend_p2_singleton,
            spend_p2_singleton_solution
        ]
    )
    conds = full_treasury_puz.run(solution)
    assert len(conds.as_python()) == 6 + len(conditions)


def test_lockup() -> None:
    # PROPOSAL_MOD_HASH
    # SINGLETON_MOD_HASH
    # SINGLETON_LAUNCHER_PUZHASH
    # LOCKUP_MOD_HASH
    # CAT_MOD_HASH
    # CAT_TAIL
    # PREVIOUS_VOTES
    # LOCKUP_TIME
    # PUBKEY
    CAT_TAIL: Program = Program.to("tail").get_tree_hash()

    INNERPUZ = Program.to(1)
    previous_votes = [0xFADEDDAB]

    full_lockup_puz: Program = DAO_LOCKUP_MOD.curry(
        DAO_PROPOSAL_MOD.get_tree_hash(),
        SINGLETON_MOD.get_tree_hash(),
        SINGLETON_LAUNCHER.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        previous_votes,
        INNERPUZ,
    )

    # my_id  ; if my_id is 0 we do the return to return_address (exit voting mode) spend case
    # innersolution
    # my_amount
    # new_proposal_vote_id_or_return_address
    # vote_info
    # proposal_curry_vals
    my_id = Program.to("my_id").get_tree_hash()
    lockup_coin_amount = 20
    new_proposal = 0xBADDADAB
    previous_votes = [new_proposal, 0xFADEDDAB]
    child_puzhash = DAO_LOCKUP_MOD.curry(
        DAO_PROPOSAL_MOD.get_tree_hash(),
        SINGLETON_MOD.get_tree_hash(),
        SINGLETON_LAUNCHER.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        previous_votes,
        INNERPUZ,
    ).get_tree_hash()
    message = Program.to([new_proposal, lockup_coin_amount, 1, my_id]).get_tree_hash()
    generated_conditions = [[51, child_puzhash, lockup_coin_amount], [62, message]]
    # my_id  ; if my_id is 0 we do the return to return_address (exit voting mode) spend case
    # inner_solution
    # my_amount
    # new_proposal_vote_id_or_return_address
    # vote_info
    # proposal_curry_vals
    solution: Program = Program.to(
        [
            my_id,
            generated_conditions,
            20,
            new_proposal,
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 0],
            1,
            20,
            child_puzhash,
            0,
        ]
    )
    conds: Program = full_lockup_puz.run(solution)
    assert len(conds.as_python()) == 6

    solution = Program.to(
        [
            0,
            generated_conditions,
            20,
            0xFADEDDAB,
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 0],
        ]
    )
    conds = full_lockup_puz.run(solution)
    assert len(conds.as_python()) == 3


def test_proposal_innerpuz() -> None:
    proposal_pass_percentage: uint64 = uint64(5100)
    attendance_required: uint64 = uint64(1000)
    CAT_TAIL_HASH: Program = Program.to("tail").get_tree_hash()
    LOCKUP_TIME: uint64 = uint64(200)

    # Setup the treasury
    treasury_singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    treasury_singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (treasury_singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )

    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        treasury_singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        DAO_SAFE_PAYMENT_MOD.get_tree_hash(),
        attendance_required,
        proposal_pass_percentage,
    )
    money_receiver = DAO_MONEY_RECEIVER_MOD.curry(-1, treasury_singleton_struct, 1)
    # PROPOSAL_VALIDATOR
    # MONEY_RECEIVER
    # PROPOSAL_LENGTH
    # PROPOSAL_SOFTCLOSE_LENGTH
    treasury_puz: Program = DAO_TREASURY_MOD.curry(
        proposal_validator,
        money_receiver,
        40,
        5,
    )

    full_treasury_puz = SINGLETON_MOD.curry(treasury_singleton_struct, treasury_puz)

    treasury_puzzle_hash = treasury_puz.get_tree_hash()
    treasury_amount = 401
    delegated_puzzle = Program.to(1)
    delegated_conditions = [[51, 0xcafef00d, 100], [51, 0xdabbad00, 100]]
    spend_amount = 200
    safe_puzzle = DAO_SAFE_PAYMENT_MOD.curry(treasury_singleton_struct, delegated_conditions, spend_amount)
    safe_puzzle_hash = safe_puzzle.get_tree_hash()
    safe_puzzle_solution = Program.to([treasury_puzzle_hash, treasury_amount])

    # Setup Proposal
    proposal_singleton_id: Program = Program.to("p_singleton_id").get_tree_hash()
    proposal_singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (proposal_singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )

    # P2_PH = Program.to("p2_ph").get_tree_hash()
    # P2_CONDS = [[51, P2_PH, 200]]

    # proposed_innerpuz = P2_CONDITIONS_MOD.curry(P2_CONDS)

    proposal: Program = DAO_PROPOSAL_MOD.curry(
        proposal_singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        treasury_singleton_id,
        950,
        1200,
        's',
        safe_puzzle_hash,
    )
    full_proposal = SINGLETON_MOD.curry(proposal_singleton_struct, proposal)

    full_prop_ph: bytes32 = full_proposal.get_tree_hash()

    # (@ proposal_announcement (announcement_source delegated_puzzle_hash announcement_args spend_or_update_flag))
    # proposal_validator_solution
    # delegated_puzzle_reveal  ; this is the reveal of the puzzle announced by the proposal
    # delegated_solution  ; this is not secure unless the delegated puzzle secures it
    treasury_solution: Program = Program.to(
        [
            [full_proposal.get_tree_hash(), safe_puzzle_hash, 0, 's'],
            [proposal_singleton_id, 1200, 950, spend_amount],
            safe_puzzle,
            safe_puzzle_solution,
        ]
    )

    # vote_amounts_or_proposal_validator_hash  ; The qty of "votes" to add or subtract. ALWAYS POSITIVE.
    # vote_info_or_money_receiver_hash ; vote_info is whether we are voting YES or NO. XXX rename vote_type?
    # vote_coin_id_or_proposal_timelock_length  ; this is either the coin ID we're taking a vote from
    # previous_votes_or_pass_margin  ; this is the active votes of the lockup we're communicating with
    #                              ; OR this is what percentage of the total votes must be YES - represented as an integer from 0 to 10,000 - typically this is set at 5100 (51%)
    # lockup_innerpuzhash_or_attendance_required  ; this is either the innerpuz of the locked up CAT we're taking a vote from OR
    #                                           ; the attendance required - the percentage of the current issuance which must have voted represented as 0 to 10,000 - this is announced by the treasury
    # innerpuz_reveal  ; this is only added during the first vote
    # soft_close_length  ; revealed by the treasury

    proposal_solution = Program.to(
        [
            proposal_validator.get_tree_hash(),
            money_receiver.get_tree_hash(),
            40,
            proposal_pass_percentage,
            1000,
            0,
            5,
        ]
    )
    # lineage_proof my_amount inner_solution
    lineage_proof = [treasury_singleton_id, treasury_puz.get_tree_hash(), treasury_amount]
    full_treasury_solution = Program.to([lineage_proof, treasury_amount+spend_amount, treasury_solution])
    full_proposal_solution = Program.to([lineage_proof, 1, proposal_solution])

    # Run the puzzles
    treasury_conds: Program = full_treasury_puz.run(full_treasury_solution)
    proposal_conds: Program = full_proposal.run(full_proposal_solution)
    # breakpoint()
    # Check the A_P_As from treasury match the C_P_As from the proposal
    cpa = b">"
    apa = b"?"
    cpas = []
    for cond in proposal_conds.as_python():
        if cond[0] == cpa:
            cpas.append(std_hash(full_prop_ph + cond[1]))
    for cond in treasury_conds.as_python():
        if cond[0] == apa:
            assert bytes32(cond[1]) in cpas

    amps = []
    ccs = []
    for cond in treasury_conds.as_python():
        if cond[0] == b"3":
            if cond[2] == treasury_amount - spend_amount:
                assert cond[1] == full_treasury_puz.get_tree_hash()
            ccs.append(cond)
        if cond[0] == b"H":
            amps.append(cond[1])
    assert len(ccs) == 1 + len(delegated_conditions)
    assert len(amps) == 1
    assert amps[0] == full_treasury_puz.get_tree_hash()
