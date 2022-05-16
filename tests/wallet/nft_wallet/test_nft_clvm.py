from blspy import G1Element
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    solution_for_conditions,
)
from tests.core.make_block_generator import int_to_public_key
from chia.wallet.puzzles.puzzle_utils import (
    make_assert_coin_announcement,
    make_assert_puzzle_announcement,
    make_assert_my_coin_id_condition,
    make_assert_absolute_seconds_exceeds_condition,
    make_create_coin_announcement,
    make_create_puzzle_announcement,
    make_create_coin_condition,
    make_reserve_fee_condition,
)

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

LAUNCHER_ID = Program.to(b"launcher-id").get_tree_hash()
NFT_METADATA_UPDATER_DEFAULT = load_clvm("nft_metadata_updater_default.clvm")
NFT_METADATA_UPDATER_UPDATEABLE = load_clvm("nft_metadata_updater_updateable.clvm")

def test_new_nft_state_layer() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    my_amount = 1
    destination: bytes32 = puzzle_for_pk(int_to_public_key(2))
    condition_list = [make_create_coin_condition(destination.get_tree_hash(), my_amount, [])]
    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]
    solution = Program.to(
        [
            NFT_STATE_LAYER_MOD_HASH,
            metadata,
            NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(),
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
    assert res.rest().rest().first().rest().first().as_atom() == NFT_STATE_LAYER_MOD.curry(NFT_STATE_LAYER_MOD_HASH, metadata, NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(), destination).get_tree_hash()


def test_update_metadata() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    my_amount = 1
    destination: bytes32 = puzzle_for_pk(int_to_public_key(2))
    condition_list = [make_create_coin_condition(destination.get_tree_hash(), my_amount, [])]
    condition_list.append([-24, NFT_METADATA_UPDATER_DEFAULT, "https://www.chia.net/img/branding/chia-logo-2.svg"])
    condition_list.append([-70, NFT_METADATA_UPDATER_DEFAULT, "https://www.chia.net/img/branding/chia-logo-2.svg"])
    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]
    solution = Program.to(
        [
            NFT_STATE_LAYER_MOD_HASH,
            metadata,
            NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(),
            innerpuz,
            # below here is the solution
            solution_for_conditions(condition_list),
            my_amount,
            0,
        ]
    )

    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo-2.svg", "https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]

    cost, res = NFT_STATE_LAYER_MOD.run_with_cost(INFINITE_COST, solution)
    assert len(res.as_python()) == 3  # check that the negative conditions have been filtered out
    assert res.first().first().as_int() == 73
    assert res.first().rest().first().as_int() == 1
    assert res.rest().rest().first().first().as_int() == 51
    assert res.rest().rest().first().rest().first().as_atom() == NFT_STATE_LAYER_MOD.curry(NFT_STATE_LAYER_MOD_HASH, metadata, NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(), destination).get_tree_hash()


def test_update_metadata_updater() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    my_amount = 1
    destination: bytes32 = puzzle_for_pk(int_to_public_key(2))
    condition_list = [make_create_coin_condition(destination.get_tree_hash(), my_amount, [])]
    condition_list.append([-24, NFT_METADATA_UPDATER_UPDATEABLE, ["test", NFT_METADATA_UPDATER_DEFAULT.get_tree_hash()]])
    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]
    solution = Program.to(
        [
            NFT_STATE_LAYER_MOD_HASH,
            metadata,
            NFT_METADATA_UPDATER_UPDATEABLE.get_tree_hash(),
            innerpuz,
            # below here is the solution
            solution_for_conditions(condition_list),
            my_amount,
            0,
        ]
    )

    metadata = [
        ("u", ["test", "https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]

    cost, res = NFT_STATE_LAYER_MOD.run_with_cost(INFINITE_COST, solution)
    assert len(res.as_python()) == 3  # check that the negative conditions have been filtered out
    assert res.first().first().as_int() == 73
    assert res.first().rest().first().as_int() == 1
    assert res.rest().rest().first().first().as_int() == 51
    assert res.rest().rest().first().rest().first().as_atom() == NFT_STATE_LAYER_MOD.curry(NFT_STATE_LAYER_MOD_HASH, metadata, NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(), destination).get_tree_hash()


def test_innerpuz_enforcement_layer() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    my_amount = 1
    destination = int_to_public_key(2)
    new_did = Program.to("test").get_tree_hash()
    # P2_DELEGATED_PUZZLE_OR_HIDDEN_PUZZLE_MOD_HASH
    # NFT_V1_MOD_HASH
    # PUBKEY
    # INNER_PUZZLE  ; returns (new_owner, new_price, new_pk, transfer_program_reveal, transfer_program_solution, Optional[metadata_updater_reveal], Optional[metadata_updater_solution], Conditions)
    # inner_solution
    condition_list = [new_did, 200, destination, ["fake solution"], 0, 0, [[51, 0xcafef00d, 200]]]
    solution = Program.to([
        STANDARD_PUZZLE_MOD.get_tree_hash(),
        NFT_INNER_INNERPUZ.get_tree_hash(),
        pubkey,
        STANDARD_PUZZLE_MOD.curry(pubkey),
        solution_for_conditions(condition_list),
    ])
    cost, res = NFT_INNER_INNERPUZ.run_with_cost(INFINITE_COST, solution)
    assert res.first().first().as_int() == 51
    assert res.first().rest().first().as_atom() == NFT_INNER_INNERPUZ.curry(
        STANDARD_PUZZLE_MOD.get_tree_hash(),
        NFT_INNER_INNERPUZ.get_tree_hash(),
        destination,
        STANDARD_PUZZLE_MOD.curry(destination)
    ).get_tree_hash()


def test_ownership_layer() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    my_amount = 1
    destination = int_to_public_key(2)
    new_did = Program.to("test").get_tree_hash()
    # P2_DELEGATED_PUZZLE_OR_HIDDEN_PUZZLE_MOD_HASH
    # NFT_V1_MOD_HASH
    # PUBKEY
    # INNER_PUZZLE  ; returns (new_owner, new_price, new_pk, transfer_program_reveal, transfer_program_solution, Optional[metadata_updater_reveal], Optional[metadata_updater_solution], Conditions)
    # inner_solution
    condition_list = [new_did, 200, destination, ["fake solution"], 0, 0, [[51, 0xcafef00d, 200]]]
    curried_tp = NFT_TRANSFER_PROGRAM_DEFAULT.curry()
    curried_ownership_layer = NFT_OWNERSHIP_LAYER.curry()
    # breakpoint()
