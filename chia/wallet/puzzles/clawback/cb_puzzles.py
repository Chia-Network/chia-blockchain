from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from chia_rs.chia_rs import Coin
from clvm.casts import int_from_bytes

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import solution_for_conditions
from chia.wallet.util.merkle_utils import build_merkle_tree

CB_MOD = load_clvm("cb_outer.clsp", package_or_requirement="chia.wallet.puzzles.clawback", include_standard_libraries=True)
CB_MOD_HASH = CB_MOD.get_tree_hash()
ACH_CLAWBACK_MOD = load_clvm("ach_clawback.clsp", package_or_requirement="chia.wallet.puzzles.clawback", include_standard_libraries=True)
ACH_CLAWBACK_MOD_HASH = ACH_CLAWBACK_MOD.get_tree_hash()
ACH_COMPLETION_MOD = load_clvm("ach_completion.clsp", package_or_requirement="chia.wallet.puzzles.clawback", include_standard_libraries=True)
ACH_COMPLETION_MOD_HASH = ACH_COMPLETION_MOD.get_tree_hash()
P2_MERKLE_MOD = load_clvm("p2_merkle_tree.clsp", package_or_requirement="chia.wallet.puzzles.clawback", include_standard_libraries=True)
P2_MERKLE_MOD_HASH = P2_MERKLE_MOD.get_tree_hash()

VALIDATOR_MOD = load_clvm("validator.clsp", package_or_requirement="chia.wallet.puzzles.clawback", include_standard_libraries=True)
VALIDATOR_MOD_HASH = VALIDATOR_MOD.get_tree_hash()
P2_MERKLE_VALIDATOR_MOD = load_clvm("p2_merkle_validator.clsp", package_or_requirement="chia.wallet.puzzles.clawback", include_standard_libraries=True)


@streamable
@dataclass(frozen=True)
class ClawbackInfo(Streamable):
    timelock: uint32
    inner_puzzle: Program

    def curry_params(self) -> List[Any]:
        return [
            VALIDATOR_MOD_HASH,
            P2_MERKLE_VALIDATOR_MOD,
            ACH_CLAWBACK_MOD_HASH,
            ACH_COMPLETION_MOD_HASH,
            P2_MERKLE_MOD_HASH,
            self.timelock,
            self.inner_puzzle,
        ]

    def puzzle_and_curry_params(self) -> Program:
        return Program.to([[P2_MERKLE_VALIDATOR_MOD, self.curry_params()], [self.inner_puzzle, []]])

    def outer_puzzle(self) -> Program:
        return VALIDATOR_MOD.curry(self.puzzle_and_curry_params())

    def puzzle_hash(self) -> bytes32:
        return self.outer_puzzle().get_tree_hash()


def generate_claim_spend_bundle(merkle_coin: Coin, metadata: Dict[str, Any]) -> CoinSpend:
    claim_puz = ACH_COMPLETION_MOD.curry(metadata["time_lock"], metadata["target_puzhash"])
    claim_sol = solve_claim_puzzle(merkle_coin.amount)
    claw_puz = ACH_CLAWBACK_MOD.curry(metadata["cb_puzhash"], Program.fromhex(metadata["sender_inner_puzzle"]))
    merkle_tree = build_merkle_tree([claw_puz.get_tree_hash(), claim_puz.get_tree_hash()])
    claim_proof = Program.to(merkle_tree[1][claim_puz.get_tree_hash()])
    p2_merkle_puz = P2_MERKLE_MOD.curry(merkle_tree[0])
    p2_merkle_claim_sol = Program.to([claim_puz, claim_proof, claim_sol])
    return CoinSpend(merkle_coin, p2_merkle_puz, p2_merkle_claim_sol)


def get_cb_puzzle_hash(clawback_info: ClawbackInfo) -> bytes32:
    puz = clawback_info.outer_puzzle()
    return puz.get_tree_hash()


def solve_cb_outer_with_conds(clawback_info: ClawbackInfo, conditions: List[Any]) -> Program:
    morphed_conds = []
    solution_data = []
    total_amount = 0
    for cond in conditions:
        if cond[0] == 51:
            new_cond = [51, construct_p2_merkle_puzzle(clawback_info, cond[1]).get_tree_hash(), cond[2]]
            solution_data.append(cond[1])
            total_amount += cond[2]
            if len(cond) == 4:
                new_cond.append([cond[3]])
            morphed_conds.append(new_cond)
        else:
            morphed_conds.append(cond)

    morphed_conds.append([73, total_amount])
    inner_solution = solution_for_conditions(morphed_conds)
    validator_solution = Program.to([[solution_data, inner_solution]])
    return validator_solution


