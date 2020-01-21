from typing import List, Tuple, Optional, Dict

import clvm

from src.types.hashable import BLSSignature, Coin
from src.util.ConsensusError import Err

from .Conditions import conditions_by_opcode, parse_sexp_to_conditions, ConditionOpcode, ConditionVarPair


def conditions_for_solution(solution_program, eval=clvm.eval_f) -> Tuple[Optional[Err], Optional[List[ConditionVarPair]]]:
    # get the standard script for a puzzle hash and feed in the solution
    args = clvm.to_sexp_f(solution_program)
    try:
        puzzle_sexp = args.first()
        solution_sexp = args.rest().first()
        r = eval(eval, puzzle_sexp, solution_sexp)
        error, result = parse_sexp_to_conditions(r)
        return error, result
    except clvm.EvalError.EvalError:
        return Err.SEXP_ERROR, None


def conditions_dict_for_solution(solution) -> Tuple[Optional[Err], Optional[Dict[ConditionOpcode, List[ConditionVarPair]]]]:
    error, result = conditions_for_solution(solution)
    if error:
        return error, None
    return None, conditions_by_opcode(result)


def hash_key_pairs_for_solution(solution) -> Tuple[Optional[Err], List[bytes]]:
    error, result = conditions_dict_for_solution(solution)
    if error:
        return error, []
    return None, hash_key_pairs_for_conditions_dict(result)


def validate_spend_bundle_signature(spend_bundle) -> bool:
    hash_key_pairs = []
    for coin_solution in spend_bundle.coin_solutions:
        hash_key_pairs += hash_key_pairs_for_solution(coin_solution.solution)
    return spend_bundle.aggregated_signature.validate(hash_key_pairs)


def created_outputs_for_conditions_dict(conditions_dict, input_coin_name) -> List[Coin]:
    output_coins = []
    for _ in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
        # TODO: check condition very carefully
        # (ensure there are the correct number and type of parameters)
        # maybe write a type-checking framework for conditions
        # and don't just fail with asserts
        opcode, puzzle_hash, amount_bin = _.opcode, _.var1, _.var2
        amount = clvm.casts.int_from_bytes(amount_bin)
        coin = Coin(input_coin_name, puzzle_hash, amount)
        output_coins.append(coin)
    return output_coins


def aggsig_in_conditions_dict(conditions_dict):
    agg_sig_conditions = []
    for _ in conditions_dict.get(ConditionOpcode.AGG_SIG, []):
        agg_sig_conditions.append(_)
    return agg_sig_conditions


def hash_key_pairs_for_conditions_dict(conditions_dict: Dict[ConditionOpcode, ConditionVarPair]) -> List[bytes]:
    pairs: bytes = []
    for cvp in conditions_dict.get(ConditionOpcode.AGG_SIG, []):
        # TODO: check types
        # assert len(_) == 3
        pairs.append(BLSSignature.AGGSIGPair(cvp.var1, cvp.var2))
    return pairs
