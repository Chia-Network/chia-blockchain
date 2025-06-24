from typing import Union

from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.wallet.program import Program
from chia_rs import CoinSpend

from chia.types.blockchain_format.coin import Coin

def make_spend(
    coin: Coin,
    puzzle_reveal: Union[Program, SerializedProgram],
    solution: Union[Program, SerializedProgram],
) -> CoinSpend:
    pr: SerializedProgram
    sol: SerializedProgram
    if isinstance(puzzle_reveal, SerializedProgram):
        pr = puzzle_reveal
    elif isinstance(puzzle_reveal, Program):
        pr = puzzle_reveal.to_serialized()
    else:
        raise ValueError("Only [SerializedProgram, Program] supported for puzzle reveal")
    if isinstance(solution, SerializedProgram):
        sol = solution
    elif isinstance(solution, Program):
        sol = solution.to_serialized()
    else:
        raise ValueError("Only [SerializedProgram, Program] supported for solution")

    return CoinSpend(coin, pr, sol)