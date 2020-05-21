from typing import Optional, Tuple, List, Dict

import blspy
import clvm
from clvm.EvalError import EvalError
from clvm.casts import int_from_bytes
from clvm.subclass_sexp import BaseSExp

from src.types.condition_var_pair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.types.BLSSignature import BLSSignature, BLSPublicKey
from src.types.coin import Coin
from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.errors import Err, ConsensusError


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
        opcode = ConditionOpcode.UNKNOWN
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
    cvp: ConditionVarPair
    for cvp in conditions:
        if cvp.opcode not in d:
            d[cvp.opcode] = list()
        d[cvp.opcode].append(cvp)
    return d


def hash_key_pairs_for_conditions_dict(
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]],
    coin_name: bytes32 = None,
) -> List[BLSSignature.PkMessagePair]:
    pairs: List[BLSSignature.PkMessagePair] = []
    for cvp in conditions_dict.get(ConditionOpcode.AGG_SIG, []):
        # TODO: check types
        # assert len(_) == 3
        blspubkey: BLSPublicKey = BLSPublicKey(cvp.var1)
        message: bytes32 = cvp.var2
        pairs.append(BLSSignature.PkMessagePair(blspubkey, message))
    if coin_name is not None:
        for cvp in conditions_dict.get(ConditionOpcode.AGG_SIG_ME, []):
            aggsigme_blspubkey: BLSPublicKey = BLSPublicKey(cvp.var1)
            aggsigme_message: bytes32 = bytes32(
                blspy.Util.hash256(cvp.var2 + coin_name)
            )
            pairs.append(
                BLSSignature.PkMessagePair(aggsigme_blspubkey, aggsigme_message)
            )
    return pairs


def aggsig_in_conditions_dict(
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]]
) -> List[ConditionVarPair]:
    agg_sig_conditions = []
    for _ in conditions_dict.get(ConditionOpcode.AGG_SIG, []):
        agg_sig_conditions.append(_)
    return agg_sig_conditions


def created_outputs_for_conditions_dict(
    conditions_dict: Dict[ConditionOpcode, List[ConditionVarPair]],
    input_coin_name: bytes32,
) -> List[Coin]:
    output_coins = []
    for cvp in conditions_dict.get(ConditionOpcode.CREATE_COIN, []):
        # TODO: check condition very carefully
        # (ensure there are the correct number and type of parameters)
        # maybe write a type-checking framework for conditions
        # and don't just fail with asserts
        puzzle_hash, amount_bin = cvp.var1, cvp.var2
        amount = int_from_bytes(amount_bin)
        coin = Coin(input_coin_name, puzzle_hash, amount)
        output_coins.append(coin)
    return output_coins


def conditions_dict_for_solution(
    solution,
) -> Tuple[
    Optional[Err], Optional[Dict[ConditionOpcode, List[ConditionVarPair]]], uint64
]:
    error, result, cost = conditions_for_solution(solution)
    if error or result is None:
        return error, None, uint64(0)
    return None, conditions_by_opcode(result), cost


def conditions_for_solution(
    solution_program, run_program=clvm.run_program
) -> Tuple[Optional[Err], Optional[List[ConditionVarPair]], uint64]:
    # get the standard script for a puzzle hash and feed in the solution
    args = Program.to(solution_program)
    try:
        puzzle_sexp = args.first()
        solution_sexp = args.rest().first()
        cost, r = run_program(puzzle_sexp, solution_sexp)
        error, result = parse_sexp_to_conditions(r)
        return error, result, cost
    except EvalError:
        return Err.SEXP_ERROR, None, uint64(0)
