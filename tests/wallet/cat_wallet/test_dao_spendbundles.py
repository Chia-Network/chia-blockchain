# type: ignore

from blspy import AugSchemeMPL, G1Element, PrivateKey, G2Element
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from typing import List
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.types.blockchain_format.coin import Coin
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.types.coin_spend import CoinSpend
from chia.wallet.cat_wallet.cat_utils import SpendableCAT, unsigned_spend_bundle_for_spendable_cats
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions

SINGLETON_MOD: Program = load_clvm("singleton_top_layer_v1_1.clvm")
SINGLETON_LAUNCHER: Program = load_clvm("singleton_launcher.clvm")
DAO_LOCKUP_MOD: Program = load_clvm("dao_lockup.clvm")
DAO_PROPOSAL_TIMER_MOD: Program = load_clvm("dao_proposal_timer.clvm")
DAO_PROPOSAL_MOD: Program = load_clvm("dao_proposal.clvm")
DAO_TREASURY_MOD: Program = load_clvm("dao_treasury.clvm")
P2_SINGLETON_MOD: Program = load_clvm("p2_singleton_or_delayed_puzhash.clvm")

CAT_MOD_HASH: bytes32 = CAT_MOD.get_tree_hash()


def test_vote_from_locked_state():

    current_cat_issuance: uint64 = uint64(1000)
    proposal_pass_percentage: uint64 = uint64(15)
    CAT_TAIL: Program = Program.to("tail").get_tree_hash()
    treasury_id: Program = Program.to("treasury").get_tree_hash()
    LOCKUP_TIME: uint64 = uint64(200)
    PREVIOUS_VOTES: List[bytes] = [0xFADEDDAB]

    proposal_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (proposal_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )

    current_votes: uint64 = uint64(0)
    total_votes: uint64 = uint64(0)
    proposal_innerpuz: Program = Program.to(1)

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
        current_votes,
        total_votes,
        proposal_innerpuz,
    )

    # Example seed, used to generate private key. Taken from the github readme.
    seed: bytes = bytes(
        [
            0,
            50,
            6,
            244,
            24,
            199,
            1,
            25,
            52,
            88,
            192,
            19,
            18,
            12,
            89,
            6,
            220,
            18,
            102,
            58,
            209,
            82,
            12,
            62,
            89,
            110,
            182,
            9,
            44,
            20,
            254,
            22,
        ]
    )
    sk: PrivateKey = AugSchemeMPL.key_gen(seed)
    pk: G1Element = sk.get_g1()

    # PROPOSAL_MOD_HASH
    # SINGLETON_MOD_HASH
    # SINGLETON_LAUNCHER_PUZHASH
    # LOCKUP_MOD_HASH
    # CAT_MOD_HASH
    # CAT_TAIL
    # PREVIOUS_VOTES
    # LOCKUP_TIME
    # PUBKEY

    innerpuz = puzzle_for_pk(pk)
    full_lockup_puz: Program = DAO_LOCKUP_MOD.curry(
        DAO_PROPOSAL_MOD.get_tree_hash(),
        SINGLETON_MOD.get_tree_hash(),
        SINGLETON_LAUNCHER.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        PREVIOUS_VOTES,
        LOCKUP_TIME,
        innerpuz,
    )

    lockup_coin_amount: uint64 = uint64(200)
    lockup_parent_id: bytes32 = Coin(
        Program.to("fake_parent").get_tree_hash(),
        CAT_MOD.curry(CAT_MOD_HASH, CAT_TAIL, Program.to(1)).get_tree_hash(),
        lockup_coin_amount,
    ).name()

    cat_lockup_puzzlehash: bytes32 = CAT_MOD.curry(CAT_MOD_HASH, CAT_TAIL, full_lockup_puz)
    lockup_coin: Coin = Coin(lockup_parent_id, cat_lockup_puzzlehash.get_tree_hash(), lockup_coin_amount)

    # TREASURY_MOD_HASH
    # PROPOSAL_TIMER_MOD_HASH
    # CURRENT_CAT_ISSUANCE
    # PROPOSAL_PASS_PERCENTAGE
    # TREASURY_ID
    # PROPOSAL_TIMELOCK
    # SUM_VOTES
    # TOTAL_VOTES
    # INNERPUZHASH

    proposal_curry_vals: List = [
        DAO_TREASURY_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        current_cat_issuance,
        proposal_pass_percentage,
        treasury_id,
        LOCKUP_TIME,
        current_votes,
        total_votes,
        proposal_innerpuz.get_tree_hash(),
    ]

    # my_id  ; if my_id is 0 we do the return to return_address (exit voting mode) spend case
    # inner_solution
    # my_amount
    # new_proposal_vote_id
    # vote_info
    # proposal_curry_vals
    NEW_PREVIOUS_VOTES = [proposal_id, 0xFADEDDAB]
    child_puzhash: Program = DAO_LOCKUP_MOD.curry(
        DAO_PROPOSAL_MOD.get_tree_hash(),
        SINGLETON_MOD.get_tree_hash(),
        SINGLETON_LAUNCHER.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        NEW_PREVIOUS_VOTES,  # this is the important line
        LOCKUP_TIME,
        innerpuz,
    ).get_tree_hash()
    message = Program.to([proposal_id, lockup_coin_amount, 1, lockup_coin.name()]).get_tree_hash()
    conditions = [[51, child_puzhash, lockup_coin_amount], [62, message]]
    inner_sol = solution_for_conditions(conditions)

    solution: Program = Program.to(
        [
            lockup_coin.name(),
            inner_sol,
            lockup_coin_amount,
            proposal_id,
            proposal_curry_vals,
            1,
        ]
    )

    sc_list: List[SpendableCAT] = [
        SpendableCAT(
            coin=lockup_coin,
            limitations_program_hash=CAT_TAIL,
            inner_puzzle=full_lockup_puz,
            inner_solution=solution,
            lineage_proof=LineageProof(
                Program.to("fake_parent").get_tree_hash(), Program.to(1).get_tree_hash(), lockup_coin_amount
            ),
        )
    ]

    singleton_proposal_puzzle: Program = SINGLETON_MOD.curry(singleton_struct, full_proposal)

    proposal_parent: Coin = Coin(
        Program.to("prop_parent").get_tree_hash(),
        SINGLETON_MOD.curry(singleton_struct, Program.to(1)).get_tree_hash(),
        1,
    )
    proposal_coin: Coin = Coin(proposal_parent.name(), singleton_proposal_puzzle.get_tree_hash(), 1)
    # vote_amount_or_solution
    # vote_info_or_p2_singleton_mod_hash
    # vote_coin_id  ; set this to 0 if we have passed
    # previous_votes
    # pubkey
    proposal_solution: Program = Program.to(
        [lockup_coin_amount, 1, lockup_coin.name(), PREVIOUS_VOTES, innerpuz.get_tree_hash()]
    )
    singleton_solution: Program = Program.to(
        [[Program.to("prop_parent").get_tree_hash(), Program.to(1).get_tree_hash(), 1], 1, proposal_solution]
    )
    cs_list: List[CoinSpend] = [(CoinSpend(proposal_coin, singleton_proposal_puzzle, singleton_solution))]

    #     (sha256tree (list
    # new_proposal_vote_id_or_return_address
    # vote_info
    # )
    # )
    usb: SpendBundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, sc_list)
    sig: G2Element = AugSchemeMPL.sign(sk, bytes(lockup_coin.name() + Program.to([proposal_id, 1]).get_tree_hash()))
    spend_bundle: SpendBundle = SpendBundle(cs_list, sig)
    spend_bundle: SpendBundle = usb.aggregate([usb, spend_bundle])
    breakpoint()
    # TODO: add asserts here


