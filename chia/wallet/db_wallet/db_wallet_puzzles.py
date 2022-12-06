from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple, Type, TypeVar, Union

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64
from chia.wallet.action_manager.protocols import WalletAction
from chia.wallet.action_manager.wallet_actions import Graftroot
from chia.wallet.nft_wallet.nft_puzzles import NFT_STATE_LAYER_MOD, create_nft_layer_puzzle_with_curry_params
from chia.wallet.puzzle_drivers import Solver, cast_to_int
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.util.merkle_utils import _simplify_merkle_proof

# from chia.types.condition_opcodes import ConditionOpcode
# from chia.wallet.util.merkle_tree import MerkleTree, TreeType

ACS_MU = Program.to(11)  # returns the third argument a.k.a the full solution
ACS_MU_PH = ACS_MU.get_tree_hash()
SINGLETON_TOP_LAYER_MOD = load_clvm_maybe_recompile("singleton_top_layer_v1_1.clvm")
SINGLETON_TOP_LAYER_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
SINGLETON_LAUNCHER = load_clvm_maybe_recompile("singleton_launcher.clvm")
SINGLETON_LAUNCHER_HASH = SINGLETON_LAUNCHER.get_tree_hash()
NFT_STATE_LAYER_MOD_HASH = NFT_STATE_LAYER_MOD.get_tree_hash()
GRAFTROOT_DL_OFFERS = load_clvm_maybe_recompile("graftroot_dl_offers.clvm")
CURRY_DL_GRAFTROOT = load_clvm_maybe_recompile("curry_dl_graftroot.clsp")
P2_PARENT = load_clvm_maybe_recompile("p2_parent.clvm")


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


def match_dl_singleton(puzzle: Program) -> Tuple[bool, Iterator[Program]]:
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


_T_RequireDLInclusion = TypeVar("_T_RequireDLInclusion", bound="RequireDLInclusion")


