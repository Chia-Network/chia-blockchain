from __future__ import annotations

# mypy: ignore-errors
from clvm.casts import int_to_bytes

# from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.condition_tools import conditions_dict_for_solution
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm

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
SPEND_P2_SINGLETON_MOD: Program = load_clvm("dao_spend_p2_singleton.clvm")
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
DAO_UPDATE_MOD: Program = load_clvm("dao_update_proposal.clvm")
DAO_UPDATE_MOD_HASH: bytes32 = DAO_UPDATE_MOD.get_tree_hash()


def test_proposal() -> None:
    proposal_pass_percentage: uint64 = uint64(5100)
    CAT_TAIL_HASH: Program = Program.to("tail").get_tree_hash()
    treasury_id: Program = Program.to("treasury").get_tree_hash()
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (singleton_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    self_destruct_time = 1000  # number of blocks
    oracle_spend_delay = 10
    active_votes_list = [0xFADEDDAB]  # are the the ids of previously voted on proposals?
    acs: Program = Program.to(1)
    acs_ph: bytes32 = acs.get_tree_hash()

    # make a lockup puz for the dao cat
    lockup_puz = DAO_LOCKUP_MOD.curry(
        DAO_PROPOSAL_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_MOD_HASH,
        CAT_TAIL_HASH,
        active_votes_list,
        acs,  # innerpuz
    )

    dao_cat_puz: Program = CAT_MOD.curry(CAT_MOD_HASH, CAT_TAIL_HASH, lockup_puz)
    dao_cat_puzhash: bytes32 = dao_cat_puz.get_tree_hash()

    # Test Voting
    current_yes_votes = 20
    current_total_votes = 100
    full_proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        treasury_id,
        current_yes_votes,
        current_total_votes,
        "s",
        acs_ph,
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
        ]
    )

    # Run the proposal and check its conditions
    conditions = conditions_dict_for_solution(full_proposal, solution, INFINITE_COST)[1]

    # Puzzle Announcement of vote_coin_ids
    assert conditions[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT][0].vars[0] == vote_coin_id

    # Assert puzzle announcement from dao_cat of proposal_id and all vote details
    apa_msg = Program.to([singleton_id, vote_amount, vote_type, vote_coin_id]).get_tree_hash()
    assert conditions[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0] == std_hash(dao_cat_puzhash + apa_msg)

    # Check that the proposal recreates itself with updated vote amounts
    next_proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        treasury_id,
        current_yes_votes + vote_amount,
        current_total_votes + vote_amount,
        "s",
        acs_ph,
    )
    assert conditions[ConditionOpcode.CREATE_COIN][0].vars[0] == next_proposal.get_tree_hash()
    assert conditions[ConditionOpcode.CREATE_COIN][0].vars[1] == int_to_bytes(1)

    # Test Launch
    current_yes_votes = 0
    current_total_votes = 0
    launch_proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        treasury_id,
        current_yes_votes,
        current_total_votes,
        "s",
        acs_ph,
    )
    vote_amount = 10
    vote_type = 1  # yes vote
    vote_coin_id = Program.to("vote_coin").get_tree_hash()
    solution: Program = Program.to(
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
        ]
    )
    # Run the proposal and check its conditions
    conditions = conditions_dict_for_solution(launch_proposal, solution, INFINITE_COST)[1]
    # check that the timer is created
    timer_puz = DAO_PROPOSAL_TIMER_MOD.curry(
        DAO_PROPOSAL_MOD_HASH, DAO_PROPOSAL_TIMER_MOD_HASH, CAT_MOD_HASH, CAT_TAIL_HASH, singleton_struct, treasury_id
    )
    timer_puzhash = timer_puz.get_tree_hash()
    assert conditions[ConditionOpcode.CREATE_COIN][1].vars[0] == timer_puzhash

    # Test exits

    # Test attempt to close a passing proposal
    current_yes_votes = 200
    current_total_votes = 350
    full_proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        treasury_id,
        current_yes_votes,
        current_total_votes,
        "s",
        acs_ph,
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
        ]
    )

    conds = conditions_dict_for_solution(full_proposal, solution, INFINITE_COST)[1]

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
    full_proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        treasury_id,
        20,  # failing number of yes votes
        current_total_votes,
        "s",
        acs_ph,
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
        ]
    )
    conds = conditions_dict_for_solution(full_proposal, solution, INFINITE_COST)[1]
    apa_msg = int_to_bytes(0)
    assert conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][1].vars[0] == std_hash(treasury_puzhash + apa_msg)
    assert conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0] == timer_apa

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
        ]
    )
    conds = conditions_dict_for_solution(full_proposal, solution, INFINITE_COST)[1]
    # apa_msg = Program.to([proposal_pass_percentage, self_destruct_time]).get_tree_hash()
    assert conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0] == std_hash(treasury_puzhash + apa_msg)


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
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_MOD_HASH,
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

    # treasury_puzzle_hash = Program.to("treasury").get_tree_hash()

    p2_singleton = P2_SINGLETON_MOD.curry(singleton_struct)
    p2_singleton_puzhash = p2_singleton.get_tree_hash()
    parent_id = Program.to("parent").get_tree_hash()
    locked_amount = 100000
    spend_amount = 1100
    conditions = [[51, 0xDABBAD00, 1000], [51, 0xCAFEF00D, 100]]

    spend_p2_singleton = SPEND_P2_SINGLETON_MOD.curry(conditions, p2_singleton_puzhash)
    spend_p2_singleton_puzhash = spend_p2_singleton.get_tree_hash()
    spend_p2_singleton_solution = Program.to([[[parent_id, locked_amount]]])
    output_conds = spend_p2_singleton.run(spend_p2_singleton_solution)

    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        CAT_TAIL_HASH,
    )

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
    # SPEND_OR_UPDATE_FLAG  ; this is one of 's', 'u', 'd' - other types may be added in the future
    # PROPOSED_PUZ_HASH  ; this is what runs if this proposal is successful - the inner puzzle of this proposal
    proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        singleton_id,
        950,
        1200,
        "s",
        spend_p2_singleton_puzhash,
    )
    full_proposal = SINGLETON_MOD.curry(singleton_struct, proposal)
    solution = Program.to(
        [
            1000,
            5100,
            [full_proposal.get_tree_hash(), spend_p2_singleton_puzhash, 0, "s"],
            [singleton_id, 1200, 950, spend_amount],
            output_conds.as_python(),
        ]
    )
    conds: Program = proposal_validator.run(solution)
    assert len(conds.as_python()) == 3 + len(conditions)

    # test update
    proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        singleton_id,
        950,
        1200,
        "u",
        Program.to(1).get_tree_hash(),
    )
    full_proposal = SINGLETON_MOD.curry(singleton_struct, proposal)
    solution = Program.to(
        [
            1000,
            5100,
            [full_proposal.get_tree_hash(), Program.to(1).get_tree_hash(), 0, "u"],
            [singleton_id, 1200, 950, spend_amount],
            [[51, 0xCAFE00D, spend_amount]],
        ]
    )
    conds: Program = proposal_validator.run(solution)
    assert len(conds.as_python()) == 2

    return


