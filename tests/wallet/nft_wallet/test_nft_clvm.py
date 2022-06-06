from chia.types.announcement import Announcement
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions
from chia.wallet.puzzles.puzzle_utils import make_create_coin_condition
from tests.core.make_block_generator import int_to_public_key

SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
LAUNCHER_PUZZLE = load_clvm("singleton_launcher.clvm")
DID_MOD = load_clvm("did_innerpuz.clvm")
NFT_STATE_LAYER_MOD = load_clvm("nft_state_layer.clvm")
NFT_OWNERSHIP_LAYER = load_clvm("nft_ownership_layer.clvm")
NFT_TRANSFER_PROGRAM = load_clvm("nft_ownership_transfer_program_one_way_claim_with_royalties.clvm")
NFT_GRAFTROOT_TRANSFER = load_clvm("nft_graftroot_transfer.clvm")
STANDARD_PUZZLE_MOD = load_clvm("p2_delegated_puzzle_or_hidden_puzzle.clvm")
LAUNCHER_PUZZLE_HASH = LAUNCHER_PUZZLE.get_tree_hash()
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()
OFFER_MOD = load_clvm("settlement_payments.clvm")

LAUNCHER_ID = Program.to(b"launcher-id").get_tree_hash()
NFT_METADATA_UPDATER_DEFAULT = load_clvm("nft_metadata_updater_default.clvm")
NFT_METADATA_UPDATER_UPDATEABLE = load_clvm("nft_metadata_updater_updateable.clvm")


def test_new_nft_state_layer() -> None:
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
            NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(),
            innerpuz,
            # below here is the solution
            solution_for_conditions(condition_list),
            my_amount,
        ]
    )

    cost, res = NFT_STATE_LAYER_MOD.run_with_cost(INFINITE_COST, solution)
    assert res.first().first().as_int() == 73
    assert res.first().rest().first().as_int() == 1
    assert res.rest().rest().first().first().as_int() == 51
    assert (
        res.rest().rest().first().rest().first().as_atom()
        == NFT_STATE_LAYER_MOD.curry(
            NFT_STATE_LAYER_MOD_HASH, metadata, NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(), destination
        ).get_tree_hash()
    )


def test_update_metadata() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    my_amount = 1
    destination: Program = puzzle_for_pk(int_to_public_key(2))
    condition_list = [make_create_coin_condition(destination.get_tree_hash(), my_amount, [])]
    condition_list.append([-24, NFT_METADATA_UPDATER_DEFAULT, ("mu", "https://url2")])

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
            NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(),
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
    assert len(res.as_python()) == 3  # check that the negative conditions have been filtered out
    assert res.first().first().as_int() == 73
    assert res.first().rest().first().as_int() == 1
    assert res.rest().rest().first().first().as_int() == 51
    assert (
        res.rest().rest().first().rest().first().as_atom()
        == NFT_STATE_LAYER_MOD.curry(
            NFT_STATE_LAYER_MOD_HASH, metadata, NFT_METADATA_UPDATER_DEFAULT.get_tree_hash(), destination
        ).get_tree_hash()
    )


def test_transfer_program() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    current_owner = Program.to("current_owner").get_tree_hash()
    new_owner = Program.to("new_owner").get_tree_hash()
    new_inner = Program.to("new_owner_inner").get_tree_hash()
    new_pk = int_to_public_key(2)
    nft_id = Program.to("nft").get_tree_hash()
    SINGLETON_STRUCT = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    curried_tp = NFT_TRANSFER_PROGRAM.curry(
        STANDARD_PUZZLE_MOD.get_tree_hash(),
        SINGLETON_STRUCT,
        innerpuz.get_tree_hash(),
        2000,  # percentage with 2 decimal points 0 - 10000
        OFFER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
    )
    #     Current_Owner
    # conditions
    # (
    #   new_owner
    #   trade_prices_list
    #   (new_did_inner_hash)  ; this is the opaque transfer_program_solution
    # )

    # (CREATE_COIN p2dohp odd_number)
    # (NEW_OWNER_CONDITION new_owner trade_prices_list new_pk transfer_program_solution)
    trade_prices_list = [[200]]
    conditions = Program.to(
        [
            [51, STANDARD_PUZZLE_MOD.curry(new_pk).get_tree_hash(), 1],
            [-10, new_owner, trade_prices_list, new_pk, [new_inner]],
        ]
    )
    solution = Program.to([current_owner, conditions, [new_owner, trade_prices_list, new_pk, [new_inner]]])
    cost, res = curried_tp.run_with_cost(INFINITE_COST, solution)
    assert res.first().as_atom() == new_owner
    assert res.rest().first().as_int() == 0
    conditions = res.rest().rest().first()
    assert conditions.rest().first().first().as_int() == 51
    assert conditions.rest().first().rest().rest().first().as_int() == 1
    assert conditions.rest().rest().rest().first().first().as_int() == 63
    SINGLETON_STRUCT = Program.to((SINGLETON_MOD_HASH, (new_owner, LAUNCHER_PUZZLE_HASH)))
    new_owner_coin_puzhash = SINGLETON_MOD.curry(SINGLETON_STRUCT, "new_owner_inner").get_tree_hash()
    assert (
        conditions.rest().rest().rest().first().rest().first().as_atom()
        == Announcement(new_owner_coin_puzhash, nft_id).name()
    )
    assert conditions.rest().rest().rest().rest().first().first().as_int() == 51
    assert conditions.rest().rest().rest().rest().first().rest().rest().first().as_int() == 40

    conditions = NFT_GRAFTROOT_TRANSFER.curry(
        Program.to([[60, bytes32([0] * 32)]]),
        Program.to(trade_prices_list),
    ).run(Program.to([new_pk, STANDARD_PUZZLE_MOD.curry(new_pk).get_tree_hash(), 1]))
    solution = Program.to([current_owner, conditions, [[], trade_prices_list, new_pk, []]])
    cost, res = curried_tp.run_with_cost(INFINITE_COST, solution)
    assert res.first().as_int() == 0
    assert res.rest().first().as_int() == 0

    # TODO: check for the announcement.  This is broken currently.
    # TODO: Add a test where the inner puzzle tries to create a banned announcement

