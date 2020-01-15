import enum

import clvm

from clvm_tools import binutils

from .ConsensusError import ConsensusError, Err


class ConditionOpcode(bytes, enum.Enum):
    AGG_SIG = bytes([50])
    CREATE_COIN = bytes([51])
    ASSERT_COIN_CONSUMED = bytes([52])
    ASSERT_MY_COIN_ID = bytes([53])
    ASSERT_MIN_TIME = bytes([54])
    ASSERT_BLOCK_INDEX_EXCEEDS = bytes([55])
    ASSERT_BLOCK_AGE_EXCEEDS = bytes([56])


def parse_sexp_to_condition(sexp):
    assert sexp.listp()
    items = sexp.as_python()
    if not isinstance(items[0], bytes):
        raise ConsensusError(Err.INVALID_CONDITION, items)
    assert isinstance(items[0], bytes)
    opcode = items[0]
    try:
        opcode = ConditionOpcode(items[0])
    except ValueError:
        pass
    return [opcode] + items[1:]


def parse_sexp_to_conditions(sexp):
    return [parse_sexp_to_condition(_) for _ in sexp.as_iter()]


def conditions_by_opcode(conditions):
    opcodes = sorted(set([_[0] for _ in conditions if len(_) > 0]))
    d = {}
    for _ in opcodes:
        d[_] = list()
    for _ in conditions:
        d[_[0]].append(_)
    return d


def parse_sexp_to_conditions_dict(sexp):
    return conditions_by_opcode(parse_sexp_to_conditions(sexp))


def conditions_to_sexp(conditions):
    return clvm.to_sexp_f([binutils.assemble("#q"), conditions])
