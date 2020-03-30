from typing import List

from src.types.coin import Coin
from src.util.condition_tools import (
    created_outputs_for_conditions_dict,
    conditions_dict_for_solution,
)


def additions_for_solution(coin_name, solution) -> List[Coin]:
    """
    Checks the conditions created by CoinSolution and returns the list of all coins created
    """
    err, dic, cost = conditions_dict_for_solution(solution)
    if err or dic is None:
        return []
    return created_outputs_for_conditions_dict(dic, coin_name)
