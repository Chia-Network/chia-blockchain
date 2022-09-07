import json
from typing import Optional

import pytest
from blspy import AugSchemeMPL

from chia.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.program import Program
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint16, uint32, uint64
from chia.types.blockchain_format.coin import Coin
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.types.coin_spend import CoinSpend
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.cat_wallet.cat_utils import SpendableCAT, unsigned_spend_bundle_for_spendable_cats
from chia.wallet.lineage_proof import LineageProof

SINGLETON_MOD = load_clvm("singleton_top_layer_v1_1.clvm")
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")
DAO_EPHEMERAL_VOTE_MOD = load_clvm("dao_ephemeral_vote.clvm")
DAO_LOCKUP_MOD = load_clvm("dao_lockup.clvm")
DAO_PROPOSAL_TIMER_MOD = load_clvm("dao_proposal_timer.clvm")
DAO_PROPOSAL_MOD = load_clvm("dao_proposal.clvm")
DAO_TREASURY_MOD = load_clvm("dao_treasury.clvm")
P2_SINGLETON_MOD = load_clvm("p2_singleton_or_delayed_puzhash.clvm")

CAT_MOD_HASH = CAT_MOD.get_tree_hash()

def get_secret_key(pk_var):
    seed: bytes = bytes([0,  50, 6,  244, 24,  199, 1,  25,  52,  88,  192,
                            19, 18, 12, 89,  6,   220, 18, 102, 58,  209, 82,
                            12, 62, 89, 110, 182, 9,   44, 20,  254, 22])
    sk: PrivateKey = AugSchemeMPL.key_gen(seed)
    pk: G1Element = sk.get_g1()
    assert pk == pk_var
    return sk

