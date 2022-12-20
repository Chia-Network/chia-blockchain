from typing import List, Tuple, Dict

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint64
from chia.wallet.lineage_proof import LineageProof

from cic.drivers.merkle_utils import build_merkle_tree
from cic.drivers.prefarm_info import PrefarmInfo
from cic.drivers.singleton import SINGLETON_MOD, SINGLETON_LAUNCHER_HASH, construct_p2_singleton
from cic.load_clvm import load_clvm

P2_MERKLE_MOD = load_clvm("p2_merkle_tree.clsp", package_or_requirement="cic.clsp.drop_coins")
DEFAULT_INNER = Program.to([2, 2, 5])  # (a 2 5)
REKEY_COMPLETION_MOD = load_clvm("rekey_completion.clsp", package_or_requirement="cic.clsp.drop_coins")
REKEY_CLAWBACK_MOD = load_clvm("rekey_clawback.clsp", package_or_requirement="cic.clsp.drop_coins")
ACH_COMPLETION_MOD = load_clvm("ach_completion.clsp", package_or_requirement="cic.clsp.drop_coins")
ACH_CLAWBACK_MOD = load_clvm("ach_clawback.clsp", package_or_requirement="cic.clsp.drop_coins")


############
# REKEYING #
############
def construct_rekey_completion(prefarm_info: PrefarmInfo) -> Program:
    return REKEY_COMPLETION_MOD.curry(
        (SINGLETON_MOD.get_tree_hash(), (prefarm_info.launcher_id, SINGLETON_LAUNCHER_HASH)),  # SINGLETON_STRUCT
        prefarm_info.rekey_clawback_period,
    )


def construct_rekey_clawback() -> Program:
    return REKEY_CLAWBACK_MOD


def calculate_rekey_merkle_tree(prefarm_info: PrefarmInfo) -> Tuple[bytes32, Dict[bytes32, Tuple[int, List[bytes32]]]]:
    return build_merkle_tree(
        [
            construct_rekey_completion(prefarm_info).get_tree_hash(),
            construct_rekey_clawback().get_tree_hash(),
        ]
    )


def construct_rekey_puzzle(prefarm_info: PrefarmInfo) -> Program:
    return P2_MERKLE_MOD.curry(DEFAULT_INNER, calculate_rekey_merkle_tree(prefarm_info)[0])


def curry_rekey_puzzle(
    timelock_multiple: uint8,
    old_prefarm_info: PrefarmInfo,
    new_prefarm_info: PrefarmInfo,
) -> Program:
    return construct_rekey_puzzle(old_prefarm_info).curry(
        [
            new_prefarm_info.puzzle_root,
            old_prefarm_info.puzzle_root,
            timelock_multiple,
        ]
    )


def solve_rekey_completion(prefarm_info: PrefarmInfo, lineage_proof: LineageProof):
    completion_puzzle: Program = construct_rekey_completion(prefarm_info)
    merkle_proofs: Dict[bytes32, Tuple[int, List[bytes32]]] = calculate_rekey_merkle_tree(prefarm_info)[1]
    completion_proof = Program.to(merkle_proofs[completion_puzzle.get_tree_hash()])

    return Program.to(
        [
            completion_puzzle,
            completion_proof,
            [
                lineage_proof.to_program(),
            ],
        ]
    )


def solve_rekey_clawback(
    prefarm_info: PrefarmInfo,
    rekey_ph: bytes32,
    puzzle_reveal: Program,
    proof_of_inclusion: Program,
    solution: Program,
):
    clawback_puzzle: Program = construct_rekey_clawback()
    merkle_proofs: Dict[bytes32, Tuple[int, List[bytes32]]] = calculate_rekey_merkle_tree(prefarm_info)[1]
    clawback_proof = Program.to(merkle_proofs[clawback_puzzle.get_tree_hash()])

    return Program.to(
        [
            clawback_puzzle,
            clawback_proof,
            [
                rekey_ph,
                puzzle_reveal,
                proof_of_inclusion,
                solution,
            ],
        ]
    )


#######
# ACH #
#######
def construct_ach_completion(prefarm_info: PrefarmInfo) -> Program:
    return ACH_COMPLETION_MOD.curry(prefarm_info.payment_clawback_period)


def calculate_ach_clawback_ph(prefarm_info: PrefarmInfo) -> bytes32:
    return construct_p2_singleton(prefarm_info.launcher_id).get_tree_hash()


def construct_ach_clawback(prefarm_info: PrefarmInfo) -> Program:
    return ACH_CLAWBACK_MOD.curry(calculate_ach_clawback_ph(prefarm_info))


def calculate_ach_merkle_tree(prefarm_info: PrefarmInfo) -> Tuple[bytes32, Dict[bytes32, Tuple[int, List[bytes32]]]]:
    return build_merkle_tree(
        [
            construct_ach_completion(prefarm_info).get_tree_hash(),
            construct_ach_clawback(prefarm_info).get_tree_hash(),
        ]
    )


def construct_ach_puzzle(prefarm_info: PrefarmInfo) -> Program:
    return P2_MERKLE_MOD.curry(DEFAULT_INNER, calculate_ach_merkle_tree(prefarm_info)[0])


def curry_ach_puzzle(prefarm_info: PrefarmInfo, p2_puzzle_hash: bytes32) -> Program:
    return construct_ach_puzzle(prefarm_info).curry(
        (
            prefarm_info.puzzle_root,
            p2_puzzle_hash,
        )
    )


def solve_ach_completion(prefarm_info: PrefarmInfo, amount: uint64) -> Program:
    completion_puzzle: Program = construct_ach_completion(prefarm_info)
    merkle_proofs: Dict[bytes32, Tuple[int, List[bytes32]]] = calculate_ach_merkle_tree(prefarm_info)[1]
    completion_proof = Program.to(merkle_proofs[completion_puzzle.get_tree_hash()])

    return Program.to(
        [
            completion_puzzle,
            completion_proof,
            [
                amount,
            ],
        ]
    )


def solve_ach_clawback(
    prefarm_info: PrefarmInfo,
    amount: uint64,
    puzzle_reveal: Program,
    proof_of_inclusion: Program,
    solution: Program,
):
    clawback_puzzle: Program = construct_ach_clawback(prefarm_info)
    merkle_proofs: Dict[bytes32, Tuple[int, List[bytes32]]] = calculate_ach_merkle_tree(prefarm_info)[1]
    clawback_proof = Program.to(merkle_proofs[clawback_puzzle.get_tree_hash()])

    return Program.to(
        [
            clawback_puzzle,
            clawback_proof,
            [
                amount,
                puzzle_reveal,
                proof_of_inclusion,
                solution,
            ],
        ]
    )
