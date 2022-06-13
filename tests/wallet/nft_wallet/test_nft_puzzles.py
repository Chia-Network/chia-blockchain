from typing import Tuple

from clvm.casts import int_from_bytes

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.nft_wallet import uncurry_nft
from chia.wallet.nft_wallet.nft_puzzles import (
    construct_ownership_layer,
    create_full_puzzle,
    create_nft_layer_puzzle_with_curry_params,
    recurry_nft_puzzle,
)
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions
from tests.core.make_block_generator import int_to_public_key

SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
DID_MOD = load_clvm("did_innerpuz.clvm")
NFT_STATE_LAYER_MOD = load_clvm("nft_state_layer.clvm")
NFT_OWNERSHIP_LAYER = load_clvm("nft_ownership_layer.clvm")
NFT_TRANSFER_PROGRAM_DEFAULT = load_clvm("nft_ownership_transfer_program_one_way_claim_with_royalties.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()
OFFER_MOD = load_clvm("settlement_payments.clvm")

LAUNCHER_ID = Program.to(b"launcher-id").get_tree_hash()
NFT_METADATA_UPDATER_DEFAULT = load_clvm("nft_metadata_updater_default.clvm")


def make_a_new_solution() -> Tuple[Program, Program]:
    destination = int_to_public_key(2)
    p2_puzzle = puzzle_for_pk(destination)
    puzhash = p2_puzzle.get_tree_hash()
    new_did = Program.to("test").get_tree_hash()
    new_did_inner_hash = Program.to("fake").get_tree_hash()
    trade_prices_list = [[200]]

    condition_list = [
        [
            51,
            puzhash,
            1,
            [puzhash],
        ],
        [-10, new_did, trade_prices_list, new_did_inner_hash],
    ]
    solution = Program.to(
        [
            [solution_for_conditions(condition_list)],
        ]
    )
    return p2_puzzle, solution


def make_a_new_ownership_layer_puzzle() -> Tuple[Program, Program]:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    old_did = Program.to("test_2").get_tree_hash()
    nft_id = Program.to("nft_id")
    SINGLETON_STRUCT = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    curried_tp = NFT_TRANSFER_PROGRAM_DEFAULT.curry(
        SINGLETON_STRUCT,
        innerpuz.get_tree_hash(),
        2000,
        OFFER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
    )
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
        code = int_from_bytes(condition.first().atom)
        if code == 51:
            if int_from_bytes(condition.rest().rest().first().atom) == 1:
                # this is our new puzzle hash
                return bytes32(condition.rest().first().atom)
    raise ValueError("No create coin condition found")


def test_transfer_puzzle_builder() -> None:
    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]
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
    clvm_puzzle_hash = get_updated_nft_puzzle(clvm_nft_puzzle, solution)
    unft = uncurry_nft.UncurriedNFT.uncurry(puzzle)
    assert unft.nft_state_layer == clvm_nft_puzzle
    assert unft.inner_puzzle == ownership_puzzle
    assert unft.p2_puzzle == p2_puzzle
    ol_puzzle = recurry_nft_puzzle(unft, solution.first(), sp2_puzzle)
    nft_puzzle = create_nft_layer_puzzle_with_curry_params(
        Program.to(metadata), NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(), ol_puzzle
    )
    assert clvm_puzzle_hash == nft_puzzle.get_tree_hash()
