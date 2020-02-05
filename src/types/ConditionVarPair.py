from dataclasses import dataclass
from typing import Optional

from src.types.condition_opcodes import ConditionOpcode


@dataclass(frozen=True)
class ConditionVarPair:
    """
    This structure is used in the body for the reward and fees genesis coins.
    """

    opcode: ConditionOpcode
    var1: Optional[bytes]
    var2: Optional[bytes]
