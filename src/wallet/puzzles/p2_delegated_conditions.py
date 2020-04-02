"""
Pay to delegated conditions

In this puzzle program, the solution must be a signed list of conditions, which
is returned literally. The

This is a pretty useless most of the time. But some (most?) solutions
require a delegated puzzle program, so in those cases, this is just what
the doctor ordered.
"""


from clvm_tools import binutils

from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program


def puzzle_for_pk(public_key):
    aggsig = ConditionOpcode.AGG_SIG[0]
    TEMPLATE = f"(c (c (q {aggsig}) (c (q 0x%s) (c (sha256tree (a)) (q ())))) (a))"
    return Program.to(binutils.assemble(TEMPLATE % public_key.hex()))


def solution_for_conditions(puzzle_reveal, conditions):
    return Program.to([puzzle_reveal, conditions])
