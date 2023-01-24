from __future__ import annotations

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm

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
DAO_SPEND_PROPOSAL: Program = load_clvm("dao_spend_proposal.clvm")


def test_proposal() -> None:
    # SINGLETON_STRUCT
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # CAT_MOD_HASH
    # TREASURY_MOD_HASH
    # LOCKUP_MOD_HASH  ; this is the mod already curried with what it needs - should still be a constant
    # CAT_TAIL_HASH
    # CURRENT_CAT_ISSUANCE
    # PROPOSAL_PASS_PERCENTAGE
    # TREASURY_ID
    # PROPOSAL_TIMELOCK
    # VOTES_SUM  ; yes votes are +1, no votes are -1
    # TOTAL_VOTES  ; how many people responded
    # INNERPUZ  ; this is what runs if this proposal is successful

    current_cat_issuance: uint64 = uint64(1000)
    proposal_pass_percentage: uint64 = uint64(5100)
    CAT_TAIL_HASH: Program = Program.to("tail").get_tree_hash()
    treasury_id: Program = Program.to("treasury").get_tree_hash()
    LOCKUP_TIME: uint64 = uint64(200)
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
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
        Program.to(1),
    )
    # vote_amount_or_solution  ; The qty of "votes" to add or subtract. ALWAYS POSITIVE.
    # vote_info_or_p2_singleton_mod_hash ; vote_info is whether we are voting YES or NO. XXX rename vote_type?
    # vote_coin_id_or_current_cat_issuance  ; this is either the coin ID we're taking a vote from OR...
    #                                       ; the total number of CATs in circulation according to the treasury
    # previous_votes_or_pass_margin  ; this is the active votes of the lockup we're communicating with
    #                                ; OR this is what percentage of the total votes must be YES - represented as an integer from 0 to 10,000 - typically this is set at 5100 (51%)
    # lockup_innerpuzhash_or_attendance_required  ; this is either the innerpuz of the locked up CAT we're taking a vote from OR
    #                                             ; the attendance required - the percentage of the current issuance which must have voted represented as 0 to 10,000 - this is announced by the treasury
    # proposal_timelock  ; we assert this from the treasury and announce it, so the timer knows what the the current timelock is
    #                    ; set this to 0 and we will do the vote spend case

    # Test Voting
    solution: Program = Program.to(
        [
            [10],
            1,
            [Program.to("vote_coin").get_tree_hash()],
            [[0xFADEDDAB]],
            [0xCAFEF00D],
            0,
        ]
    )
    conds: Program = full_proposal.run(solution)
    assert len(conds.as_python()) == 3
    # Test exit
    solution = Program.to(
        [
            [[51, 0xCAFEF00D, 200]],
            P2_SINGLETON_MOD.get_tree_hash(),
            current_cat_issuance,
            proposal_pass_percentage,
            1000,
            LOCKUP_TIME,
        ]
    )
    full_proposal = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        treasury_id,
        200,
        350,
        Program.to(1),
    )
    conds = full_proposal.run(solution)
    assert len(conds.as_python()) == 6


def test_proposal_timer() -> None:
    proposal_pass_percentage: uint64 = uint64(15)
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
    # CAT_TAIL
    # CURRENT_CAT_ISSUANCE
    # PROPOSAL_TIMELOCK
    # PROPOSAL_PASS_PERCENTAGE
    # MY_PARENT_SINGLETON_STRUCT
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

    solution: Program = Program.to(
        [
            140,
            180,
            Program.to(1).get_tree_hash(),
            Program.to("parent").get_tree_hash(),
            23,
            200,
        ]
    )
    conds: Program = proposal_timer_full.run(solution)
    assert len(conds.as_python()) == 4


