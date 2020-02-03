from typing import Optional, Tuple, List, Dict

from clvm.subclass_sexp import BaseSExp

from clvm_tools import binutils

from src.types.ConditionVarPair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.types.hashable import Program
from .ConsensusError import Err


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
    d: Dict[ConditionOpcode, List[ConditionVarPair]] = {}
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
    return Program.to([binutils.assemble("#q"), conditions])
