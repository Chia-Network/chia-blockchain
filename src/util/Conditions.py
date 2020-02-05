from typing import Optional, Tuple, List, Dict

from clvm.subclass_sexp import BaseSExp

from src.types.ConditionVarPair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from .ConsensusError import Err, ConsensusError


def parse_sexp_to_condition(
    sexp: BaseSExp,
) -> Tuple[Optional[Err], Optional[ConditionVarPair]]:
    """
    Takes a ChiaLisp sexp and returns a ConditionVarPair.
    If it fails, returns an Error
    """
    if not sexp.listp():
        return Err.SEXP_ERROR, None
    items = sexp.as_python()
    if not isinstance(items[0], bytes):
        return Err.INVALID_CONDITION, None
    try:
        opcode = ConditionOpcode(items[0])
    except ValueError:
        return Err.INVALID_CONDITION, None
    if len(items) == 3:
        return None, ConditionVarPair(opcode, items[1], items[2])
    return None, ConditionVarPair(opcode, items[1], None)


def parse_sexp_to_conditions(
    sexp: BaseSExp,
) -> Tuple[Optional[Err], Optional[List[ConditionVarPair]]]:
    """
    Takes a ChiaLisp sexp (list) and returns the list of ConditionVarPairs
    If it fails, returns as Error
    """
    results: List[ConditionVarPair] = []
    try:
        for _ in sexp.as_iter():
            error, cvp = parse_sexp_to_condition(_)
            if error:
                return error, None
            results.append(cvp)  # type: ignore # noqa
    except ConsensusError:
        return Err.INVALID_CONDITION, None
    return None, results


def conditions_by_opcode(
    conditions: List[ConditionVarPair],
) -> Dict[ConditionOpcode, List[ConditionVarPair]]:
    """
    Takes a list of ConditionVarPairs(CVP) and return dictionary of CVPs keyed of their opcode
    """
    d: Dict[ConditionOpcode, List[ConditionVarPair]] = {}
    for _ in conditions:
        if _.opcode not in d:
            d[_.opcode] = list()
        d[_.opcode].append(_)
    return d
