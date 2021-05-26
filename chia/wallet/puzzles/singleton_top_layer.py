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
SINGLETON_LAUNCHER = load_clvm('singleton_launcher.clvm')
ESCAPE_VALUE = -113

# Given the parent of the launcher coin, return the launcher coin
def get_launcher_coin_from_parent(coin: Coin) -> Coin:
    return Coin(coin.name(), SINGLETON_LAUNCHER.get_tree_hash(), coin.amount)


# Wrap inner puzzles that are not singleton specific in a program that strips away the "truths" that the top layer tries to pass in
def adapt_inner_to_singleton(inner_puzzle: Program) -> Program:
    return Program.to([2, (1, inner_puzzle), [6, 1]]) #(a (q . inner_puzzle) (r 1))


# Take a coin in the format of p2_delegated_puzzle_or_hidden_puzzle and send it to a new puzzle wrapped by a singleton
def launch_singleton_from_standard_coin(coin: Coin, inner_puzzle: Program, comment: bytes) -> Tuple[Program, CoinSolution]:
    if (coin.amount % 2) == 0:
        raise ValueError("The coin amount cannot be even. Try lowering the amount by one mojo.")
    launcher_coin = get_launcher_coin_from_parent(coin)
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

# API for spending a singleton
def spend_singleton(
        coin: Coin,              # coin being spent
        launcher_id: bytes32,    # launcher_coin.name()
        inner_puzzle: Program,   # inner_puzzle of coin being spent
        parent_coin: Coin,       # parent of the coin being spent
        is_eve: bool,            # is the coin being spent the child of the launcher?
        inner_solution: Program, # solution to inner_puzzle
        parent_innerpuz_hash: bytes32 = None
    ) -> CoinSolution:

    puzzle_reveal = SINGLETON_MOD.curry(SINGLETON_MOD.get_tree_hash(), launcher_id, inner_puzzle)

    if is_eve:
        parent_info = [parent_coin.parent_coin_info, parent_coin.amount]
    else:
        if parent_innerpuz_hash is None:
            raise ValueError("Need a parent inner puzzle for non-eve spends.")
        parent_info = [parent_coin.parent_coin_info, parent_innerpuz_hash, parent_coin.amount]

    solution = Program.to([parent_info, coin.amount, inner_solution])

    return CoinSolution(
        coin,
        puzzle_reveal,
        solution
    )


# Provides a program that outputs a list of conditions that melt the singleton and create a new coin of any kind
def delegated_puzzle_for_melting(new_puzhash: bytes32, new_amount: uint64) -> Program:
    if (new_amount % 2) == 1:
        raise ValueError("The new amount cannot be odd, we need that for the escape.  Try lowering the amount by one mojo.")
    return Program.to((1, [[ConditionOpcode.CREATE_COIN, b'80', ESCAPE_VALUE],[ConditionOpcode.CREATE_COIN, new_puzhash, new_amount]]))
