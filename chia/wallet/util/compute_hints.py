from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64


@dataclass(frozen=True)
class HintedCoin:
    coin: Coin
    hint: Optional[bytes32]


def compute_spend_hints_and_additions(cs: CoinSpend) -> Dict[bytes32, HintedCoin]:
    _, result_program = cs.puzzle_reveal.run_with_cost(INFINITE_COST, cs.solution)

    hinted_coins: Dict[bytes32, HintedCoin] = {}
    for condition in result_program.as_iter():
        if condition.at("f").atom == ConditionOpcode.CREATE_COIN:  # It's a create coin:
            coin: Coin = Coin(cs.coin.name(), bytes32(condition.at("rf").atom), uint64(condition.at("rrf").as_int()))
            hint: Optional[bytes32] = None
            if (
                condition.at("rrr") != Program.to(None)  # There's more than two arguments
                and condition.at("rrrf").atom is None  # The 3rd argument is a cons
            ):
                potential_hint: bytes = condition.at("rrrff").atom
                if len(potential_hint) == 32:
                    hint = bytes32(potential_hint)
            hinted_coins[bytes32(coin.name())] = HintedCoin(coin, hint)

    return hinted_coins
