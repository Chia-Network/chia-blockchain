from typing import Dict, Iterable, List

from hsms.streamables import Program


def iter_program(program: Program) -> Iterable[Program]:
    while program.pair:
        yield Program.to(program.pair[0])
        program = program.pair[1]


def conditions_by_opcode(conditions: Program) -> Dict[int, List[Program]]:
    d: Dict[int, List[Program]] = {}
    for _ in iter_program(conditions):
        if _.pair:
            d.setdefault(Program.to(_.pair[0]).as_int(), []).append(_)
    return d
