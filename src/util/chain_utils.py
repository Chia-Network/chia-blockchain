from typing import List


from src.types.hashable import Coin
from src.util.consensus import conditions_dict_for_solution, created_outputs_for_conditions_dict



def additions_for_solution(coin_name, solution) -> List[Coin]:
    return created_outputs_for_conditions_dict(
        conditions_dict_for_solution(solution), coin_name)


