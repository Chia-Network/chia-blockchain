"""
Pay to conditions

In this puzzle program, the solution is ignored. The reveal of the puzzle
returns a fixed list of conditions. This roughly corresponds to OP_SECURETHEBAG
in bitcoin.

This is a pretty useless most of the time. But some (most?) solutions
require a delegated puzzle program, so in those cases, this is just what
the doctor ordered.
"""

from clvm_tools import binutils

from src.types.program import Program


# contract:
# generate puzzle: (() . puzzle_parameters)
# generate solution: (1 . (puzzle_parameters . solution_parameters))
from clvm import run_program


def make_contract():
    """
    Rough source (hasn't been tested):
        (mod (is_solution . parameters)
            (defmacro puzzle conditions (qq (q (unquote conditions))))
            (defmacro solution (conditions . solution_info) (qq (q (unquote (c conditions ())))))
            (if is_solution (solution parameters) (puzzle parameters))
        )
    """
    return binutils.assemble(
        """
    ((c (i (f (a))
        (q (c (c (q #q) (c (f (r (a)))
        (q ()))) (q (())))) (q (c (q #q) (c (r (a)) (q ()))))) (a)))
    """
    )


CONTRACT = make_contract()


def puzzle_for_contract(contract, puzzle_parameters):
    env = Program.to([]).cons(Program.to(puzzle_parameters))
    cost, r = run_program(contract, env)
    return Program.to(r)


def solution_for_contract(contract, puzzle_parameters, solution_parameters):
    cost, r = run_program(
        contract, Program.to((1, (puzzle_parameters, solution_parameters)))
    )
    return r


def puzzle_for_conditions(conditions):
    return puzzle_for_contract(CONTRACT, conditions)


def solution_for_conditions(conditions):
    return solution_for_contract(CONTRACT, conditions, [])
