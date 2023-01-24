from __future__ import annotations

from dataclasses import dataclass
from typing import List

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import SerializedProgram
from chia.util.chain_utils import additions_for_solution, fee_for_solution
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class CoinSpend(Streamable):
    """
    This is a rather disparate data structure that validates coin transfers. It's generally populated
    with data from different sources, since burned coins are identified by name, so it is built up
    more often that it is streamed.
    """

    coin: Coin
    puzzle_reveal: SerializedProgram
    solution: SerializedProgram


def compute_additions(cs: CoinSpend, *, max_cost: int = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM) -> List[Coin]:
    return additions_for_solution(cs.coin.name(), cs.puzzle_reveal, cs.solution, max_cost)


def compute_reserved_fee(cs: CoinSpend, *, max_cost: int = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM) -> int:
    return fee_for_solution(cs.puzzle_reveal, cs.solution, max_cost)
