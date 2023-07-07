from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional, Tuple

from chia.consensus.condition_costs import ConditionCost
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_item import BundleCoinSpend
from chia.util.ints import uint64


def run_for_cost(
    puzzle_reveal: SerializedProgram, solution: SerializedProgram, additions_count: int, max_cost: int
) -> uint64:
    create_coins_cost = additions_count * ConditionCost.CREATE_COIN.value
    clvm_cost, _ = puzzle_reveal.run_mempool_with_cost(max_cost, solution)
    saved_cost = uint64(clvm_cost + create_coins_cost)
    return saved_cost


@dataclasses.dataclass(frozen=True)
class DedupCoinSpend:
    solution: SerializedProgram
    cost: Optional[uint64]


@dataclasses.dataclass(frozen=True)
class EligibleCoinSpends:
    eligible_spends: Dict[bytes32, DedupCoinSpend] = dataclasses.field(default_factory=dict)

    def get_deduplication_info(
        self, *, bundle_coin_spends: Dict[bytes32, BundleCoinSpend], max_cost: int
    ) -> Tuple[List[CoinSpend], uint64, List[Coin]]:
        """
        Checks all coin spends of a mempool item for deduplication eligibility and
        provides the caller with the necessary information that allows it to perform
        identical spend aggregation on that mempool item if possible

        Args:
            bundle_coin_spends: the mempool item's coin spends data
            max_cost: the maximum limit when running for cost

        Returns:
            List[CoinSpend]: list of unique coin spends in this mempool item
            uint64: the cost we're saving by deduplicating eligible coins
            List[Coin]: list of unique additions in this mempool item

        Raises:
            ValueError to skip the mempool item we're currently in, if it's
            attempting to spend an eligible coin with a different solution than the
            one we're already deduplicating on.
        """
        cost_saving = 0
        unique_coin_spends: List[CoinSpend] = []
        unique_additions: List[Coin] = []
        new_eligible_spends: Dict[bytes32, DedupCoinSpend] = {}
        # See if this item has coin spends that are eligible for deduplication
        for coin_id, spend_data in bundle_coin_spends.items():
            if not spend_data.eligible_for_dedup:
                unique_coin_spends.append(spend_data.coin_spend)
                unique_additions.extend(spend_data.additions)
                continue
            # See if we processed an item with this coin before
            dedup_coin_spend = self.eligible_spends.get(coin_id)
            if dedup_coin_spend is None:
                # We didn't process an item with this coin before. If we end up including
                # this item, add this pair to eligible_spends
                new_eligible_spends[coin_id] = DedupCoinSpend(spend_data.coin_spend.solution, None)
                unique_coin_spends.append(spend_data.coin_spend)
                unique_additions.extend(spend_data.additions)
                continue
            # See if the solution was identical
            current_solution, duplicate_cost = dataclasses.astuple(dedup_coin_spend)
            if current_solution != spend_data.coin_spend.solution:
                # It wasn't, so let's skip this whole item because it's relying on
                # spending this coin with a different solution and that would
                # conflict with the coin spends that we're deduplicating already
                # NOTE: We can miss an opportunity to deduplicate on other solutions
                # even if they end up saving more cost, as we're going for the first
                # solution we see from the relatively highest FPC item, to avoid
                # severe performance and/or time-complexity impact
                raise ValueError("Solution is different from what we're deduplicating on")
            # Let's calculate the saved cost if we never did that before
            if duplicate_cost is None:
                # See first if this mempool item had this cost computed before
                # This can happen if this item didn't get included in the previous block
                spend_cost = spend_data.cost
                if spend_cost is None:
                    spend_cost = run_for_cost(
                        puzzle_reveal=spend_data.coin_spend.puzzle_reveal,
                        solution=spend_data.coin_spend.solution,
                        additions_count=len(spend_data.additions),
                        max_cost=max_cost,
                    )
                    # Update this mempool item's coin spends map
                    bundle_coin_spends[coin_id] = BundleCoinSpend(
                        spend_data.coin_spend, spend_data.eligible_for_dedup, spend_data.additions, spend_cost
                    )
                duplicate_cost = spend_cost
                # If we end up including this item, update this entry's cost
                new_eligible_spends[coin_id] = DedupCoinSpend(current_solution, duplicate_cost)
            cost_saving += duplicate_cost
        # Update the eligible coin spends data
        self.eligible_spends.update(new_eligible_spends)
        return unique_coin_spends, uint64(cost_saving), unique_additions
