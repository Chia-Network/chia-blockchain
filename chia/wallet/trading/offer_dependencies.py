from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.cat_wallet.cat_utils import CAT_MOD
from chia.wallet.db_wallet.db_wallet_puzzles import create_graftroot_offer_puz, GRAFTROOT_DL_OFFERS
from chia.wallet.nft_wallet.nft_puzzles import NFT_STATE_LAYER_MOD, NFT_OWNERSHIP_LAYER
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import Solver
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_MOD
from chia.wallet.trading import Offer
from chia.wallet.puzzles.puzzle_utils import make_assert_puzzle_announcement

ADD_CONDITIONS = load_clvm("add_conditions.clsp")
ADD_ANNOUNCEMENT = load_clvm("add_wrapped_announcement.clsp")
CAT_WRAPPER = load_clvm("cat_wrapper.clsp").curry(CAT_MOD.get_tree_hash())
SINGLETON_WRAPPER = load_clvm("singleton_wrapper.clsp").curry(SINGLETON_MOD.get_tree_hash())
METADATA_WRAPPER = load_clvm("metadata_wrapper.clsp").curry(NFT_STATE_LAYER_MOD.get_tree_hash())
OWNERSHIP_WRAPPER = load_clvm("ownership_wrapper.clsp").curry(NFT_OWNERSHIP_LAYER.get_tree_hash())

@dataclass(frozen=True)
class GroupLookup:
    groups: List[Tuple[Any, ...]]

    def __getitem__(self, item: Any) -> Any:
        for group in groups:
            if item in group:
                return group
        raise KeyError(f"{item}")


REQUESTED_PAYMENT_PUZZLES = GroupLookup(
    [
        (AssetType.CAT, CAT_WRAPPER, ["asset_id"]),
        (AssetType.SINGLETON, SINGLETON_WRAPPER, ["launcher_id", "launcher_ph"]),
        (AssetType.METADATA, METADATA_WRAPPER, ["metadata", "metadata_updater_hash"]),
        (AssetType.OWNERSHIP, OWNERSHIP_WRAPPER, ["owner", "transfer_program"]),
    ]
)


@dataclass(frozen=True)
class OfferDependency:
    nonce: Optional[bytes32]


@dataclass(frozen=True)
class Conditions(OfferDependency):
    conditions: List[Program]

    def apply(self, delegated_puzzle: Program, delegated_solution: Program, solver: Solver = Solver({})) -> Tuple[Program, Program]:
        return ADD_CONDITIONS.curry(conditions, delegated_puzzle), Program.to([delegated_solution])

    @classmethod
    def from_puzzle(cls, mod: Program, curried_args: Program) -> Tuple["Conditions", Program]:
        conditions, delegated_puzzle = curried_args.as_iter()
        return cls(None, list(conditions.as_iter())), delegated_puzzle

    def parse_solution(self, delegated_solution: Program) -> Tuple[Solver, Program]:
        return Solver({}), delegated_solution.first()


@dataclass(frozen=True)
class RequestedPayment(OfferDependency):
    asset_types: List[Solver]
    payments: List[Payment]

    def apply(self, delegated_puzzle: Program, delegated_solution: Program, solver: Solver = Solver({})) -> Tuple[Program, Program]:
        if "asset_types" in solver:
            solver_types = solver["asset_types"]
        else:
            solver["asset_types"] = [{"type": a["type"] for a in self.asset_types}]

        wrappers: List[Program] = []
        committed_args_list: List[Program] = []
        solved_args_list: List[Program] = []
        for fixed_typ, solved_typ in zip(self.asset_types, solver_types):
            if fixed_typ["type"] != solved_type["type"]:
                raise ValueError("Got an unclear solution for requested payment dependency")

            committed_args: List[Any] = []
            solved_args: List[Any] = []
            _, wrapper, properties = REQUESTED_PAYMENT_PUZZLES[AssetType(fixed_typ["type"])]
            wrappers.append(wrapper)

            for prop in properties:
                if prop in fixed_typ:
                    if prop in solved_typ:
                        raise ValueError(f"Received a commitment and solution for argument {prop}")
                    else:
                        committed_args.append(fixed_typ[prop])
                else:
                    committed_args.append("missing")
                if prop in solved_typ:
                    solved_args.append(solved_typ[prop])
                else:
                    solved_args.append(None)

            committed_args_list.append(Program.to(committed_args))
            solved_args_list.append(Program.to(solved_args))

        return (
            ADD_ANNOUNCEMENT.curry(
                wrappers,
                committed_args_list,
                OFFER_MOD_HASH,
                Program.to((self.nonce, [p.as_condition_args() for p in self.payments])),
                delegated_puzzle,
            ),
            Program.to([solved_args_list, delegated_solution]),
        )

    @classmethod
    def from_puzzle(cls, mod: Program, curried_args: Program) -> Tuple["RequestedPayment", Program]:
        asset_types: List[Solver] = []

        wrappers, committed_args_list, _, payments, inner_puzzle = curried_args.as_iter()
        for wrapper in wrappers.as_iter():
            typ, _, props = REQUESTED_PAYMENT_PUZZLES[wrapper]
            asset_type = {"type": typ.value}
            type_args = {prop: disassemble(arg) for prop, arg in zip(props, committed_args_list.as_iter()) if arg != Program.to("missing")}
            asset_type.update(type_args)
            asset_types.append(Solver(asset_type))

        nonce: Optional[bytes32] = Program.to(None) if payments.first() == Program.to(None) else bytes32(payments.first().as_python())
        payments: List[Payment] = [Payment.from_condition(p) for p in payments.rest().as_iter()]

        return cls(nonce, asset_types, payments)

    def parse_solution(self, delegated_solution: Program) -> Tuple[Solver, Program]:
        solved_args_list: Program = delegated_solution.first()
        inner_solution: Program = delegated_solution.rest().first()

        asset_types: List[Solver] = []
        for fixed_args, solved_args in zip(self.asset_types, solved_args_list.as_iter()):
            asset_type: Dict[str, Any] = {"type": fixed_args["type"]}
            _, _, props = REQUESTED_PAYMENT_PUZZLES[fixed_args["type"]]
            for prop, solved_value in zip(props, solved_args.as_iter()):
                if prop in fixed_args:
                    continue
                else:
                    asset_type[prop] = disassemble(solved_value)
            asset_types.append(Solver(asset_type))

        return Solver({"asset_types": asset_types}), inner_solution


