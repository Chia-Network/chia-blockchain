from __future__ import annotations

from chia_rs import CoinSpend
from chia_rs.sized_ints import uint64

from chia.consensus.condition_costs import ConditionCost
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, run_with_cost
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.errors import Err, ValidationError


def compute_additions_with_cost(
    cs: CoinSpend,
    *,
    max_cost: int = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
) -> tuple[list[Coin], int]:
    """
    Run the puzzle in the specified CoinSpend and return the cost and list of
    coins created by the puzzle, i.e. additions. If the cost (CLVM- and
    condition cost) exceeds the specified max_cost, the function fails with a
    ValidationError exception. Byte cost is not included since at this point the
    puzzle and solution may have been decompressed, the true byte-cost can only be
    measured at the block generator level.
    """
    parent_id = cs.coin.name()
    ret: list[Coin] = []
    cost, r = run_with_cost(cs.puzzle_reveal, max_cost, cs.solution)
    for cond in Program.to(r).as_iter():
        if cost > max_cost:
            raise ValidationError(Err.BLOCK_COST_EXCEEDS_MAX, "compute_additions() for CoinSpend")
        atoms = cond.as_iter()
        op = next(atoms).atom
        if op in {
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_UNSAFE,
            ConditionOpcode.AGG_SIG_ME,
        }:
            cost += ConditionCost.AGG_SIG.value
            continue
        if op != ConditionOpcode.CREATE_COIN.value:
            continue
        cost += ConditionCost.CREATE_COIN.value
        puzzle_hash = next(atoms).as_atom()
        amount = uint64(next(atoms).as_int())
        ret.append(Coin(parent_id, puzzle_hash, uint64(amount)))

    return ret, cost


def compute_additions(cs: CoinSpend, *, max_cost: int = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM) -> list[Coin]:
    return compute_additions_with_cost(cs, max_cost=max_cost)[0]