def test_merge_p2_singleton() -> None:
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()

    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_HASH)))

    # Test that p2_singleton_via_delegated_puzzle will run
    p2_singleton = P2_SINGLETON_MOD.curry(singleton_struct)
    # singleton_inner_puzhash
    # delegated_puzzle
    # delegated_solution
    # my_id
    # my_puzhash
    # list_of_parent_amounts
    # my_amount
    conds = p2_singleton.run(Program.to([0, 0, 0, singleton_id, p2_singleton.get_tree_hash(), 0]))
    assert len(conds.as_python()) == 3
    fake_parent_id = Program.to("fake_parent").get_tree_hash()
    # fake_coin = Coin(fake_parent_id, p2_singleton.get_tree_hash(), 200)
    conds = p2_singleton.run(
        Program.to([0, 0, 0, singleton_id, p2_singleton.get_tree_hash(), [[fake_parent_id, 200]], 100])
    )
    assert len(conds.as_python()) == 6
    assert conds.rest().rest().rest().rest().rest().first().rest().rest().first().as_int() == 300
    return


def test_spend_p2_singleton() -> None:
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_HASH)))

    # Test that p2_singleton_via_delegated_puzzle will run
    p2_singleton = P2_SINGLETON_MOD.curry(singleton_struct)
    p2_singleton_puzhash = p2_singleton.get_tree_hash()
    parent_id = Program.to("parent").get_tree_hash()
    locked_amount = 100000
    singleton_inner_hash = Program.to(1).get_tree_hash()
    deleg_puz = Program.to(1)
    deleg_conds = Program.to([[51, 0xCAFEF00D, 1000]])
    # singleton_inner_puzhash
    # delegated_puzzle
    # delegated_solution
    # my_id
    p2_singleton_id = Program.to("p2_singleton_coin").get_tree_hash()
    conds = p2_singleton.run(Program.to([singleton_inner_hash, deleg_puz, deleg_conds, p2_singleton_id, 0, 0]))
    assert len(conds.as_python()) == 4

    spend_amount = 1100
    conditions = [[51, 0xDABBAD00, 1000], [51, 0xCAFEF00D, 100]]

    spend_p2_singleton = SPEND_P2_SINGLETON_MOD.curry(conditions, p2_singleton_puzhash)
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
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        CAT_TAIL_HASH,
    )
    proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        singleton_id,
        yes_votes,
        total_votes,
        "s",
        spend_p2_singleton_puzhash,
    )
    full_proposal = SINGLETON_MOD.curry(singleton_struct, proposal)
    validator_solution = Program.to(
        [
            attendance_required,
            pass_margin,
            [full_proposal.get_tree_hash(), spend_p2_singleton_puzhash, 0, "s"],
            [singleton_id, total_votes, yes_votes, spend_amount],
            output_conditions,
        ]
    )
    conds = proposal_validator.run(validator_solution)
    assert len(conds.as_python()) == 3 + len(conditions)


