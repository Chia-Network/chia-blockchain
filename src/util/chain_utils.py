from typing import List

from src.types.announcement import Announcement
from src.types.blockchain_format.coin import Coin
from src.types.blockchain_format.program import Program
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.condition_tools import (
    conditions_dict_for_solution,
    created_announcements_for_conditions_dict,
    created_outputs_for_conditions_dict,
)


def additions_for_solution(coin_name: bytes32, puzzle_reveal: Program, solution: Program) -> List[Coin]:
    """
    Checks the conditions created by CoinSolution and returns the list of all coins created
    """
    err, dic, cost = conditions_dict_for_solution(puzzle_reveal, solution)
    if err or dic is None:
        return []
    return created_outputs_for_conditions_dict(dic, coin_name)


def announcements_for_solution(coin_name: bytes, puzzle_reveal: Program, solution: Program) -> List[Announcement]:
    """
    Checks the conditions created by CoinSolution and returns the list of announcements
    """
    err, dic, cost = conditions_dict_for_solution(puzzle_reveal, solution)
    if err or dic is None:
        return []
    return created_announcements_for_conditions_dict(dic, coin_name)
