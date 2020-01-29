from typing import List


from src.types.hashable import Coin
from src.util.Conditions import ConditionVarPair
from src.util.consensus import conditions_dict_for_solution, created_outputs_for_conditions_dict, \
    aggsig_in_conditions_dict


def additions_for_solution(coin_name, solution) -> List[Coin]:

    err, dic = conditions_dict_for_solution(solution)
    if err:
        return []
    return created_outputs_for_conditions_dict(dic, coin_name)


def aggsigs_for_solution(solution) -> List[ConditionVarPair]:

    err, dic = conditions_dict_for_solution(solution)
    if err:
        return []
    return aggsig_in_conditions_dict(dic)