def test_treasury() -> None:
    CAT_TAIL_HASH: Program = Program.to("tail").get_tree_hash()
    singleton_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_HASH)))
    p2_singleton = P2_SINGLETON_MOD.curry(singleton_struct)
    p2_singleton_puzhash = p2_singleton.get_tree_hash()
    parent_id = Program.to("parent").get_tree_hash()
    locked_amount = 100000
    oracle_spend_delay = 10
    spend_amount = 1100
    conditions = [[51, 0xDABBAD00, 1000], [51, 0xCAFEF00D, 100]]

    spend_p2_singleton = SPEND_P2_SINGLETON_MOD.curry(conditions, p2_singleton_puzhash)
    spend_p2_singleton_puzhash = spend_p2_singleton.get_tree_hash()
    spend_p2_singleton_solution = Program.to([[[parent_id, locked_amount]]])

    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        CAT_TAIL_HASH,
    )

    # TREASURY_MOD_HASH
    # PROPOSAL_VALIDATOR
    # PROPOSAL_LENGTH
    # PROPOSAL_SOFTCLOSE_LENGTH
    # ATTENDANCE_REQUIRED
    # PASS_MARGIN  ; this is a percentage 0 - 10,000 - 51% would be 5100
    # PROPOSAL_SELF_DESTRUCT_TIME ; time in seconds after which proposals can be automatically closed
    # ORACLE_SPEND_DELAY  ; timelock delay for oracle spend
    self_destruct_time = 1000
    full_treasury_puz: Program = DAO_TREASURY_MOD.curry(
        DAO_TREASURY_MOD.get_tree_hash(),
        proposal_validator,
        40,
        5,
        1000,
        5100,
        self_destruct_time,
        oracle_spend_delay,
    )

    # treasury_puzzle_hash = full_treasury_puz.get_tree_hash()

    # (@ proposal_announcement (announcement_source delegated_puzzle_hash announcement_args spend_or_update_flag))
    # proposal_validator_solution
    # delegated_puzzle_reveal  ; this is the reveal of the puzzle announced by the proposal
    # delegated_solution  ; this is not secure unless the delegated puzzle secures it

    # Curry vals:
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
    # SPEND_OR_UPDATE_FLAG  ; this is one of 's', 'u', 'd' - other types may be added in the future
    # PROPOSED_PUZ_HASH  ; this is what runs if this proposal is successful - the inner puzzle of this proposal
    proposal: Program = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        singleton_id,
        950,
        1200,
        "s",
        spend_p2_singleton_puzhash,
    )
    full_proposal = SINGLETON_MOD.curry(singleton_struct, proposal)

    # Oracle spend
    solution: Program = Program.to([0])
    conds: Program = full_treasury_puz.run(solution)
    assert len(conds.as_python()) == 3

    # Run a passed proposal spend
    # (@ proposal_announcement (announcement_source delegated_puzzle_hash announcement_args spend_or_update_flag))
    # proposal_validator_solution
    # delegated_puzzle_reveal  ; this is the reveal of the puzzle announced by the proposal
    # delegated_solution  ; this is not secure unless the delegated puzzle secures it
    solution: Program = Program.to(
        [
            "p",
            [full_proposal.get_tree_hash(), spend_p2_singleton_puzhash, 0, "s"],
            [singleton_id, 1200, 950, spend_amount],
            spend_p2_singleton,
            spend_p2_singleton_solution,
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
        DAO_PROPOSAL_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_MOD_HASH,
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
        DAO_PROPOSAL_MOD_HASH,
        SINGLETON_MOD_HASH,
        SINGLETON_LAUNCHER_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_MOD_HASH,
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
    proposal_timelock = 40
    soft_close_length = 5
    self_destruct_time = 1000
    CAT_TAIL_HASH: Program = Program.to("tail").get_tree_hash()
    # LOCKUP_TIME: uint64 = uint64(200)
    oracle_spend_delay = 10

    # Setup the treasury
    treasury_id: Program = Program.to("treasury_id").get_tree_hash()
    treasury_singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (treasury_id, SINGLETON_LAUNCHER_HASH)))
    treasury_amount = 1

    # setup the p2_singleton
    p2_singleton = P2_SINGLETON_MOD.curry(treasury_singleton_struct)
    p2_singleton_puzhash = p2_singleton.get_tree_hash()
    parent_id = Program.to("parent").get_tree_hash()
    locked_amount = 100001
    spend_amount = 1100
    conditions = [[51, 0xDABBAD00, 1000], [51, 0xCAFEF00D, 100]]
    spend_p2_singleton = SPEND_P2_SINGLETON_MOD.curry(conditions, p2_singleton_puzhash)
    spend_p2_singleton_puzhash = spend_p2_singleton.get_tree_hash()
    spend_p2_singleton_solution = Program.to([[[parent_id, locked_amount]]])

    proposal_validator = DAO_PROPOSAL_VALIDATOR_MOD.curry(
        treasury_singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        CAT_TAIL_HASH,
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

    full_treasury_puz = SINGLETON_MOD.curry(treasury_singleton_struct, treasury_inner_puz)
    full_treasury_puzhash = full_treasury_puz.get_tree_hash()

    # Setup Proposal
    proposal_id: Program = Program.to("proposal_id").get_tree_hash()
    proposal_singleton_struct: Program = Program.to((SINGLETON_MOD_HASH, (proposal_id, SINGLETON_LAUNCHER_HASH)))

    current_votes = 1200
    yes_votes = 950
    proposal: Program = DAO_PROPOSAL_MOD.curry(
        proposal_singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        treasury_id,
        yes_votes,
        current_votes,
        "s",
        spend_p2_singleton_puzhash,
    )
    full_proposal: Program = SINGLETON_MOD.curry(proposal_singleton_struct, proposal)
    full_proposal_puzhash: bytes32 = full_proposal.get_tree_hash()

    treasury_solution: Program = Program.to(
        [
            "p",
            [full_proposal_puzhash, spend_p2_singleton_puzhash, 0, "s"],
            [proposal_id, current_votes, yes_votes, spend_amount],
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
        ]
    )

    # lineage_proof my_amount inner_solution
    lineage_proof = [treasury_id, treasury_inner_puzhash, treasury_amount]
    full_treasury_solution = Program.to([lineage_proof, treasury_amount, treasury_solution])
    full_proposal_solution = Program.to([lineage_proof, 1, proposal_solution])

    # Run the puzzles
    treasury_conds: Program = conditions_dict_for_solution(full_treasury_puz, full_treasury_solution, INFINITE_COST)[1]
    proposal_conds: Program = conditions_dict_for_solution(full_proposal, full_proposal_solution, INFINITE_COST)[1]

    # Announcements
    # Proposal CPA (proposal_timelock) <-> Treasury APA
    # Proposal APA (proposal_id, proposal_timelock, soft_close_length) <-> Treasury CPA
    treasury_apa = treasury_conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0]
    proposal_cpa = proposal_conds[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT][0].vars[0]
    assert std_hash(full_proposal_puzhash + proposal_cpa) == treasury_apa

    treasury_cpas = [
        std_hash(full_treasury_puzhash + cond.vars[0])
        for cond in treasury_conds[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT]
    ]
    proposal_apas = [cond.vars[0] for cond in proposal_conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT]]
    assert treasury_cpas[0] == proposal_apas[1]

    # Test Proposal to update treasury
    # Set up new treasury params
    new_proposal_pass_percentage: uint64 = uint64(2500)
    new_attendance_required: uint64 = uint64(500)
    new_proposal_timelock = 900
    new_soft_close_length = 10
    new_self_destruct_time = 1000
    new_oracle_spend_delay = 20

    update_proposal = DAO_UPDATE_MOD.curry(
        DAO_TREASURY_MOD_HASH,
        proposal_validator,
        new_proposal_timelock,
        new_soft_close_length,
        new_attendance_required,
        new_proposal_pass_percentage,
        new_self_destruct_time,
        new_oracle_spend_delay,
    )
    update_proposal_puzhash = update_proposal.get_tree_hash()
    update_proposal_sol = Program.to([])

    proposal: Program = DAO_PROPOSAL_MOD.curry(
        proposal_singleton_struct,
        DAO_PROPOSAL_MOD_HASH,
        DAO_PROPOSAL_TIMER_MOD_HASH,
        CAT_MOD_HASH,
        DAO_TREASURY_MOD_HASH,
        DAO_LOCKUP_MOD_HASH,
        CAT_TAIL_HASH,
        treasury_id,
        yes_votes,
        current_votes,
        "u",
        update_proposal_puzhash,
    )
    full_proposal: Program = SINGLETON_MOD.curry(proposal_singleton_struct, proposal)
    full_proposal_puzhash: bytes32 = full_proposal.get_tree_hash()

    treasury_solution: Program = Program.to(
        [
            "p",
            [full_proposal_puzhash, update_proposal_puzhash, 0, "u"],
            [proposal_id, current_votes, yes_votes, spend_amount],
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
        ]
    )

    lineage_proof = [treasury_id, treasury_inner_puzhash, treasury_amount]
    full_treasury_solution = Program.to([lineage_proof, treasury_amount, treasury_solution])
    full_proposal_solution = Program.to([lineage_proof, 1, proposal_solution])

    treasury_conds: Program = conditions_dict_for_solution(full_treasury_puz, full_treasury_solution, INFINITE_COST)[1]
    proposal_conds: Program = conditions_dict_for_solution(full_proposal, full_proposal_solution, INFINITE_COST)[1]

    treasury_apa = treasury_conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT][0].vars[0]
    proposal_cpa = proposal_conds[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT][0].vars[0]
    assert std_hash(full_proposal_puzhash + proposal_cpa) == treasury_apa

    treasury_cpas = [
        std_hash(full_treasury_puzhash + cond.vars[0])
        for cond in treasury_conds[ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT]
    ]
    proposal_apas = [cond.vars[0] for cond in proposal_conds[ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT]]
    assert treasury_cpas[0] == proposal_apas[1]