def test_treasury() -> None:
    current_cat_issuance: uint64 = uint64(1000)
    attendance_percentage: uint64 = uint64(15)
    CAT_TAIL: Program = Program.to("tail").get_tree_hash()
    LOCKUP_TIME: uint64 = uint64(200)
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    # SINGLETON_STRUCT
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # CAT_MOD_HASH
    # CAT_TAIL
    # CURRENT_CAT_ISSUANCE
    # PROPOSAL_PASS_PERCENTAGE
    # PROPOSAL_TIMELOCK
    full_treasury_puz: Program = DAO_TREASURY_MOD.curry(
        [
            singleton_struct,
            DAO_TREASURY_MOD.get_tree_hash(),
            DAO_PROPOSAL_MOD.get_tree_hash(),
            DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
            DAO_LOCKUP_MOD.get_tree_hash(),
            CAT_MOD.get_tree_hash(),
            CAT_TAIL,
            current_cat_issuance,
            attendance_percentage,
            5100,  # pass margin
            LOCKUP_TIME,
        ]
    )

    # my_amount         ; current amount
    # new_amount_change ; may be negative or positive. Is zero during eve spend
    # my_puzhash_or_proposal_id ; either the current treasury singleton puzzlehash OR proposal ID
    # announcement_messages_list_or_payment_nonce  ; this is a list of messages which the treasury will parrot - assert from the proposal and also create
    # new_puzhash  ; if this variable is 0 then we do the "add_money" spend case and all variables below are not needed
    # proposal_innerpuz
    # proposal_current_votes ; tally of yes votes
    # proposal_total_votes   ; total votes cast (by number of cat-mojos)
    # type  ; this is used for the recreating self type
    # extra_value  ; this is used for recreating self

    # Add money solution
    solution: Program = Program.to(
        [
            200,
            100,
            full_treasury_puz.get_tree_hash(),
            Program.to("payment_nonce").get_tree_hash(),
            0,
            0,
        ]
    )
    conds: Program = full_treasury_puz.run(solution)
    assert len(conds.as_python()) == 4

    solution = Program.to(
        [
            200,
            -100,
            Program.to("proposal_id").get_tree_hash(),
            [],
            full_treasury_puz.get_tree_hash(),
            Program.to("proposal_inner").get_tree_hash(),
            100,
            150,
            "u",
        ]
    )
    conds = full_treasury_puz.run(solution)
    assert len(conds.as_python()) == 6


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
    LOCKUP_TIME: uint64 = uint64(200)

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
    current_cat_issuance: uint64 = uint64(200)
    proposal_pass_percentage: uint64 = uint64(15)
    CAT_TAIL_HASH: Program = Program.to("tail").get_tree_hash()
    LOCKUP_TIME: uint64 = uint64(200)
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )

    new_puzhash = Program.to("new_puzhash").get_tree_hash()
    old_amount = 200
    spend_amount = 50
    new_amount_change = old_amount - spend_amount
    pass_margin = 5100

    # Setup Proposal
    P2_PH = Program.to("p2_ph").get_tree_hash()
    P2_CONDS = [[51, P2_PH, spend_amount]]

    proposal_innerpuz = DAO_SPEND_PROPOSAL.curry(P2_CONDS, new_puzhash, new_amount_change)

    full_proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL_HASH,
        singleton_id,
        200,
        350,
        proposal_innerpuz,
    )

    # vote_amount_or_solution  ; The qty of "votes" to add or subtract. ALWAYS POSITIVE.
    # vote_info_or_p2_singleton_mod_hash ; vote_info is whether we are voting YES or NO. XXX rename vote_type?
    # vote_coin_id_or_current_cat_issuance  ; this is either the coin ID we're taking a vote from OR...
    #                                       ; the total number of CATs in circulation according to the treasury
    # previous_votes_or_pass_margin  ; this is the active votes of the lockup we're communicating with
    #                                ; OR this is what percentage of the total votes must be YES - represented as an integer from 0 to 10,000 - typically this is set at 5100 (51%)
    # lockup_innerpuzhash_or_attendance_required  ; this is either the innerpuz of the locked up CAT we're taking a vote from OR
    #                                             ; the attendance required - the percentage of the current issuance which must have voted represented as 0 to 10,000 - this is announced by the treasury
    # proposal_timelock  ; we assert this from the treasury and announce it, so the timer knows what the the current timelock is
    #                    ; set this to 0 and we will do the vote spend case

    solution: Program = Program.to(
        [
            [],
            P2_SINGLETON_MOD.get_tree_hash(),
            current_cat_issuance,
            pass_margin,
            proposal_pass_percentage,
            LOCKUP_TIME,
        ]
    )

    full_prop_ph: bytes32 = SINGLETON_MOD.curry(singleton_struct, full_proposal).get_tree_hash()

    # Setup the treasury
    full_treasury_puz: Program = DAO_TREASURY_MOD.curry(
        [
            singleton_struct,
            DAO_TREASURY_MOD.get_tree_hash(),
            DAO_PROPOSAL_MOD.get_tree_hash(),
            DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
            DAO_LOCKUP_MOD.get_tree_hash(),
            CAT_MOD.get_tree_hash(),
            CAT_TAIL_HASH,
            current_cat_issuance,
            proposal_pass_percentage,
            pass_margin,
            LOCKUP_TIME,
        ]
    )
    # my_amount         ; current amount
    # new_amount_change ; may be negative or positive. Is zero during eve spend
    # my_puzhash_or_proposal_id ; either the current treasury singleton puzzlehash OR proposal ID
    # announcement_messages_list_or_payment_nonce  ; this is a list of messages which the treasury will parrot - assert from the proposal and also create
    # new_puzhash  ; if this variable is 0 then we do the "add_money" spend case and all variables below are not needed
    # proposal_innerpuz
    # proposal_current_votes ; tally of yes votes
    # proposal_total_votes   ; total votes cast (by number of cat-mojos)
    # type  ; this is used for the recreating self type
    # extra_value  ; this is used for recreating self

    treasury_solution: Program = Program.to(
        [
            old_amount,  # old_amount
            new_amount_change,  # new_amount_change
            singleton_id,  # my_puzhash_or_proposal_id
            [],  # announcement_messages_list_or_payment_nonce
            new_puzhash,  # amount_or_new_puzhash
            proposal_innerpuz,  # proposal_innerpuz
            200,  # current_votes
            350,  # total_votes
            "u",  # recreation type
            0,  # extra_value for recreation
        ]
    )

    # Run the puzzles
    treasury_conds: Program = full_treasury_puz.run(treasury_solution)
    proposal_conds: Program = full_proposal.run(solution)

    # Check the A_P_As from treasury match the C_P_As from the proposal
    cpa = b">"
    apa = b"?"
    cpas = []
    for cond in proposal_conds.as_python():
        if cond[0] == cpa:
            cpas.append(std_hash(full_prop_ph + bytes32(cond[1])))
    for cond in treasury_conds.as_python():
        if cond[0] == apa:
            assert bytes32(cond[1]) in cpas
