from __future__ import annotations

from typing import Iterator, List, Tuple, Union

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64
from chia.wallet.nft_wallet.nft_puzzles import NFT_STATE_LAYER_MOD, create_nft_layer_puzzle_with_curry_params
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile

# from chia.types.condition_opcodes import ConditionOpcode
# from chia.wallet.util.merkle_tree import MerkleTree, TreeType

ACS_MU = Program.to(11)  # returns the third argument a.k.a the full solution
ACS_MU_PH = ACS_MU.get_tree_hash()
SINGLETON_TOP_LAYER_MOD = load_clvm_maybe_recompile("singleton_top_layer_v1_1.clsp")
SINGLETON_LAUNCHER = load_clvm_maybe_recompile("singleton_launcher.clsp")
GRAFTROOT_DL_OFFERS = load_clvm_maybe_recompile(
    "graftroot_dl_offers.clsp", package_or_requirement="chia.data_layer.puzzles"
)
P2_PARENT = load_clvm_maybe_recompile("p2_parent.clsp")


def create_host_fullpuz(innerpuz: Union[Program, bytes32], current_root: bytes32, genesis_id: bytes32) -> Program:
    db_layer = create_host_layer_puzzle(innerpuz, current_root)
    mod_hash = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
    singleton_struct = Program.to((mod_hash, (genesis_id, SINGLETON_LAUNCHER.get_tree_hash())))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, db_layer)


def create_host_layer_puzzle(innerpuz: Union[Program, bytes32], current_root: bytes32) -> Program:
    # some hard coded metadata formatting and metadata updater for now
    return create_nft_layer_puzzle_with_curry_params(
        Program.to((current_root, None)),
        ACS_MU_PH,
        # TODO: the nft driver doesn't like the Union yet, but changing that is out of scope for me rn - Quex
        innerpuz,  # type: ignore
    )


def match_dl_singleton(puzzle: Union[Program, SerializedProgram]) -> Tuple[bool, Iterator[Program]]:
    """
    Given a puzzle test if it's a CAT and, if it is, return the curried arguments
    """
    mod, singleton_curried_args = puzzle.uncurry()
    if mod == SINGLETON_TOP_LAYER_MOD:
        mod, dl_curried_args = singleton_curried_args.at("rf").uncurry()
        if mod == NFT_STATE_LAYER_MOD and dl_curried_args.at("rrf") == ACS_MU_PH:
            launcher_id = singleton_curried_args.at("frf")
            root = dl_curried_args.at("rff")
            innerpuz = dl_curried_args.at("rrrf")
            return True, iter((innerpuz, root, launcher_id))

    return False, iter(())


def launch_solution_to_singleton_info(launch_solution: Program) -> Tuple[bytes32, uint64, bytes32, bytes32]:
    solution = launch_solution.as_python()
    try:
        full_puzzle_hash = bytes32(solution[0])
        amount = uint64(int.from_bytes(solution[1], "big"))
        root = bytes32(solution[2][0])
        inner_puzzle_hash = bytes32(solution[2][1])
    except (IndexError, TypeError):
        raise ValueError("Launcher is not a data layer launcher")

    return full_puzzle_hash, amount, root, inner_puzzle_hash


def launcher_to_struct(launcher_id: bytes32) -> Program:
    struct: Program = Program.to(
        (SINGLETON_TOP_LAYER_MOD.get_tree_hash(), (launcher_id, SINGLETON_LAUNCHER.get_tree_hash()))
    )
    return struct


def create_graftroot_offer_puz(
    launcher_ids: List[bytes32], values_to_prove: List[List[bytes32]], inner_puzzle: Program
) -> Program:
    return GRAFTROOT_DL_OFFERS.curry(
        inner_puzzle,
        [launcher_to_struct(launcher) for launcher in launcher_ids],
        [NFT_STATE_LAYER_MOD.get_tree_hash()] * len(launcher_ids),
        values_to_prove,
    )


def create_mirror_puzzle() -> Program:
    return P2_PARENT.curry(Program.to(1))


MIRROR_PUZZLE_HASH = create_mirror_puzzle().get_tree_hash()


def get_mirror_info(parent_puzzle: Program, parent_solution: Program) -> Tuple[bytes32, List[bytes]]:
    conditions = parent_puzzle.run(parent_solution)
    for condition in conditions.as_iter():
        if (
            condition.first().as_python() == ConditionOpcode.CREATE_COIN
            and condition.at("rf").as_python() == create_mirror_puzzle().get_tree_hash()
        ):
            memos: List[bytes] = condition.at("rrrf").as_python()
            launcher_id = bytes32(memos[0])
            return launcher_id, [url for url in memos[1:]]
    raise ValueError("The provided puzzle and solution do not create a mirror coin")
