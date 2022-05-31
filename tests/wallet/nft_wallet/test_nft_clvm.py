from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions
from chia.wallet.puzzles.puzzle_utils import make_create_coin_condition
from tests.core.make_block_generator import int_to_public_key

SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
DID_MOD = load_clvm("did_innerpuz.clvm")
NFT_STATE_LAYER_MOD = load_clvm("nft_state_layer.clvm")
STANDARD_PUZZLE_MOD = load_clvm("p2_delegated_puzzle_or_hidden_puzzle.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()

LAUNCHER_ID = Program.to("launcher-id").get_tree_hash()
NFT_METADATA_UPDATER = load_clvm("nft_metadata_updater_default.clvm")


def test_new_nft_ownership_layer() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    my_amount = 1
    destination: Program = puzzle_for_pk(int_to_public_key(2))
    condition_list = [make_create_coin_condition(destination.get_tree_hash(), my_amount, [])]
    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]
    solution = Program.to(
        [
            NFT_STATE_LAYER_MOD_HASH,
            metadata,
            NFT_METADATA_UPDATER.get_tree_hash(),
            innerpuz,
            # below here is the solution
            solution_for_conditions(condition_list),
            my_amount,
            0,
        ]
    )

    cost, res = NFT_STATE_LAYER_MOD.run_with_cost(INFINITE_COST, solution)
    assert res.first().first().as_int() == 73
    assert res.first().rest().first().as_int() == 1
    assert res.rest().rest().first().first().as_int() == 51
    assert (
        res.rest().rest().first().rest().first().as_atom()
        == NFT_STATE_LAYER_MOD.curry(
            NFT_STATE_LAYER_MOD_HASH, metadata, NFT_METADATA_UPDATER.get_tree_hash(), destination
        ).get_tree_hash()
    )


def test_update_metadata() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    my_amount = 1
    destination: Program = puzzle_for_pk(int_to_public_key(2))
    condition_list = [make_create_coin_condition(destination.get_tree_hash(), my_amount, [])]
    condition_list.append([-24, NFT_METADATA_UPDATER, ("mu", "https://url2")])

    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
        ("mu", []),
        ("mh", 0xD4584AD463139FA8C0D9F68F4B59F185),
        ("lu", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("lh", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]

    solution = Program.to(
        [
            NFT_STATE_LAYER_MOD_HASH,
            metadata,
            NFT_METADATA_UPDATER.get_tree_hash(),
            innerpuz,
            # below here is the solution
            solution_for_conditions(condition_list),
            my_amount,
            0,
        ]
    )

    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
        ("mu", ["https://url2"]),
        ("mh", 0xD4584AD463139FA8C0D9F68F4B59F185),
        ("lu", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("lh", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]
    cost, res = NFT_STATE_LAYER_MOD.run_with_cost(INFINITE_COST, solution)
    assert res.first().first().as_int() == 73
    assert res.first().rest().first().as_int() == 1
    assert res.rest().rest().first().first().as_int() == 51
    assert (
        bytes32(res.rest().rest().first().rest().first().as_atom())
        == NFT_STATE_LAYER_MOD.curry(
            NFT_STATE_LAYER_MOD_HASH, metadata, NFT_METADATA_UPDATER.get_tree_hash(), destination
        ).get_tree_hash()
    )
