from typing import List, Tuple, Optional, Dict

import blspy
import clvm
from clvm.EvalError import EvalError
from clvm.casts import int_from_bytes

from src.types.ConditionVarPair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.types.hashable.BLSSignature import BLSSignature, BLSPublicKey
from src.types.hashable.Coin import Coin
from src.types.hashable.Program import Program
from src.types.sized_bytes import bytes32
from src.util.ConsensusError import Err

from .Conditions import parse_sexp_to_conditions, conditions_by_opcode


def conditions_for_solution(
    solution_program, run_program=clvm.run_program
) -> Tuple[Optional[Err], Optional[List[ConditionVarPair]]]:
    # get the standard script for a puzzle hash and feed in the solution
    args = Program.to(solution_program)
    try:
        puzzle_sexp = args.first()
        solution_sexp = args.rest().first()
        cost, r = run_program(puzzle_sexp, solution_sexp)
        error, result = parse_sexp_to_conditions(r)
        return error, result
    except EvalError:
        return Err.SEXP_ERROR, None


def conditions_dict_for_solution(
    solution,
) -> Tuple[Optional[Err], Optional[Dict[ConditionOpcode, List[ConditionVarPair]]]]:
    error, result = conditions_for_solution(solution)
    if error or result is None:
        return error, None
    return None, conditions_by_opcode(result)


def hash_key_pairs_for_solution(
    solution,
) -> Tuple[Optional[Err], List[BLSSignature.AGGSIGPair]]:
    error, result = conditions_dict_for_solution(solution)
    if error or result is None:
        return error, []
    return None, hash_key_pairs_for_conditions_dict(result)


def created_outputs_for_conditions_dict(
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]],
    input_coin_name: bytes32,
) -> List[Coin]:
    output_coins = []
    for _ in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
        # TODO: check condition very carefully
        # (ensure there are the correct number and type of parameters)
        # maybe write a type-checking framework for conditions
        # and don't just fail with asserts
        _, puzzle_hash, amount_bin = _.opcode, _.var1, _.var2
        amount = int_from_bytes(amount_bin)
        coin = Coin(input_coin_name, puzzle_hash, amount)
        output_coins.append(coin)
    return output_coins


def aggsig_in_conditions_dict(
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]]
) -> List[ConditionVarPair]:
    agg_sig_conditions = []
    for _ in conditions_dict.get(ConditionOpcode.AGG_SIG, []):
        agg_sig_conditions.append(_)
    return agg_sig_conditions


def hash_key_pairs_for_conditions_dict(
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]]
) -> List[BLSSignature.AGGSIGPair]:
    pairs: List[BLSSignature.AGGSIGPair] = []
    for cvp in conditions_dict.get(ConditionOpcode.AGG_SIG, []):
        # TODO: check types
        # assert len(_) == 3
        blspubkey: BLSPublicKey = BLSPublicKey(cvp.var1)
        message: bytes32 = bytes32(blspy.Util.hash256(cvp.var2))
        pairs.append(BLSSignature.AGGSIGPair(blspubkey, message))
    return pairs
