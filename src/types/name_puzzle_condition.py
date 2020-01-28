from dataclasses import dataclass
from typing import Dict, List

from src.types.sized_bytes import bytes32
from src.util.Conditions import ConditionVarPair, ConditionOpcode


@dataclass(frozen=True)
class NPC:
    coin_name: bytes32
    puzzle_hash: bytes32
    condition_dict: Dict[ConditionOpcode, List[ConditionVarPair]]