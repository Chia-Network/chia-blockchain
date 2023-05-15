from __future__ import annotations

from typing import Dict, List, Tuple

from clvm.casts import int_from_bytes

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.util.errors import ConsensusError, Err
from chia.util.ints import uint64

# TODO: review each `assert` and consider replacing with explicit checks
#       since asserts can be stripped with python `-OO` flag


def parse_sexp_to_condition(sexp: Program) -> ConditionWithArgs:
    """
    Takes a ChiaLisp sexp and returns a ConditionWithArgs.
    Raises an ConsensusError if it fails.
    """
    first = sexp.pair
    if first is None:
        raise ConsensusError(Err.INVALID_CONDITION, ["first is None"])
    op = first[0].atom
    if op is None or len(op) != 1:
        raise ConsensusError(Err.INVALID_CONDITION, ["invalid op"])

    # since the ConditionWithArgs only has atoms as the args, we can't parse
    # hints and memos with this function. We just exit the loop if we encounter
    # a pair instead of an atom
    vars: List[bytes] = []
    for arg in Program(first[1]).as_iter():
        a = arg.atom
        if a is None:
            break
        vars.append(a)
        # no condition (currently) has more than 3 arguments. Additional
        # arguments are allowed but ignored
        if len(vars) > 3:
            break

    return ConditionWithArgs(ConditionOpcode(op), vars)


def parse_sexp_to_conditions(sexp: Program) -> List[ConditionWithArgs]:
    """
    Takes a ChiaLisp sexp (list) and returns the list of ConditionWithArgss
    Raises an ConsensusError if it fails.
    """
    return [parse_sexp_to_condition(s) for s in sexp.as_iter()]


def pkm_pairs(
    conditions: SpendBundleConditions, additional_data: bytes, *, soft_fork: bool
) -> Tuple[List[bytes48], List[bytes]]:
    ret: Tuple[List[bytes48], List[bytes]] = ([], [])

    for pk, msg in conditions.agg_sig_unsafe:
        ret[0].append(bytes48(pk))
        ret[1].append(msg)
        if soft_fork and msg.endswith(additional_data):
            raise ConsensusError(Err.INVALID_CONDITION)

    for spend in conditions.spends:
        for pk, msg in spend.agg_sig_me:
            ret[0].append(bytes48(pk))
            ret[1].append(msg + spend.coin_id + additional_data)
    return ret


def pkm_pairs_for_conditions_dict(
    conditions_dict: Dict[ConditionOpcode, List[ConditionWithArgs]], coin_name: bytes32, additional_data: bytes
) -> List[Tuple[bytes48, bytes]]:
    assert coin_name is not None
    ret: List[Tuple[bytes48, bytes]] = []

    for cwa in conditions_dict.get(ConditionOpcode.AGG_SIG_UNSAFE, []):
        assert len(cwa.vars) == 2
        assert len(cwa.vars[0]) == 48 and len(cwa.vars[1]) <= 1024
        assert cwa.vars[0] is not None and cwa.vars[1] is not None
        if cwa.vars[1].endswith(additional_data):
            raise ConsensusError(Err.INVALID_CONDITION)
        ret.append((bytes48(cwa.vars[0]), cwa.vars[1]))

    for cwa in conditions_dict.get(ConditionOpcode.AGG_SIG_ME, []):
        assert len(cwa.vars) == 2
        assert len(cwa.vars[0]) == 48 and len(cwa.vars[1]) <= 1024
        assert cwa.vars[0] is not None and cwa.vars[1] is not None
        ret.append((bytes48(cwa.vars[0]), cwa.vars[1] + coin_name + additional_data))
    return ret


def created_outputs_for_conditions_dict(
    conditions_dict: Dict[ConditionOpcode, List[ConditionWithArgs]],
    input_coin_name: bytes32,
) -> List[Coin]:
    output_coins = []
    for cvp in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
        puzzle_hash, amount_bin = cvp.vars[0], cvp.vars[1]
        amount = int_from_bytes(amount_bin)
        coin = Coin(input_coin_name, bytes32(puzzle_hash), uint64(amount))
        output_coins.append(coin)
    return output_coins


def conditions_dict_for_solution(
    puzzle_reveal: SerializedProgram,
    solution: SerializedProgram,
    max_cost: int,
) -> Dict[ConditionOpcode, List[ConditionWithArgs]]:
    conditions_dict: Dict[ConditionOpcode, List[ConditionWithArgs]] = {}
    for cvp in conditions_for_solution(puzzle_reveal, solution, max_cost):
        conditions_dict.setdefault(cvp.opcode, list()).append(cvp)
    return conditions_dict


def conditions_for_solution(
    puzzle_reveal: SerializedProgram,
    solution: SerializedProgram,
    max_cost: int,
) -> List[ConditionWithArgs]:
    # get the standard script for a puzzle hash and feed in the solution
    try:
        cost, r = puzzle_reveal.run_with_cost(max_cost, solution)
        return parse_sexp_to_conditions(r)
    except Program.EvalError as e:
        raise ConsensusError(Err.SEXP_ERROR, [str(e)]) from e
