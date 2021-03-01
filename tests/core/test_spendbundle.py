from src.types.blockchain_format.program import Program
from src.util.condition_tools import (
    aggsig_in_conditions_dict,
    conditions_by_opcode,
    conditions_for_solution,
    created_outputs_for_conditions_dict,
)
from src.util.hash import std_hash
from src.util.ints import uint32
from src.wallet.puzzles import p2_delegated_puzzle
from src.wallet.puzzles.puzzle_utils import make_create_coin_condition
from tests.keys import puzzle_program_for_index


def test_1():
    puzzle_program_1 = puzzle_program_for_index(uint32(1))
    puzzle_program_2 = puzzle_program_for_index(uint32(2))

    conditions = Program.to(
        [
            make_create_coin_condition(std_hash(bytes(pp)), amount)
            for pp, amount in [(puzzle_program_1, 1000), (puzzle_program_2, 2000)]
        ]
    )

    assert conditions is not None
    puzzle_reveal = p2_delegated_puzzle.puzzle_reveal_for_conditions(conditions)
    solution = p2_delegated_puzzle.solution_for_conditions(conditions)

    error, output_conditions, cost = conditions_for_solution(puzzle_reveal, solution)
    assert error is None
    from pprint import pprint

    assert output_conditions is not None
    output_conditions_dict = conditions_by_opcode(output_conditions)
    pprint(output_conditions_dict)
    input_coin_info_hash = bytes([0] * 32)
    created_outputs_for_conditions_dict(output_conditions_dict, input_coin_info_hash)
    aggsigs = aggsig_in_conditions_dict(output_conditions_dict)
    pprint(aggsigs)
