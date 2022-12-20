from typing import List, Tuple

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.puzzles.singleton_top_layer import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    P2_SINGLETON_MOD,
    solution_for_singleton,
)

from cic.load_clvm import load_clvm

SINGLETON_MOD = load_clvm("singleton_top_layer_v1_1.clsp", package_or_requirement="cic.clsp.singleton")


solve_singleton = solution_for_singleton


# Return the puzzle reveal of a singleton with specific ID and innerpuz
def construct_singleton(launcher_id: bytes32, inner_puz: Program) -> Program:
    return SINGLETON_MOD.curry(
        (SINGLETON_MOD.get_tree_hash(), (launcher_id, SINGLETON_LAUNCHER_HASH)),
        inner_puz,
    )


def generate_launch_conditions_and_coin_spend(
    coin: Coin,
    inner_puzzle: Program,
    amount: uint64,
) -> Tuple[List[Program], CoinSpend]:
    if (amount % 2) == 0:
        raise ValueError("Coin amount cannot be even. Subtract one mojo.")

    launcher_coin = Coin(coin.name(), SINGLETON_LAUNCHER_HASH, amount)
    curried_singleton: Program = construct_singleton(launcher_coin.name(), inner_puzzle)

    launcher_solution = Program.to(
        [
            curried_singleton.get_tree_hash(),
            amount,
            [],
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

    launcher_coin_spend = CoinSpend(
        launcher_coin,
        SINGLETON_LAUNCHER,
        launcher_solution,
    )

    return conditions, launcher_coin_spend


def construct_p2_singleton(launcher_id: bytes32) -> Program:
    return P2_SINGLETON_MOD.curry(SINGLETON_MOD.get_tree_hash(), launcher_id, SINGLETON_LAUNCHER_HASH)


def solve_p2_singleton(p2_singleton_coin: Coin, singleton_inner_puzhash: bytes32) -> Program:
    return Program.to([singleton_inner_puzhash, p2_singleton_coin.name()])
