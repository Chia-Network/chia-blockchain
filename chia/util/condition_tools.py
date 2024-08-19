from __future__ import annotations

from functools import lru_cache
from typing import Callable, Dict, List, Tuple, Union

from chia_rs import G1Element
from clvm.casts import int_from_bytes, int_to_bytes

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.spend_bundle_conditions import SpendBundleConditions, SpendConditions
from chia.util.errors import ConsensusError, Err
from chia.util.hash import std_hash
from chia.util.ints import uint64


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


@lru_cache
def agg_sig_additional_data(agg_sig_data: bytes) -> Dict[ConditionOpcode, bytes]:
    ret: Dict[ConditionOpcode, bytes] = {}
    for code in [
        ConditionOpcode.AGG_SIG_PARENT,
        ConditionOpcode.AGG_SIG_PUZZLE,
        ConditionOpcode.AGG_SIG_AMOUNT,
        ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
        ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
        ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
    ]:
        ret[code] = std_hash(agg_sig_data + code)

    ret[ConditionOpcode.AGG_SIG_ME] = agg_sig_data
    return ret


def make_aggsig_final_message(
    opcode: ConditionOpcode,
    msg: bytes,
    spend_conditions: Union[Coin, SpendConditions],
    agg_sig_additional_data: Dict[ConditionOpcode, bytes],
) -> bytes:
    if isinstance(spend_conditions, Coin):
        coin = spend_conditions
    elif isinstance(spend_conditions, SpendConditions):
        coin = Coin(spend_conditions.parent_id, spend_conditions.puzzle_hash, uint64(spend_conditions.coin_amount))
    else:
        raise ValueError(f"Expected Coin or Spend, got {type(spend_conditions)}")  # pragma: no cover

    COIN_TO_ADDENDUM_F_LOOKUP: Dict[ConditionOpcode, Callable[[Coin], bytes]] = {
        ConditionOpcode.AGG_SIG_PARENT: lambda coin: coin.parent_coin_info,
        ConditionOpcode.AGG_SIG_PUZZLE: lambda coin: coin.puzzle_hash,
        ConditionOpcode.AGG_SIG_AMOUNT: lambda coin: int_to_bytes(coin.amount),
        ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT: lambda coin: coin.puzzle_hash + int_to_bytes(coin.amount),
        ConditionOpcode.AGG_SIG_PARENT_AMOUNT: lambda coin: coin.parent_coin_info + int_to_bytes(coin.amount),
        ConditionOpcode.AGG_SIG_PARENT_PUZZLE: lambda coin: coin.parent_coin_info + coin.puzzle_hash,
        ConditionOpcode.AGG_SIG_ME: lambda coin: coin.name(),
    }
    addendum = COIN_TO_ADDENDUM_F_LOOKUP[opcode](coin)
    return msg + addendum + agg_sig_additional_data[opcode]


def pkm_pairs(conditions: SpendBundleConditions, additional_data: bytes) -> Tuple[List[G1Element], List[bytes]]:
    ret: Tuple[List[G1Element], List[bytes]] = ([], [])

    data = agg_sig_additional_data(additional_data)

    for pk, msg in conditions.agg_sig_unsafe:
        ret[0].append(pk)
        ret[1].append(msg)

    for spend in conditions.spends:
        condition_items_pairs = [
            (ConditionOpcode.AGG_SIG_PARENT, spend.agg_sig_parent),
            (ConditionOpcode.AGG_SIG_PUZZLE, spend.agg_sig_puzzle),
            (ConditionOpcode.AGG_SIG_AMOUNT, spend.agg_sig_amount),
            (ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT, spend.agg_sig_puzzle_amount),
            (ConditionOpcode.AGG_SIG_PARENT_AMOUNT, spend.agg_sig_parent_amount),
            (ConditionOpcode.AGG_SIG_PARENT_PUZZLE, spend.agg_sig_parent_puzzle),
            (ConditionOpcode.AGG_SIG_ME, spend.agg_sig_me),
        ]
        for condition, items in condition_items_pairs:
            for pk, msg in items:
                ret[0].append(pk)
                ret[1].append(make_aggsig_final_message(condition, msg, spend, data))

    return ret


def validate_cwa(cwa: ConditionWithArgs) -> None:
    if (
        len(cwa.vars) != 2
        or len(cwa.vars[0]) != 48
        or len(cwa.vars[1]) > 1024
        or cwa.vars[0] is None
        or cwa.vars[1] is None
    ):
        raise ConsensusError(Err.INVALID_CONDITION)


def pkm_pairs_for_conditions_dict(
    conditions_dict: Dict[ConditionOpcode, List[ConditionWithArgs]],
    coin: Coin,
    additional_data: bytes,
) -> List[Tuple[G1Element, bytes]]:
    ret: List[Tuple[G1Element, bytes]] = []

    data = agg_sig_additional_data(additional_data)

    for cwa in conditions_dict.get(ConditionOpcode.AGG_SIG_UNSAFE, []):
        validate_cwa(cwa)
        for disallowed in data.values():
            if cwa.vars[1].endswith(disallowed):
                raise ConsensusError(Err.INVALID_CONDITION)
        ret.append((G1Element.from_bytes(cwa.vars[0]), cwa.vars[1]))

    for opcode in [
        ConditionOpcode.AGG_SIG_PARENT,
        ConditionOpcode.AGG_SIG_PUZZLE,
        ConditionOpcode.AGG_SIG_AMOUNT,
        ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
        ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
        ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
        ConditionOpcode.AGG_SIG_ME,
    ]:
        for cwa in conditions_dict.get(opcode, []):
            validate_cwa(cwa)
            ret.append((G1Element.from_bytes(cwa.vars[0]), make_aggsig_final_message(opcode, cwa.vars[1], coin, data)))

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
    puzzle_reveal: Union[Program, SerializedProgram], solution: Union[Program, SerializedProgram], max_cost: int
) -> Dict[ConditionOpcode, List[ConditionWithArgs]]:
    conditions_dict: Dict[ConditionOpcode, List[ConditionWithArgs]] = {}
    for cvp in conditions_for_solution(puzzle_reveal, solution, max_cost):
        conditions_dict.setdefault(cvp.opcode, list()).append(cvp)
    return conditions_dict


def conditions_for_solution(
    puzzle_reveal: Union[Program, SerializedProgram], solution: Union[Program, SerializedProgram], max_cost: int
) -> List[ConditionWithArgs]:
    # get the standard script for a puzzle hash and feed in the solution
    try:
        cost, r = puzzle_reveal.run_with_cost(max_cost, solution)
        return parse_sexp_to_conditions(r)
    except Program.EvalError as e:
        raise ConsensusError(Err.SEXP_ERROR, [str(e)]) from e