@dataclass(frozen=True)
class RequireDLInclusion:
    launcher_ids: List[bytes32]
    values_to_prove: List[List[bytes32]]

    @staticmethod
    def name() -> str:
        return "require_dl_inclusion"

    @classmethod
    def from_solver(cls: Type[_T_RequireDLInclusion], solver: Solver) -> _T_RequireDLInclusion:
        return cls(
            [bytes32(launcher_id) for launcher_id in solver["launcher_ids"]],
            [[bytes32(value) for value in values] for values in solver["values_to_prove"]],
        )

    def __post_init__(self) -> None:
        if len(self.launcher_ids) != len(self.values_to_prove):
            raise ValueError("Length mismatch between launcher ids and values to prove")

    def to_solver(self) -> Solver:
        return Solver(
            {
                "type": self.name(),
                "launcher_ids": ["0x" + launcher_id.hex() for launcher_id in self.launcher_ids],
                "values_to_prove": [["0x" + value.hex() for value in values] for values in self.values_to_prove],
            }
        )

    def de_alias(self) -> WalletAction:
        return Graftroot(
            self.construct_puzzle_wrapper(),
            Program.to(
                [
                    4,
                    Program.to(None),
                    [
                        4,
                        Program.to(None),
                        [
                            4,
                            Program.to(None),
                            [
                                4,
                                Program.to(None),
                                [4, 2, None],
                            ],
                        ],
                    ],
                ]
            ),
            Program.to(None),
        )

    def construct_puzzle_wrapper(self) -> Program:
        return CURRY_DL_GRAFTROOT.curry(
            GRAFTROOT_DL_OFFERS,
            [launcher_to_struct(launcher) for launcher in self.launcher_ids],
            [NFT_STATE_LAYER_MOD.get_tree_hash()] * len(self.launcher_ids),
            self.values_to_prove,
        )

    @staticmethod
    def action_name() -> str:
        return str(Graftroot.name())

    @classmethod
    def from_action(cls: Type[_T_RequireDLInclusion], action: WalletAction) -> _T_RequireDLInclusion:
        if action.name() != Graftroot.name():
            raise ValueError("Can only parse a RequireDLInclusion from Graftroot")

        curry_mod, curried_args = action.puzzle_wrapper.uncurry()
        if curry_mod != CURRY_DL_GRAFTROOT or curried_args.first() != GRAFTROOT_DL_OFFERS:
            raise ValueError("The parsed graftroot is not a DL requirement")

        return cls(
            [bytes32(struct.at("rf").as_python()) for struct in curried_args.at("rf").as_iter()],
            [
                [bytes32(value.as_python()) for value in values.as_iter()]
                for values in curried_args.at("rrrf").as_iter()
            ],
        )

    def augment(self, environment: Solver) -> WalletAction:
        if "dl_inclusion_proofs" in environment:
            all_spends: List[CoinSpend] = [
                CoinSpend(
                    Coin(
                        spend["coin"]["parent_coin_info"],
                        spend["coin"]["puzzle_hash"],
                        cast_to_int(spend["coin"]["amount"]),
                    ),
                    spend["puzzle_reveal"],
                    spend["solution"],
                )
                for spend in environment["spends"]
            ]
            # Build a mapping of launcher IDs to their spend information
            singleton_to_innerpuzhashs_and_roots: Dict[bytes32, List[Tuple[bytes32, bytes32]]] = {}
            for spend in all_spends:
                matched, curried_args = match_dl_singleton(spend.puzzle_reveal.to_program())
                if matched:
                    innerpuz, root, id = curried_args
                    singleton_to_innerpuzhashs_and_roots.setdefault(bytes32(id.as_python()), [])
                    singleton_to_innerpuzhashs_and_roots[bytes32(id.as_python())].append(
                        (
                            innerpuz.get_tree_hash(),
                            bytes32(root.as_python()),
                        )
                    )
            # Now find all of the info that we need for the solution
            all_proofs = []
            all_roots = []
            for launcher_id, values in zip(self.launcher_ids, self.values_to_prove):
                acceptable_roots: List[bytes32] = [r for _, r in singleton_to_innerpuzhashs_and_roots[launcher_id]]
                proved_root: Optional[bytes32] = None
                proofs_of_inclusion: List[Program] = []
                while proved_root is None:
                    for value in values:
                        for proof in environment["dl_inclusion_proofs"]:
                            _proof = (proof.first().as_int(), proof.rest().as_python())
                            calculated_root = _simplify_merkle_proof(value, _proof)
                            if calculated_root in acceptable_roots:
                                if proved_root is None:
                                    proved_root = calculated_root
                                elif calculated_root != proved_root:
                                    continue
                                proofs_of_inclusion.append(proof)
                                break
                        else:
                            if proved_root is None:
                                return self  # The proofs of inclusion were not good enough so don't do anything
                            else:
                                acceptable_roots.remove(proved_root)
                                proved_root = None
                                proofs_of_inclusion = []
                                break

                all_proofs.append(proofs_of_inclusion)
                all_roots.append(proved_root)

            potential_inner_puzzles: List[bytes32] = [
                innerpuz
                for launcher_id, expected_root in zip(self.launcher_ids, all_roots)
                for innerpuz, root in singleton_to_innerpuzhashs_and_roots[launcher_id]
                if root == expected_root
            ]
            # This is a hack to fix an edge case where you do a metadata update to the same root then announce it
            # If it causes issues, we should probably inspect the conditions
            if len(potential_inner_puzzles) > len(self.launcher_ids):
                potential_inner_puzzles = [potential_inner_puzzles[-1]]
            return Graftroot(
                self.construct_puzzle_wrapper(),
                # (list proofs_of_inclusion new_metadatas new_metadata_updaters new_inner_puzs inner_solution)
                Program.to(
                    [
                        4,
                        (1, all_proofs),
                        [
                            4,
                            (1, [Program.to([root]) for root in all_roots]),
                            [
                                4,
                                (1, [ACS_MU_PH] * len(self.launcher_ids)),
                                [
                                    4,
                                    (1, potential_inner_puzzles),
                                    [4, 2, None],
                                ],
                            ],
                        ],
                    ]
                ),
                Program.to(None),
            )
