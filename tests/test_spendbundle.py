from src.util.hash import std_hash
from src.util.condition_tools import (
    conditions_by_opcode,
    aggsig_in_conditions_dict,
    created_outputs_for_conditions_dict,
    conditions_for_solution,
)
from src.wallet.puzzles import p2_delegated_puzzle
from src.wallet.puzzles.puzzle_utils import make_create_coin_condition
from tests.keys import puzzle_program_for_index


def test_1():
    puzzle_program_0 = puzzle_program_for_index(0)
    puzzle_program_1 = puzzle_program_for_index(1)
    puzzle_program_2 = puzzle_program_for_index(2)

    conditions = [
        make_create_coin_condition(std_hash(bytes(pp)), amount)
        for pp, amount in [(puzzle_program_1, 1000), (puzzle_program_2, 2000),]
    ]

    assert conditions is not None
    puzzle_hash_solution = p2_delegated_puzzle.solution_for_conditions(
        puzzle_program_0, conditions
    )

    error, output_conditions, cost = conditions_for_solution(puzzle_hash_solution)
    assert error is None
    from pprint import pprint

    assert output_conditions is not None
    output_conditions_dict = conditions_by_opcode(output_conditions)
    pprint(output_conditions_dict)
    input_coin_info_hash = bytes([0] * 32)
    additions = created_outputs_for_conditions_dict(
        output_conditions_dict, input_coin_info_hash
    )
    aggsigs = aggsig_in_conditions_dict(output_conditions_dict)
    pprint(aggsigs)