def test_close_proposal():

    current_cat_issuance: uint64 = uint64(1000)
    proposal_pass_percentage: uint64 = uint64(15)
    CAT_TAIL: Program = Program.to("tail").get_tree_hash()
    treasury_id: Program = Program.to("treasury").get_tree_hash()
    LOCKUP_TIME: uint64 = uint64(200)
    PREVIOUS_VOTES: List[bytes] = [0xFADEDDAB]

    proposal_id: Program = Program.to("singleton_id").get_tree_hash()
    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (proposal_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )

    current_votes: uint64 = uint64(0)
    total_votes: uint64 = uint64(0)
    proposal_innerpuz: Program = Program.to(1)

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
        current_votes,
        total_votes,
        proposal_innerpuz,
    )

    # Proposal spend

    singleton_struct: Program = Program.to(
        (SINGLETON_MOD.get_tree_hash(), (treasury_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )

    full_treasury_puz = DAO_TREASURY_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        P2_SINGLETON_MOD,
        CAT_MOD_HASH,
        CAT_TAIL,
        current_cat_issuance,
        proposal_pass_percentage,
        LOCKUP_TIME,
    )

    singleton_treasury: Program = SINGLETON_MOD.curry(singleton_struct, full_treasury_puz)

    treasury_parent: Coin = Coin(
        Program.to("treasury_parent").get_tree_hash(),
        SINGLETON_MOD.curry(singleton_struct, Program.to(1)).get_tree_hash(),
        5001,
    )

    treasury_coin: Coin = Coin(
        treasury_parent.name(),
        singleton_treasury.get_tree_hash(),
        5001,
    )

    # Proposal Timer spend

    timer_puz = DAO_PROPOSAL_TIMER_MOD.curry(
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD_HASH,
        CAT_TAIL,
        current_cat_issuance,
        LOCKUP_TIME,
        proposal_pass_percentage,
        singleton_struct,
        treasury_id,
    )

    # Proposal spend

    singleton_proposal_puzzle: Program = SINGLETON_MOD.curry(singleton_struct, full_proposal)

    proposal_parent: Coin = Coin(
        Program.to("prop_parent").get_tree_hash(),
        SINGLETON_MOD.curry(singleton_struct, Program.to(1)).get_tree_hash(),
        1,
    )
    proposal_coin: Coin = Coin(proposal_parent.name(), singleton_proposal_puzzle.get_tree_hash(), 1)
    # vote_amount_or_solution
    # vote_info_or_p2_singleton_mod_hash
    # vote_coin_id  ; set this to 0 if we have passed
    # previous_votes
    # pubkey
    payout_solution = Program.to([])
    proposal_solution: Program = Program.to(
        [
            payout_solution,
            P2_SINGLETON_MOD.get_tree_hash(),
            0,
        ]
    )