def solve_cb_outer_puzzle(
    clawback_info: ClawbackInfo, primaries: List[Dict[str, Any]], change_amount: uint64, fee: uint64 = uint64(0)
) -> Program:
    conditions = [
        [51, construct_p2_merkle_puzzle(clawback_info, primary["puzzle_hash"]).get_tree_hash(), primary["amount"]]
        for primary in primaries
    ]
    if change_amount > 0:
        conditions.append([51, clawback_info.puzzle_hash(), change_amount])
    if fee > 0:
        conditions.append([52, fee])
    conditions.append([73, change_amount + fee + sum([primary["amount"] for primary in primaries])])
    inner_solution = solution_for_conditions(conditions)

    solution_data = [primary["puzzle_hash"] for primary in primaries]
    solution_data.append(clawback_info.puzzle_hash())
    validator_solution = Program.to([[solution_data, inner_solution]])
    return validator_solution


def construct_claim_puzzle(clawback_info: ClawbackInfo, target_ph: bytes32) -> Program:
    return ACH_COMPLETION_MOD.curry(clawback_info.timelock, target_ph)


def calculate_clawback_ph(clawback_info: ClawbackInfo) -> bytes32:
    return clawback_info.outer_puzzle().get_tree_hash()


def construct_clawback_puzzle(clawback_info: ClawbackInfo) -> Program:
    return ACH_CLAWBACK_MOD.curry(clawback_info.outer_puzzle().get_tree_hash(), clawback_info.inner_puzzle)


def calculate_merkle_tree(
    clawback_info: ClawbackInfo, target_ph: bytes32
) -> Tuple[bytes32, Dict[bytes32, Tuple[int, List[bytes32]]]]:
    return build_merkle_tree(
        [
            construct_clawback_puzzle(clawback_info).get_tree_hash(),
            construct_claim_puzzle(clawback_info, target_ph).get_tree_hash(),
        ]
    )


def construct_p2_merkle_puzzle(clawback_info: ClawbackInfo, target_ph: bytes32) -> Program:
    return P2_MERKLE_MOD.curry(calculate_merkle_tree(clawback_info, target_ph)[0])


def solve_claim_puzzle(amount: uint64, fee: uint64 = uint64(0)) -> Program:
    return Program.to([amount - fee, fee])


def solve_claw_puzzle(clawback_info: ClawbackInfo, primary: Dict[str, Any], fee: uint64 = uint64(0)) -> Program:
    conditions = [[51, primary["puzzle_hash"], primary["amount"]]]
    if fee > 0:
        conditions.append([52, fee])
    inner_solution = solution_for_conditions(conditions)
    return Program.to([inner_solution])


def solve_p2_merkle_claim(
    timelock: uint32,
    amount: uint64,
    target_ph: bytes32,
    cb_puzzle_hash: bytes32,
    sender_inner_puzzle: Program,
    fee: uint64 = uint64(0),
) -> Tuple[Program, Program]:
    claim_puz = ACH_COMPLETION_MOD.curry(timelock, target_ph)
    claim_sol = solve_claim_puzzle(amount, fee)
    claw_puz = ACH_CLAWBACK_MOD.curry(cb_puzzle_hash, sender_inner_puzzle)
    merkle_tree = build_merkle_tree([claw_puz.get_tree_hash(), claim_puz.get_tree_hash()])
    claim_proof = Program.to(merkle_tree[1][claim_puz.get_tree_hash()])
    p2_merkle_puz = P2_MERKLE_MOD.curry(merkle_tree[0])
    p2_merkle_claim_sol = Program.to([claim_puz, claim_proof, claim_sol])
    return p2_merkle_puz, p2_merkle_claim_sol


def uncurry_clawback(puzzle: Program) -> Optional[Tuple[uint32, Program]]:
    try:
        uncurried = puzzle.uncurry()[1]
        curried_vals = uncurried.at("ffrf").as_python()
        assert len(curried_vals) == 7
        timelock = uint32(int_from_bytes(curried_vals[-2]))
        sender_inner_puzzle = uncurried.at("ffrfrrrrrrf")
        return timelock, sender_inner_puzzle
    except Exception:
        return None


def solve_p2_merkle_claw(
    clawback_info: ClawbackInfo, primary: Dict[str, Any], target_ph: bytes32, fee: uint64 = uint64(0)
) -> Program:
    claw_puz = construct_clawback_puzzle(clawback_info)
    claw_sol = solve_claw_puzzle(clawback_info, primary, fee)
    claw_puz.run(claw_sol)
    merkle_tree = calculate_merkle_tree(clawback_info, target_ph)
    claw_proof = Program.to(merkle_tree[1][claw_puz.get_tree_hash()])
    return Program.to([claw_puz, claw_proof, claw_sol])
