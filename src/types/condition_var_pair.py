from dataclasses import dataclass
from typing import Optional

from src.types.condition_opcodes import ConditionOpcode


@dataclass(frozen=True)
class ConditionVarPair:
    """
    This structure is used to store parsed CLVM conditions
    Conditions in CLVM have either format of (opcode, var1) or (opcode, var1, var2)
    """

    opcode: ConditionOpcode
    var1: Optional[bytes]
    var2: Optional[bytes]
