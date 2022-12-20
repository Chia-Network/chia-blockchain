from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8

from cic.drivers.drop_coins import (
    P2_MERKLE_MOD,
    construct_rekey_puzzle,
    construct_ach_puzzle,
    calculate_ach_clawback_ph,
)
from cic.drivers.prefarm_info import PrefarmInfo
from cic.load_clvm import load_clvm

FILTER_ONLY_REKEY_MOD = load_clvm("only_rekey.clsp", package_or_requirement="cic.clsp.filters")
FILTER_REKEY_AND_PAYMENT_MOD = load_clvm("rekey_and_payment.clsp", package_or_requirement="cic.clsp.filters")


def construct_payment_and_rekey_filter(
    prefarm_info: PrefarmInfo,
    puzzle_root: bytes32,
    rekey_timelock: uint8,
) -> Program:
    return P2_MERKLE_MOD.curry(
        FILTER_REKEY_AND_PAYMENT_MOD.curry(
            (
                (
                    construct_rekey_puzzle(prefarm_info).get_tree_hash(),
                    rekey_timelock,
                ),
                (
                    construct_ach_puzzle(prefarm_info).get_tree_hash(),
                    calculate_ach_clawback_ph(prefarm_info),
                ),
            ),
        ),
        puzzle_root,
        [],
    )


def construct_rekey_filter(
    prefarm_info: PrefarmInfo,
    puzzle_root: bytes32,
    rekey_timelock: uint8,
) -> Program:
    return P2_MERKLE_MOD.curry(
        FILTER_ONLY_REKEY_MOD.curry(
            (
                construct_rekey_puzzle(prefarm_info).get_tree_hash(),
                rekey_timelock,
            ),
        ),
        puzzle_root,
        [],
    )


def solve_filter_for_payment(
    puzzle_reveal: Program,
    proof_of_inclusion: Program,
    puzzle_solution: Program,
    puzzle_root: bytes32,
    p2_ph: bytes32,
):
    return Program.to(
        [
            puzzle_reveal,
            proof_of_inclusion,
            [
                puzzle_solution,
                (puzzle_root, p2_ph),
            ],
        ]
    )


def solve_filter_for_rekey(
    puzzle_reveal: Program,
    proof_of_inclusion: Program,
    puzzle_solution: Program,
    old_puzzle_root: bytes32,
    new_puzzle_root: bytes32,
    timelock: uint8,
):
    return Program.to(
        [
            puzzle_reveal,
            proof_of_inclusion,
            [
                puzzle_solution,
                [new_puzzle_root, old_puzzle_root, timelock],
            ],
        ]
    )
