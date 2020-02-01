import enum
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict

import clvm
from clvm.subclass_sexp import BaseSExp

from clvm_tools import binutils

from src.util.streamable import Streamable, streamable
from .ConsensusError import ConsensusError, Err


class ConditionOpcode(bytes, enum.Enum):
    AGG_SIG = bytes([50])
    CREATE_COIN = bytes([51])
    ASSERT_COIN_CONSUMED = bytes([52])
    ASSERT_MY_COIN_ID = bytes([53])
    ASSERT_TIME_EXCEEDS = bytes([54])
    ASSERT_BLOCK_INDEX_EXCEEDS = bytes([55])
    ASSERT_BLOCK_AGE_EXCEEDS = bytes([56])


@dataclass(frozen=True)
class ConditionVarPair():
    """
    This structure is used in the body for the reward and fees genesis coins.
    """
    opcode: ConditionOpcode
    var1: Optional[bytes]
    var2: Optional[bytes]


def parse_sexp_to_condition(sexp: BaseSExp) -> Tuple[Optional[Err], Optional[ConditionVarPair]]:
    if not sexp.listp():
        return Err.SEXP_ERROR, None
    items = sexp.as_python()
    if not isinstance(items[0], bytes):
        return Err.INVALID_CONDITION, None
    opcode = items[0]
    try:
        opcode = ConditionOpcode(items[0])
    except ValueError:
        pass
    if len(items) == 3:
        return None, ConditionVarPair(opcode,  items[1], items[2])
    return None, ConditionVarPair(opcode, items[1], None)


def parse_sexp_to_conditions(sexp: BaseSExp) -> Tuple[Optional[Err], Optional[List[ConditionVarPair]]]:
    results: List[ConditionVarPair] = []
    try:
        for _ in sexp.as_iter():
            error, cvp = parse_sexp_to_condition(_)
            if error:
                return error, None
            results.append(cvp)
    except:
        return Err.INVALID_CONDITION, None
    return None, results


def conditions_by_opcode(conditions: List[ConditionVarPair]) -> Dict[ConditionOpcode, List[ConditionVarPair]]:
    d: Dict[ConditionOpcode: List[ConditionVarPair]] = {}
    for _ in conditions:
        if _.opcode not in d:
            d[_.opcode] = list()
        d[_.opcode].append(_)
    return d


def parse_sexp_to_conditions_dict(sexp: BaseSExp) -> \
        Tuple[Optional[Err], Optional[Dict[ConditionOpcode, List[ConditionVarPair]]]]:
    error, list = parse_sexp_to_conditions(sexp)
    if error:
        return error, None
    return None, conditions_by_opcode(list)


def conditions_to_sexp(conditions):
    return clvm.to_sexp_f([binutils.assemble("#q"), conditions])
