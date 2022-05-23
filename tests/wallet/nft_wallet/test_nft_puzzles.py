from typing import Tuple

from clvm.casts import int_from_bytes

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.nft_wallet import uncurry_nft
from chia.wallet.nft_wallet.nft_puzzles import create_full_puzzle, generate_new_puzzle
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions
from chia.wallet.util.debug_spend_bundle import disassemble
from tests.core.make_block_generator import int_to_public_key

SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
DID_MOD = load_clvm("did_innerpuz.clvm")
NFT_STATE_LAYER_MOD = load_clvm("nft_state_layer.clvm")
NFT_OWNERSHIP_LAYER = load_clvm("nft_ownership_layer.clvm")
NFT_TRANSFER_PROGRAM_DEFAULT = load_clvm("nft_ownership_transfer_program_one_way_claim_with_royalties.clvm")
NFT_INNER_INNERPUZ = load_clvm("nft_v1_innerpuz.clvm")
STANDARD_PUZZLE_MOD = load_clvm("p2_delegated_puzzle_or_hidden_puzzle.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()
OFFER_MOD = load_clvm("settlement_payments.clvm")

LAUNCHER_ID = Program.to(b"launcher-id").get_tree_hash()
NFT_METADATA_UPDATER_DEFAULT = load_clvm("nft_metadata_updater_default.clvm")
NFT_METADATA_UPDATER_UPDATEABLE = load_clvm("nft_metadata_updater_updateable.clvm")


def make_a_new_solution() -> Program:

    destination = int_to_public_key(2)
    new_did = Program.to("test").get_tree_hash()
    new_did_inner_hash = Program.to("fake").get_tree_hash()
    trade_prices_list = [[200]]
    my_amount = 1

    condition_list = [new_did, trade_prices_list, destination, [new_did_inner_hash], 0, 0, [[60, "congraultions"]]]
    solution = Program.to(
        [
            [[solution_for_conditions(condition_list)]],
            my_amount,
        ]
    )
    return solution


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
    curried_inner = NFT_INNER_INNERPUZ.curry(
        STANDARD_PUZZLE_MOD.get_tree_hash(),
        NFT_INNER_INNERPUZ.get_tree_hash(),
        STANDARD_PUZZLE_MOD.curry(pubkey),
    )
    curried_ownership_layer = NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER.get_tree_hash(),
        old_did,
        curried_tp,
        curried_inner,
    )
    return innerpuz, curried_ownership_layer


def make_a_new_nft_puzzle(curried_ownership_layer, metadata) -> Program:
    curried_state_layer = NFT_STATE_LAYER_MOD.curry(
        NFT_STATE_LAYER_MOD_HASH,
        metadata,
        NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(),
        curried_ownership_layer,
    )
    return curried_state_layer


def get_updated_nft_puzzle(curried_state_layer, solution):
    result = curried_state_layer.run(solution)
    for condition in result.as_iter():
        print(condition.as_python())
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
    solution = make_a_new_solution()
    p2_puzzle, ownership_puzzle = make_a_new_ownership_layer_puzzle()
    clvm_puzzle = make_a_new_nft_puzzle(ownership_puzzle, metadata)
    puzzle = create_full_puzzle(
        Program.to(["singleton_id"]).get_tree_hash(),
        Program.to(metadata),
        NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(),
        clvm_puzzle,
    )
    unft = uncurry_nft.UncurriedNFT.uncurry(puzzle)
    py_puzzle = generate_new_puzzle(unft, p2_puzzle, metadata, solution)
    assert disassemble(clvm_puzzle) == disassemble(py_puzzle)
