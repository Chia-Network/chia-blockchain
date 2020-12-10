from dataclasses import dataclass
from typing import List

from src.types.condition_opcodes import ConditionOpcode


@dataclass(frozen=True)
class ConditionVarPair:
    """
    This structure is used to store parsed CLVM conditions
    Conditions in CLVM have either format of (opcode, var1) or (opcode, var1, var2)
    """

    opcode: ConditionOpcode
    vars: List[bytes]

    def __init__(self, opc: ConditionOpcode, *args):
        i = 0
        var_list = []
        for arg in args:
            if arg is not None:
                assert isinstance(arg, bytes)
                var_list.append(arg)
            i = i + 1
        object.__setattr__(self, "opcode", opc)
        object.__setattr__(self, "vars", var_list)
