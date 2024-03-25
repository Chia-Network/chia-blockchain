from __future__ import annotations

import random
from typing import Tuple

from chia._tests.core.make_block_generator import int_to_public_key
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.nft_wallet import uncurry_nft
from chia.wallet.nft_wallet.nft_puzzles import (
    construct_ownership_layer,
    create_full_puzzle,
    create_nft_layer_puzzle_with_curry_params,
    recurry_nft_puzzle,
)
from chia.wallet.outer_puzzles import match_puzzle
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions
from chia.wallet.uncurried_puzzle import uncurry_puzzle

SINGLETON_MOD = load_clvm("singleton_top_layer_v1_1.clsp")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clsp")
DID_MOD = load_clvm("did_innerpuz.clsp", package_or_requirement="chia.wallet.did_wallet.puzzles")
NFT_STATE_LAYER_MOD = load_clvm("nft_state_layer.clsp", package_or_requirement="chia.wallet.nft_wallet.puzzles")
NFT_OWNERSHIP_LAYER = load_clvm("nft_ownership_layer.clsp", package_or_requirement="chia.wallet.nft_wallet.puzzles")
NFT_TRANSFER_PROGRAM_DEFAULT = load_clvm(
    "nft_ownership_transfer_program_one_way_claim_with_royalties.clsp",
    package_or_requirement="chia.wallet.nft_wallet.puzzles",
)
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()
OFFER_MOD = load_clvm("settlement_payments.clsp")

LAUNCHER_ID = Program.to(b"launcher-id").get_tree_hash()
NFT_METADATA_UPDATER_DEFAULT = load_clvm(
    "nft_metadata_updater_default.clsp", package_or_requirement="chia.wallet.nft_wallet.puzzles"
)


def test_nft_transfer_puzzle_hashes(seeded_random: random.Random) -> None:
    maker_pk = int_to_public_key(111)
    maker_p2_puz = puzzle_for_pk(maker_pk)
    maker_p2_ph = maker_p2_puz.get_tree_hash()
    maker_did = Program.to("maker did").get_tree_hash()
    # maker_did_inner_hash = Program.to("maker did inner hash").get_tree_hash()
    metadata = [("u", ["https://www.chia.net/img/branding/chia-logo.svg"]), ("h", 0xD4584AD463139FA8C0D9F68F4B59F185)]
    metadata_updater_hash = NFT_METADATA_UPDATER_DEFAULT.get_tree_hash()
    # royalty_addr = maker_p2_ph
    royalty_pc = 2000  # basis pts
    nft_id = Program.to("nft id").get_tree_hash()
    SINGLETON_STRUCT = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    transfer_puz = NFT_TRANSFER_PROGRAM_DEFAULT.curry(SINGLETON_STRUCT, maker_p2_ph, royalty_pc)
    ownership_puz = NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER.get_tree_hash(), maker_did, transfer_puz, maker_p2_puz
    )
    metadata_puz = NFT_STATE_LAYER_MOD.curry(
        NFT_STATE_LAYER_MOD.get_tree_hash(), metadata, metadata_updater_hash, ownership_puz
    )
    nft_puz = SINGLETON_MOD.curry(SINGLETON_STRUCT, metadata_puz)
    nft_info = match_puzzle(uncurry_puzzle(nft_puz))
    assert nft_info is not None
    also = nft_info.also()
    assert also is not None
    also_also = also.also()
    assert also_also is not None

    unft = uncurry_nft.UncurriedNFT.uncurry(*nft_puz.uncurry())
    assert unft is not None
    assert unft.supports_did

    # setup transfer
    taker_pk = int_to_public_key(222)
    taker_p2_puz = puzzle_for_pk(taker_pk)
    taker_p2_ph = taker_p2_puz.get_tree_hash()

    # make nft solution
    fake_lineage_proof = Program.to([bytes32.random(seeded_random), maker_p2_ph, 1])
    transfer_conditions = Program.to([[51, taker_p2_ph, 1, [taker_p2_ph]], [-10, [], [], []]])

    ownership_sol = Program.to([solution_for_conditions(transfer_conditions)])

    metadata_sol = Program.to([ownership_sol])
    nft_sol = Program.to([fake_lineage_proof, 1, metadata_sol])

    conds = nft_puz.run(nft_sol)

    # get the new NFT puzhash
    for cond in conds.as_iter():
        if cond.first().as_int() == 51:
            expected_ph = bytes32(cond.at("rf").as_atom())

    # recreate the puzzle for new_puzhash
    new_ownership_puz = NFT_OWNERSHIP_LAYER.curry(NFT_OWNERSHIP_LAYER.get_tree_hash(), None, transfer_puz, taker_p2_puz)
    new_metadata_puz = NFT_STATE_LAYER_MOD.curry(
        NFT_STATE_LAYER_MOD.get_tree_hash(), metadata, metadata_updater_hash, new_ownership_puz
    )
    new_nft_puz = SINGLETON_MOD.curry(SINGLETON_STRUCT, new_metadata_puz)
    calculated_ph = new_nft_puz.get_tree_hash()

    assert expected_ph == calculated_ph


