from chia.types.blockchain_format.program import Program
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


def test_proposal() -> None:
    # SINGLETON_STRUCT
    # PROPOSAL_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # CAT_MOD_HASH
    # TREASURY_MOD_HASH
    # LOCKUP_MOD_HASH  ; this is the mod already curried with what it needs - should still be a constant
    # CAT_TAIL
    # CURRENT_CAT_ISSUANCE
    # PROPOSAL_PASS_PERCENTAGE
    # TREASURY_ID
    # PROPOSAL_TIMELOCK
    # VOTES_SUM  ; yes votes are +1, no votes are -1
    # TOTAL_VOTES  ; how many people responded
    # INNERPUZ  ; this is what runs if this proposal is successful

    current_cat_issuance: uint64 = uint64(1000)
    proposal_pass_percentage: uint64 = uint64(15)
    CAT_TAIL: Program = Program.to("tail").get_tree_hash()
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
        CAT_TAIL,
        current_cat_issuance,
        proposal_pass_percentage,
        treasury_id,
        LOCKUP_TIME,
        20,
        100,
        Program.to(1),
    )
    # vote_amount_or_solution
    # vote_info_or_p2_singleton_mod_hash
    # vote_coin_id  ; set this to 0 if we have passed
    # previous_votes
    # pubkey

    # Test Voting
    solution: Program = Program.to(
        [
            10,
            1,
            Program.to("vote_coin").get_tree_hash(),
            [0xFADEDDAB],
            0xCAFEF00D,
        ]
    )
    conds: Program = full_proposal.run(solution)
    assert len(conds.as_python()) == 3
    # Test exit
    solution = Program.to([[[51, 0xCAFEF00D, 200]], P2_SINGLETON_MOD.get_tree_hash(), 0])
    full_proposal = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_TAIL,
        current_cat_issuance,
        proposal_pass_percentage,
        treasury_id,
        LOCKUP_TIME,
        200,
        350,
        Program.to(1),
    )
    conds = full_proposal.run(solution)
    assert len(conds.as_python()) == 6


def test_proposal_timer() -> None:
    current_cat_issuance: uint64 = uint64(1000)
    proposal_pass_percentage: uint64 = uint64(15)
    CAT_TAIL: Program = Program.to("tail").get_tree_hash()
    treasury_id: Program = Program.to("treasury").get_tree_hash()
    LOCKUP_TIME: uint64 = uint64(200)
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
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
    proposal_timer_full: Program = DAO_PROPOSAL_TIMER_MOD.curry(
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        current_cat_issuance,
        LOCKUP_TIME,
        proposal_pass_percentage,
        singleton_struct,
        treasury_id,
    )

    # proposal_current_votes
    # proposal_innerpuzhash
    # proposal_parent_id
    # proposal_amount

    solution: Program = Program.to([140, 180, Program.to(1).get_tree_hash(), Program.to("parent").get_tree_hash(), 23])
    conds: Program = proposal_timer_full.run(solution)
    assert len(conds.as_python()) == 4


def test_treasury() -> None:
    current_cat_issuance: uint64 = uint64(1000)
    proposal_pass_percentage: uint64 = uint64(15)
    CAT_TAIL: Program = Program.to("tail").get_tree_hash()
    LOCKUP_TIME: uint64 = uint64(200)
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
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
    full_treasury_puz: Program = DAO_TREASURY_MOD.curry(
        singleton_struct,
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        P2_SINGLETON_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        current_cat_issuance,
        proposal_pass_percentage,
        LOCKUP_TIME,
    )

    # old_amount
    # new_amount_change
    # my_puzhash_or_proposal_id
    # announcement_messages_list_or_payment_nonce  ; this is a list of messages which the
    # treasury will parrot - assert from the proposal and also create
    # new_puzhash  ; if this variable is 0 then we do the "add_money" spend case and all variables below are not needed
    # proposal_innerpuz
    # proposal_current_votes
    # proposal_total_votes

    # Add money solution
    solution: Program = Program.to(
        [
            200,
            100,
            full_treasury_puz.get_tree_hash(),
            Program.to("payment_nonce").get_tree_hash(),
            0,
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
        ]
    )
    conds = full_treasury_puz.run(solution)
    assert len(conds.as_python()) == 5


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
        LOCKUP_TIME,
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
        LOCKUP_TIME,
        INNERPUZ,
    ).get_tree_hash()
    message = Program.to([new_proposal, lockup_coin_amount, 1, my_id]).get_tree_hash()
    generated_conditions = [[51, child_puzhash, lockup_coin_amount], [62, message]]
    # my_id  ; if my_id is 0 we do the return to return_address (exit voting mode) spend case
    # inner_solution
    # my_amount
    # new_proposal_vote_id
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
        ]
    )
    conds: Program = full_lockup_puz.run(solution)
    assert len(conds.as_python()) == 5

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
