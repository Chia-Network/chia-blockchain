import clvm

from src.types.hashable import ProgramHash, Program, CoinName
from src.util.ConsensusError import ConsensusError, Err
from src.util.consensus import conditions_dict_for_solution, created_outputs_for_conditions_dict


def name_puzzle_conditions_list(body_program):
    """
    Return a list of tuples of (coin_name, solved_puzzle_hash, conditions_dict)
    """

    try:
        sexp = clvm.eval_f(clvm.eval_f, body_program, [])
    except clvm.EvalError.EvalError:
        breakpoint()
        raise ConsensusError(Err.INVALID_BLOCK_SOLUTION, body_program)

    npc_list = []
    for name_solution in sexp.as_iter():
        _ = name_solution.as_python()
        if len(_) != 2:
            raise ConsensusError(Err.INVALID_COIN_SOLUTION, name_solution)
        if not isinstance(_[0], bytes) or len(_[0]) != 32:
            raise ConsensusError(Err.INVALID_COIN_SOLUTION, name_solution)
        coin_name = CoinName(_[0])
        if not isinstance(_[1], list) or len(_[1]) != 2:
            raise ConsensusError(Err.INVALID_COIN_SOLUTION, name_solution)
        puzzle_solution_program = name_solution.rest().first()
        puzzle_program = puzzle_solution_program.first()
        puzzle_hash = ProgramHash(Program(puzzle_program))
        try:
            conditions_dict = conditions_dict_for_solution(puzzle_solution_program)
        except clvm.EvalError.EvalError:
            raise ConsensusError(Err.INVALID_COIN_SOLUTION, coin_name)

        npc_list.append((coin_name, puzzle_hash, conditions_dict))

    return npc_list


def additions_for_solution(coin_name, solution):
    return created_outputs_for_conditions_dict(
        conditions_dict_for_solution(solution), coin_name)


def additions_for_body(body):
    yield body.coinbase_coin
    yield body.fees_coin
    for (coin_name, solution, conditions_dict) in name_puzzle_conditions_list(body.solution_program):
        for _ in created_outputs_for_conditions_dict(conditions_dict, coin_name):
            yield _


def removals_for_body(body):
    return [
        coin_name for (coin_name, solution, conditions_dict) in
        name_puzzle_conditions_list(body.solution_program)]
