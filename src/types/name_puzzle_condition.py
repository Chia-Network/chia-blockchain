from dataclasses import dataclass
from typing import Dict, List, Tuple

from src.types.condition_var_pair import ConditionVarPair
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.condition_tools import ConditionOpcode
from src.util.streamable import streamable, Streamable


@dataclass(frozen=True)
@streamable
class NPC(Streamable):
    coin_name: bytes32
    puzzle_hash: bytes32
    conditions: List[Tuple[ConditionOpcode, List[ConditionVarPair]]]

    @property
    def condition_dict(self):
        d: Dict[ConditionOpcode, List[ConditionVarPair]] = {}
        for opcode, l in self.conditions:
            d[opcode] = l
        return d
