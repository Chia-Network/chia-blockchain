from __future__ import annotations

from dataclasses import dataclass
from typing import List

from chia.types.condition_opcodes import ConditionOpcode


@dataclass(frozen=True)
class ConditionWithArgs:
    """
    This structure is used to store parsed CLVM conditions
    Conditions in CLVM have either format of (opcode, var1) or (opcode, var1, var2)
    """

    opcode: ConditionOpcode
    vars: List[bytes]