def test_ownership_layer() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    destination = int_to_public_key(2)
    new_did = Program.to("test").get_tree_hash()
    new_did_inner_hash = Program.to("fake").get_tree_hash()
    old_did = Program.to("test_2").get_tree_hash()
    nft_id = Program.to("nft_id").get_tree_hash()
    trade_prices_list = [[200]]
    SINGLETON_STRUCT = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    curried_tp = NFT_TRANSFER_PROGRAM.curry(
        STANDARD_PUZZLE_MOD.get_tree_hash(),
        SINGLETON_STRUCT,
        innerpuz.get_tree_hash(),
        2000,  # percentage with 2 decimal points 0 - 10000
        OFFER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
    )
    curried_inner = STANDARD_PUZZLE_MOD.curry(pubkey)

    curried_ownership_layer = NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER.get_tree_hash(),
        old_did,
        curried_tp,
        curried_inner,
    )
    condition_list = [
        [
            51,
            STANDARD_PUZZLE_MOD.curry(destination).get_tree_hash(),
            1,
            [STANDARD_PUZZLE_MOD.curry(destination).get_tree_hash()],
        ],
        [-10, new_did, trade_prices_list, destination, [new_did_inner_hash]],
    ]
    solution = Program.to([solution_for_conditions(condition_list)])
    cost, res = curried_ownership_layer.run_with_cost(INFINITE_COST, solution)
    assert res.rest().first().first().as_int() == 51
    assert res.rest().first().rest().rest().first().as_int() == 1
    curried_inner = STANDARD_PUZZLE_MOD.curry(destination)
    curried_ownership_layer = NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER.get_tree_hash(),
        new_did,
        curried_tp,
        curried_inner,
    )
    assert res.rest().first().rest().first().as_atom() == curried_ownership_layer.get_tree_hash()
    assert res.rest().first().rest().rest().rest().first().first().as_atom() == curried_inner.get_tree_hash()
    assert res.rest().rest().rest().rest().first().first().as_int() == 51
    assert res.rest().rest().rest().rest().first().rest().rest().first().as_int() == 40


def test_full_stack() -> None:
    pubkey = int_to_public_key(1)
    innerpuz = puzzle_for_pk(pubkey)
    my_amount = 1
    destination = int_to_public_key(2)
    new_did = Program.to("test").get_tree_hash()
    new_did_inner_hash = Program.to("fake").get_tree_hash()
    old_did = Program.to("test_2").get_tree_hash()
    nft_id = Program.to("nft_id").get_tree_hash()
    trade_prices_list = [[200]]
    SINGLETON_STRUCT = Program.to((SINGLETON_MOD_HASH, (nft_id, LAUNCHER_PUZZLE_HASH)))
    curried_tp = NFT_TRANSFER_PROGRAM.curry(
        STANDARD_PUZZLE_MOD.get_tree_hash(),
        SINGLETON_STRUCT,
        innerpuz.get_tree_hash(),
        2000,  # percentage with 2 decimal points 0 - 10000
        OFFER_MOD.get_tree_hash(),
        CAT_MOD.get_tree_hash(),
    )
    curried_inner = STANDARD_PUZZLE_MOD.curry(pubkey)

    curried_ownership_layer = NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER.get_tree_hash(),
        old_did,
        curried_tp,
        curried_inner,
    )

    metadata = [
        ("u", ["https://www.chia.net/img/branding/chia-logo.svg"]),
        ("h", 0xD4584AD463139FA8C0D9F68F4B59F185),
    ]
    curried_state_layer = NFT_STATE_LAYER_MOD.curry(
        NFT_STATE_LAYER_MOD_HASH,
        metadata,
        NFT_METADATA_UPDATER_UPDATEABLE.get_tree_hash(),
        curried_ownership_layer,
    )

    condition_list = [
        [
            51,
            STANDARD_PUZZLE_MOD.curry(destination).get_tree_hash(),
            1,
            [STANDARD_PUZZLE_MOD.curry(destination).get_tree_hash()],
        ],
        [-10, new_did, trade_prices_list, destination, [new_did_inner_hash]],
    ]
    solution = Program.to(
        [
            [solution_for_conditions(condition_list)],
            my_amount,
        ]
    )
    cost, res = curried_state_layer.run_with_cost(INFINITE_COST, solution)
    assert res.rest().rest().first().first().as_int() == 51
    assert res.rest().rest().first().rest().rest().first().as_int() == 1
    curried_inner = STANDARD_PUZZLE_MOD.curry(destination)
    curried_ownership_layer = NFT_OWNERSHIP_LAYER.curry(
        NFT_OWNERSHIP_LAYER.get_tree_hash(),
        new_did,
        curried_tp,
        curried_inner,
    )
    curried_state_layer = NFT_STATE_LAYER_MOD.curry(
        NFT_STATE_LAYER_MOD_HASH,
        metadata,
        NFT_METADATA_UPDATER_UPDATEABLE.get_tree_hash(),
        curried_ownership_layer,
    )
    assert res.rest().rest().first().rest().first().as_atom() == curried_state_layer.get_tree_hash()
    assert res.rest().rest().first().rest().rest().rest().first().first().as_atom() == curried_inner.get_tree_hash()
