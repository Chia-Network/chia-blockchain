from typing import Tuple

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.coin_solution import CoinSolution
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.util.ints import uint64
from chia.util.hash import std_hash

SINGLETON_MOD = load_clvm('singleton_top_layer.clvm')
ESCAPE_VALUE = -113

def launch_singleton_from_standard_coin(coin: Coin, inner_puzzle: Program, comment: bytes) -> Tuple[Program, CoinSolution]:
    SINGLETON_LAUNCHER = load_clvm('singleton_launcher.clvm')
    launcher_coin = Coin(coin.name(), SINGLETON_LAUNCHER.get_tree_hash(), coin.amount)
    curried_singleton = SINGLETON_MOD.curry(SINGLETON_MOD.get_tree_hash(), launcher_coin.name(), inner_puzzle)
    launcher_solution = Program.to([curried_singleton.get_tree_hash(), coin.amount, comment])
    delegated_puzzle = Program.to((1, [
        [ConditionOpcode.CREATE_COIN, SINGLETON_LAUNCHER.get_tree_hash(), coin.amount],
        [ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, std_hash(launcher_coin.name() + launcher_solution.get_tree_hash())]
    ]))
    launcher_coin_solution = CoinSolution(
        launcher_coin,
        SINGLETON_LAUNCHER,
        launcher_solution
    )
    return delegated_puzzle, launcher_coin_solution


def spend_singleton(coin: Coin, launcher_id: bytes32, inner_puzzle: Program, parent_coin: Coin, is_eve: bool, inner_solution: Program) -> CoinSolution:
    puzzle_reveal = SINGLETON_MOD.curry(SINGLETON_MOD.get_tree_hash(), launcher_id, inner_puzzle)

    if is_eve:
        parent_info = [parent_coin.parent_coin_info, parent_coin.parent_coin_amount]
    else:
        parent_info = [parent_coin.parent_coin_info, parent_coin.puzzle_hash, parent_coin.parent_coin_amount]
    solution = Program.to([parent_info, coin.amount, inner_solution])

    return CoinSolution(
        coin,
        puzzle_reveal,
        solution
    )


def delegated_puzzle_for_melting(new_puzhash: bytes32, new_amount: uint64) -> Program:
    if (new_amount % 2) == 1:
        raise ValueError("The new amount cannot be odd, we need that for the escape.  Try lowering the amount by one mojo.")
    return Program.to((1, [[ConditionOpcode.CREATE_COIN, b'80', ESCAPE_VALUE],[ConditionOpcode.CREATE_COIN, new_puzhash, new_amount]]))