def make_a_new_solution() -> Tuple[Program, Program]:
    destination = int_to_public_key(2)
    p2_puzzle = puzzle_for_pk(destination)
    puzhash = p2_puzzle.get_tree_hash()
    new_did = Program.to("test").get_tree_hash()
    new_did_inner_hash = Program.to("fake").get_tree_hash()
    trade_prices_list = [[200, OFFER_MOD.get_tree_hash()]]
    condition_list = [[51, puzhash, 1, [puzhash]], [-10, new_did, trade_prices_list, new_did_inner_hash]]
    solution = Program.to([[], [], [[solution_for_conditions(condition_list)]]])
    return p2_puzzle, solution


def make_a_new_ownership_layer_puzzle() -> Tuple[Program, Program]:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    old_did = Program.to("test_2").get_tree_hash()
    nft_id = Program.to("nft_id")
    SINGLETON_STRUCT = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    curried_tp = NFT_TRANSFER_PROGRAM_DEFAULT.curry(SINGLETON_STRUCT, innerpuz.get_tree_hash(), 2000)
    curried_inner = innerpuz
    curried_ownership_layer = construct_ownership_layer(old_did, curried_tp, curried_inner)
    return innerpuz, curried_ownership_layer


def make_a_new_nft_puzzle(curried_ownership_layer: Program, metadata: Program) -> Program:
    curried_state_layer = NFT_STATE_LAYER_MOD.curry(
        NFT_STATE_LAYER_MOD_HASH, metadata, NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(), curried_ownership_layer
    )
    return curried_state_layer


def get_updated_nft_puzzle(puzzle: Program, solution: Program) -> bytes32:
    result = puzzle.run(solution)
    for condition in result.as_iter():
        code = condition.first().as_int()
        if code == 51:
            if condition.at("rrf").as_int() == 1:
                # this is our new puzzle hash
                return bytes32(condition.at("rf").as_atom())
    raise ValueError("No create coin condition found")


def test_transfer_puzzle_builder() -> None:
    metadata = [("u", ["https://www.chia.net/img/branding/chia-logo.svg"]), ("h", 0xD4584AD463139FA8C0D9F68F4B59F185)]
    sp2_puzzle, solution = make_a_new_solution()
    p2_puzzle, ownership_puzzle = make_a_new_ownership_layer_puzzle()
    clvm_nft_puzzle = create_nft_layer_puzzle_with_curry_params(
        Program.to(metadata), NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(), ownership_puzzle
    )
    puzzle = create_full_puzzle(
        Program.to(["singleton_id"]).get_tree_hash(),
        Program.to(metadata),
        NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(),
        ownership_puzzle,
    )
    clvm_puzzle_hash = get_updated_nft_puzzle(clvm_nft_puzzle, solution.at("rrf"))
    unft = uncurry_nft.UncurriedNFT.uncurry(*puzzle.uncurry())
    assert unft is not None
    assert unft.nft_state_layer == clvm_nft_puzzle
    assert unft.inner_puzzle == ownership_puzzle
    assert unft.p2_puzzle == p2_puzzle
    ol_puzzle = recurry_nft_puzzle(unft, solution, sp2_puzzle)
    nft_puzzle = create_nft_layer_puzzle_with_curry_params(
        Program.to(metadata), NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(), ol_puzzle
    )
    assert clvm_puzzle_hash == nft_puzzle.get_tree_hash()
