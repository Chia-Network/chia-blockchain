from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from chia.consensus.condition_costs import ConditionCost
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.errors import Err, ValidationError
from chia.util.ints import uint64


@dataclass(frozen=True)
class HintedCoin:
    coin: Coin
    hint: Optional[bytes32]


def compute_spend_hints_and_additions(
    cs: CoinSpend,
    *,
    max_cost: int = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
) -> Tuple[Dict[bytes32, HintedCoin], int]:
    cost, result_program = cs.puzzle_reveal.run_with_cost(max_cost, cs.solution)

    hinted_coins: Dict[bytes32, HintedCoin] = {}
    for condition in result_program.as_iter():
        if cost > max_cost:
            raise ValidationError(Err.BLOCK_COST_EXCEEDS_MAX, "compute_spend_hints_and_additions() for CoinSpend")
        atoms = condition.as_iter()
        op = next(atoms).atom
        if op in [
            ConditionOpcode.AGG_SIG_PARENT,
            ConditionOpcode.AGG_SIG_PUZZLE,
            ConditionOpcode.AGG_SIG_AMOUNT,
            ConditionOpcode.AGG_SIG_PUZZLE_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_AMOUNT,
            ConditionOpcode.AGG_SIG_PARENT_PUZZLE,
            ConditionOpcode.AGG_SIG_UNSAFE,
            ConditionOpcode.AGG_SIG_ME,
        ]:
            cost += ConditionCost.AGG_SIG.value
            continue
        if op != ConditionOpcode.CREATE_COIN.value:
            continue
        cost += ConditionCost.CREATE_COIN.value

        rf = condition.at("rf").atom
        assert rf is not None

        coin: Coin = Coin(cs.coin.name(), bytes32(rf), uint64(condition.at("rrf").as_int()))
        hint: Optional[bytes32] = None
        if (
            condition.at("rrr") != Program.to(None)  # There's more than two arguments
            and condition.at("rrrf").atom is None  # The 3rd argument is a cons
        ):
            potential_hint: Optional[bytes] = condition.at("rrrff").atom
            if potential_hint is not None and len(potential_hint) == 32:
                hint = bytes32(potential_hint)
        hinted_coins[bytes32(coin.name())] = HintedCoin(coin, hint)

    return hinted_coins, cost