def test_vote_from_locked_state():

    current_cat_issuance = 1000
    proposal_pass_percentage = 15
    CAT_TAIL = Program.to("tail").get_tree_hash()
    treasury_id = Program.to("treasury").get_tree_hash()
    LOCKUP_TIME = 200
    PREVIOUS_VOTES = [0xfadeddab]
    full_ephemeral_vote_puzzle = DAO_EPHEMERAL_VOTE_MOD.curry(
        DAO_PROPOSAL_MOD.get_tree_hash(),
        SINGLETON_MOD.get_tree_hash(),
        SINGLETON_LAUNCHER.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        DAO_EPHEMERAL_VOTE_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        LOCKUP_TIME,
    )

    proposal_id = Program.to("singleton_id").get_tree_hash()
    singleton_struct = Program.to((SINGLETON_MOD.get_tree_hash(), (proposal_id, SINGLETON_LAUNCHER.get_tree_hash())))

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
    # VOTES_SUM  ; yes votes are +1, no votes are -1
    # TOTAL_VOTES  ; how many people responded
    # INNERPUZ  ; this is what runs if this proposal is successful

    current_votes = 0
    total_votes = 0
    proposal_innerpuz = Program.to(1)
    full_proposal = DAO_PROPOSAL_MOD.curry(
        singleton_struct,
        DAO_PROPOSAL_MOD.get_tree_hash(),
        DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        DAO_TREASURY_MOD.get_tree_hash(),
        full_ephemeral_vote_puzzle.get_tree_hash(),
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
    seed: bytes = bytes([0,  50, 6,  244, 24,  199, 1,  25,  52,  88,  192,
                            19, 18, 12, 89,  6,   220, 18, 102, 58,  209, 82,
                            12, 62, 89, 110, 182, 9,   44, 20,  254, 22])
    sk: PrivateKey = AugSchemeMPL.key_gen(seed)
    pk: G1Element = sk.get_g1()

    full_lockup_puz = DAO_LOCKUP_MOD.curry(
        DAO_PROPOSAL_MOD.get_tree_hash(),
        SINGLETON_MOD.get_tree_hash(),
        SINGLETON_LAUNCHER.get_tree_hash(),
        DAO_LOCKUP_MOD.get_tree_hash(),
        full_ephemeral_vote_puzzle.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
        CAT_TAIL,
        PREVIOUS_VOTES,
        LOCKUP_TIME,
        pk,
    )

    lockup_coin_amount = 200
    lockup_parent_id = Coin(Program.to("fake_parent").get_tree_hash(), CAT_MOD.curry(CAT_MOD_HASH, CAT_TAIL, Program.to(1)).get_tree_hash(), lockup_coin_amount).name()

    cat_lockup_puzzlehash = CAT_MOD.curry(CAT_MOD_HASH, CAT_TAIL, full_lockup_puz)
    lockup_coin = Coin(lockup_parent_id, cat_lockup_puzzlehash.get_tree_hash(), lockup_coin_amount)

    # my_id  ; if my_id is 0 we do the return to return_address (exit voting mode) spend case
    # my_amount
    # new_proposal_vote_id_or_return_address
    # vote_info
    solution = Program.to([lockup_coin.name(), lockup_coin_amount, proposal_id, 1])
    # inner_puzzle_solution    ;; if invalid, INNER_PUZZLE will fail
    # lineage_proof            ;; This is the parent's coin info, used to check if the parent was a CAT. Optional if using tail_program.
    # prev_coin_id             ;; used in this coin's announcement, prev_coin ASSERT_COIN_ANNOUNCEMENT will fail if wrong
    # this_coin_info           ;; verified with ASSERT_MY_COIN_ID
    # next_coin_proof          ;; used to generate ASSERT_COIN_ANNOUNCEMENT
    # prev_subtotal            ;; included in announcement, prev_coin ASSERT_COIN_ANNOUNCEMENT will fail if wrong
    # extra_delta              ;; this is the "legal discrepancy" between your real delta and what you're announcing your delta is
    lineage_proof = [Program.to("fake_parent").get_tree_hash(), Program.to(1).get_tree_hash(), lockup_coin_amount]
    full_solution = Program.to([solution, lineage_proof, lockup_coin.name(), [lockup_parent_id, cat_lockup_puzzlehash.get_tree_hash(), lockup_coin_amount], lineage_proof, 0, 0])
    # coin: Coin
    # limitations_program_hash: bytes32
    # inner_puzzle: Program
    # inner_solution: Program
    # limitations_solution: Program = Program.to([])
    # lineage_proof: LineageProof = LineageProof()
    # extra_delta: int = 0
    # limitations_program_reveal: Program = Program.to([])
    sc_list = [SpendableCAT(
        coin=lockup_coin,
        limitations_program_hash=CAT_TAIL,
        inner_puzzle=full_lockup_puz,
        inner_solution=solution,
        lineage_proof=LineageProof(Program.to("fake_parent").get_tree_hash(), Program.to(1).get_tree_hash(), lockup_coin_amount)
    )]

    # cs_list = [CoinSpend(lockup_coin, cat_lockup_puzzlehash, full_solution)]

    cat_ephemeral_puzzle = CAT_MOD.curry(CAT_MOD_HASH, CAT_TAIL, full_ephemeral_vote_puzzle)
    ephemeral_vote_coin = Coin(lockup_coin.name(), cat_ephemeral_puzzle.get_tree_hash(), lockup_coin_amount)

    # proposal_id
    # previous_votes
    # my_amount  ; this is the weight of your vote
    # vote_info  ; this is the information about what to do with your vote  - atm just 1 for yes or 0 for no
    # pubkey
    # my_id
    # proposal_curry_vals  ; list of (PROPOSAL_TIMER_MOD_HASH EPHEMERAL_VOTE_PUZHASH CURRENT_CAT_ISSUANCE PROPOSAL_PASS_PERCENTAGE TREASURY_ID PROPOSAL_TIMELOCK current_votes total_votes INNERPUZHASH)
    proposal_curry_vals = [DAO_PROPOSAL_TIMER_MOD.get_tree_hash(),
        full_ephemeral_vote_puzzle.get_tree_hash(),
        current_cat_issuance,
        proposal_pass_percentage,
        treasury_id,
        LOCKUP_TIME,
        current_votes,
        total_votes,
        proposal_innerpuz.get_tree_hash(),
    ]

    lineage_proof = [lockup_coin.name(), full_lockup_puz.get_tree_hash(), lockup_coin_amount]
    ephemeral_vote_solution = Program.to([proposal_id, PREVIOUS_VOTES, lockup_coin_amount, 1, pk, ephemeral_vote_coin.name(), proposal_curry_vals])
    ephemeral_cat_solution = Program.to([ephemeral_vote_solution, lineage_proof, ephemeral_vote_coin.name(), ephemeral_vote_coin.name(), ephemeral_vote_coin.name(), 0, 0])
    # cs_list.append(CoinSpend(ephemeral_vote_coin, cat_ephemeral_puzzle, ephemeral_cat_solution))
    sc_list.append(SpendableCAT(
        coin=ephemeral_vote_coin,
        limitations_program_hash=CAT_TAIL,
        inner_puzzle=full_ephemeral_vote_puzzle,
        inner_solution=ephemeral_vote_solution,
        lineage_proof=LineageProof(lockup_parent_id, full_lockup_puz.get_tree_hash(), lockup_coin_amount)
    ))

    singleton_proposal_puzzle = SINGLETON_MOD.curry(singleton_struct, full_proposal)

    proposal_parent = Coin(Program.to("prop_parent").get_tree_hash(), SINGLETON_MOD.curry(singleton_struct, Program.to(1)).get_tree_hash(), 1)
    proposal_coin = Coin(proposal_parent.name(), singleton_proposal_puzzle.get_tree_hash(), 1)
    proposal_solution = Program.to([
        lockup_coin_amount,
        ephemeral_vote_coin.name(),
        1,
        0,
    ])
    singleton_solution = Program.to([[Program.to("prop_parent").get_tree_hash(), Program.to(1).get_tree_hash(), 1], 1, proposal_solution])
    cs_list = [(CoinSpend(proposal_coin, full_proposal, proposal_solution))]

#     (sha256tree (list
        # new_proposal_vote_id_or_return_address
        # vote_info
    # )
    # )
    usb = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, sc_list)
    sig = AugSchemeMPL.sign(sk, bytes(lockup_coin.name() + Program.to([proposal_id, 1]).get_tree_hash()))
    spend_bundle = SpendBundle(cs_list, sig)
    spend_bundle = usb.aggregate([usb, spend_bundle])
    breakpoint()
