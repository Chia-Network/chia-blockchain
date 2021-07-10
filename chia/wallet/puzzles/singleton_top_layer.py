from typing import List, Tuple

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.coin_solution import CoinSolution
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.lineage_proof import LineageProof
from chia.util.ints import uint64
from chia.util.hash import std_hash

SINGLETON_MOD = load_clvm("singleton_top_layer.clvm")
SINGLETON_MOD_HASH = SINGLETON_MOD.get_tree_hash()
P2_SINGLETON_MOD = load_clvm("p2_singleton.clvm")
P2_SINGLETON_OR_DELAYED_MOD = load_clvm("p2_singleton_or_delayed_puzhash.clvm")
SINGLETON_LAUNCHER = load_clvm("singleton_launcher.clvm")
SINGLETON_LAUNCHER_HASH = SINGLETON_LAUNCHER.get_tree_hash()
ESCAPE_VALUE = -113
MELT_CONDITION = [ConditionOpcode.CREATE_COIN, 0, ESCAPE_VALUE]


# Given the parent and amount of the launcher coin, return the launcher coin
def generate_launcher_coin(coin: Coin, amount: uint64) -> Coin:
    return Coin(coin.name(), SINGLETON_LAUNCHER_HASH, amount)


# Wrap inner puzzles that are not singleton specific to strip away "truths"
def adapt_inner_to_singleton(inner_puzzle: Program) -> Program:
    # (a (q . inner_puzzle) (r 1))
    return Program.to([2, (1, inner_puzzle), [6, 1]])


# Take standard coin and amount -> launch conditions & launcher coin solution
def launch_conditions_and_coinsol(
    coin: Coin,
    inner_puzzle: Program,
    comment: List[Tuple[str, str]],
    amount: uint64,
) -> Tuple[List[Program], CoinSolution]:
    if (amount % 2) == 0:
        raise ValueError("Coin amount cannot be even. Subtract one mojo.")

    launcher_coin = generate_launcher_coin(coin, amount)
    curried_singleton = SINGLETON_MOD.curry(
        (SINGLETON_MOD_HASH, (launcher_coin.name(), SINGLETON_LAUNCHER_HASH)),
        inner_puzzle,
    )

    launcher_solution = Program.to(
        [
            curried_singleton.get_tree_hash(),
            amount,
            comment,
        ]
    )
    create_launcher = Program.to(
        [
            ConditionOpcode.CREATE_COIN,
            SINGLETON_LAUNCHER_HASH,
            amount,
        ],
    )
    assert_launcher_announcement = Program.to(
        [
            ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
            std_hash(launcher_coin.name() + launcher_solution.get_tree_hash()),
        ],
    )

    conditions = [create_launcher, assert_launcher_announcement]

    launcher_coin_solution = CoinSolution(
        launcher_coin,
        SINGLETON_LAUNCHER,
        launcher_solution,
    )

    return conditions, launcher_coin_solution


# Take a coin solution, return a lineage proof for their child to use in spends
def lineage_proof_for_coinsol(coin_solution: CoinSolution) -> LineageProof:
    parent_name = coin_solution.coin.parent_coin_info

    inner_puzzle_hash = None
    if coin_solution.coin.puzzle_hash != SINGLETON_LAUNCHER_HASH:
        full_puzzle = Program.from_bytes(bytes(coin_solution.puzzle_reveal))
        r = full_puzzle.uncurry()
        if r is not None:
            _, args = r
            _, inner_puzzle = list(args.as_iter())
            inner_puzzle_hash = inner_puzzle.get_tree_hash()

    amount = coin_solution.coin.amount

    return LineageProof(
        parent_name,
        inner_puzzle_hash,
        amount,
    )


# Return the puzzle reveal of a singleton with specific ID and innerpuz
def puzzle_for_singleton(launcher_id: bytes32, inner_puz: Program) -> Program:
    return SINGLETON_MOD.curry(
        (SINGLETON_MOD_HASH, (launcher_id, SINGLETON_LAUNCHER_HASH)),
        inner_puz,
    )


# Return a solution to spend a singleton
def solution_for_singleton(
    lineage_proof: LineageProof,
    amount: uint64,
    inner_solution: Program,
) -> Program:
    if lineage_proof.inner_puzzle_hash is None:
        parent_info = [
            lineage_proof.parent_name,
            lineage_proof.amount,
        ]
    else:
        parent_info = [
            lineage_proof.parent_name,
            lineage_proof.inner_puzzle_hash,
            lineage_proof.amount,
        ]

    return Program.to([parent_info, amount, inner_solution])


# Create a coin that a singleton can claim
def pay_to_singleton_puzzle(launcher_id: bytes32) -> Program:
    return P2_SINGLETON_MOD.curry(SINGLETON_MOD_HASH, launcher_id, SINGLETON_LAUNCHER_HASH)


# Create a coin that a singleton can claim or that can be sent to another puzzle after a specified time
def pay_to_singleton_or_delay_puzzle(launcher_id: bytes32, delay_time: uint64, delay_ph: bytes32) -> Program:
    return P2_SINGLETON_OR_DELAYED_MOD.curry(
        SINGLETON_MOD_HASH,
        launcher_id,
        SINGLETON_LAUNCHER_HASH,
        delay_time,
        delay_ph,
    )


# Solution for EITHER p2_singleton or the claiming spend case for p2_singleton_or_delayed_puzhash
def solution_for_p2_singleton(p2_singleton_coin: Coin, singleton_inner_puzhash: bytes32) -> Program:
    return Program.to([singleton_inner_puzhash, p2_singleton_coin.name()])


# Solution for the delayed spend case for p2_singleton_or_delayed_puzhash
def solution_for_p2_delayed_puzzle(output_amount: uint64) -> Program:
    return Program.to([output_amount, []])


# Get announcement conditions for singleton solution and full CoinSolution for the claimed coin
def claim_p2_singleton(
    p2_singleton_coin: Coin,
    singleton_inner_puzhash: bytes32,
    launcher_id: bytes32,
) -> Tuple[Program, Program, CoinSolution]:
    assertion = Program.to([ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, std_hash(p2_singleton_coin.name() + b"$")])
    announcement = Program.to([ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, p2_singleton_coin.name()])
    claim_coinsol = CoinSolution(
        p2_singleton_coin,
        pay_to_singleton_puzzle(launcher_id),
        solution_for_p2_singleton(p2_singleton_coin, singleton_inner_puzhash),
    )
    return assertion, announcement, claim_coinsol


# Get the CoinSolution for spending to a delayed puzzle
def spend_to_delayed_puzzle(
    p2_singleton_coin: Coin,
    output_amount: uint64,
    launcher_id: bytes32,
    delay_time: uint64,
    delay_ph: bytes32,
) -> CoinSolution:
    claim_coinsol = CoinSolution(
        p2_singleton_coin,
        pay_to_singleton_or_delay_puzzle(launcher_id, delay_time, delay_ph),
        solution_for_p2_delayed_puzzle(output_amount),
    )
    return claim_coinsol
