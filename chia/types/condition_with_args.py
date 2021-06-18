from dataclasses import dataclass
from typing import List

from chia.types.condition_opcodes import ConditionOpcode
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True, eq=False)
@streamable
class ConditionWithArgs(Streamable):
    """
    This structure is used to store parsed CLVM conditions
    Conditions in CLVM have either format of (opcode, var1) or (opcode, var1, var2)
    """

    opcode: ConditionOpcode
    vars: List[bytes]

    def __hash__(self):
        return hash((self.opcode.value, tuple(self.vars)))

    def __eq__(self, rhs):
        if not isinstance(rhs, ConditionWithArgs):
            return False
        return self.opcode == rhs.opcode and self.vars == rhs.vars