@dataclass(frozen=True)
class DLDataInclusion(OfferDependency):
    launcher_ids: List[bytes32]
    values_to_prove: List[List[bytes32]]

    def apply(self, delegated_puzzle: Program, delegated_solution: Program, solver: Solver = Solver({})) -> Tuple[Program, Program]:
        new_delegated_puzzle: Program = create_graftroot_offer_puz(
            self.launcher_ids,
            self.values_to_prove,
            delegated_puzzle,
        )
        if "dl_dependencies_info" in solver:
            proofs: List[List[Optional[Tuple[int, List[bytes32]]]]] = []
            roots: List[Optional[bytes32]] = []
            innerpuzs: List[Optional[bytes32]] = []
            for launcher, values in zip(self.launcher_ids, self.values_to_prove):
                launcher_proofs: List[Optional[Tuple[int, List[bytes32]]]] = []
                root: Optional[bytes32] = None
                innerpuz: Optional[bytes32] = None
                for dep_info in solver["dl_dependencies_info"]:
                    if dep_info["launcher_id"] == launcher:
                        for value in values:
                            for proof_of_inclusion in dep_info["proofs_of_inclusion"]:
                                proof: Tuple[int, List[bytes32]] = (proof_of_inclusion[1], proof_of_inclusion[2])
                                new_root: bytes32 = proof_of_inclusion[0]
                                if root is not None and new_root != root:
                                    raise ValueError(f"Received two conflicting new roots for launcher_id {launcher}")
                                new_innerpuz = dep_info["inner_puzzle_hash"]
                                if innerpuz is not None and new_innerpuz != innerpuz:
                                    raise ValueError(f"Received two conflicting new innerpuzs for launcher_id {launcher}")
                                if _simplify_merkle_proof(value, proof) == root:
                                    launcher_proofs.append(proof)
                                    break
                            else:
                                launcher_proofs.append(None)

                proofs.append(launcher_proofs)
                roots.append(root)
                innerpuzs.append(innerpuz)

            new_delegated_solution: Program = Program.to(
                [
                    proofs,
                    [Program.to([root]) for root in roots],
                    [ACS_MU_PH],
                    innerpuzs,
                    delegated_solution,
                ]
            )
        else:
            new_delegated_solution: Program = Program.to(
                [
                    [None] * len(self.launcher_ids),
                    [None] * len(self.launcher_ids),
                    [None] * len(self.launcher_ids),
                    [None] * len(self.launcher_ids),
                    delegated_solution,
                ]
            )

        return new_delegated_puzzle, new_delegated_solution

    @classmethod
    def from_puzzle(cls, mod: Program, curried_args: Program) -> Tuple["DLDataInclusion", Program]:
        inner_puzzle, structs, _, values_to_prove = curried_args.as_iter()
        launcher_ids: List[bytes32] = []
        values_to_prove: List[List[bytes32]] = []
        for struct, values in zip(structs, values_to_prove):
            launcher_ids.append(bytes32(struct.as_python()))
            values_to_prove.append(list(values.as_python()))

        return cls(None, launcher_ids, values_to_prove)

    def parse_solution(self, delegated_solution: Program) -> Tuple[Solver, Program]:
        proofs, roots, _, innerpuzs, inner_solution = delegated_solution.as_iter()

        dl_dependencies_info: List[Dict[str, Any]] = []
        for launcher_id, launcher_proofs, root, innerpuz in zip(self.launcher_ids, proofs.as_iter(), roots.as_iter(), innerpuzs.as_iter()):
            dl_dependencies_info.append({
                "launcher_id": "0x" + launcher_id.hex(),
                "proofs_of_inclusion": [["0x" + root.hex(), str(int_from_bytes(proof[0].as_python())), *["0x" + sib.hex() for sib in proof[1:]]] for proof in launcher_proofs],
                "inner_puzzle_hash": "0x" + innerpuz.hex(),
            })

        return Solver({"dl_dependencies_info": dl_dependencies_info}), inner_solution


DEPENDENCY_WRAPPERS = GroupLookup(
    [
        (ADD_CONDITIONS, Conditions),
        (ADD_ANNOUNCEMENT, RequestedPayment),
        (GRAFTROOT_DL_OFFERS, DLDataInclusion),
    ]
)