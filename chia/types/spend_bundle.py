from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from chia_rs import AugSchemeMPL, G2Element

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.errors import Err, ValidationError
from chia.util.streamable import Streamable, streamable, streamable_from_dict
from chia.wallet.util.debug_spend_bundle import debug_spend_bundle

from .coin_spend import CoinSpend, compute_additions_with_cost


@streamable
@dataclass(frozen=True)
class SpendBundle(Streamable):
    """
    This is a list of coins being spent along with their solution programs, and a single
    aggregated signature. This is the object that most closely corresponds to a bitcoin
    transaction (although because of non-interactive signature aggregation, the boundaries
    between transactions are more flexible than in bitcoin).
    """

    coin_spends: List[CoinSpend]
    aggregated_signature: G2Element

    @classmethod
    def aggregate(cls, spend_bundles: List[SpendBundle]) -> SpendBundle:
        coin_spends: List[CoinSpend] = []
        sigs: List[G2Element] = []
        for bundle in spend_bundles:
            coin_spends += bundle.coin_spends
            sigs.append(bundle.aggregated_signature)
        aggregated_signature = AugSchemeMPL.aggregate(sigs)
        return cls(coin_spends, aggregated_signature)

    # TODO: this should be removed
    def additions(self, *, max_cost: int = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM) -> List[Coin]:
        items: List[Coin] = []
        for cs in self.coin_spends:
            coins, cost = compute_additions_with_cost(cs, max_cost=max_cost)
            max_cost -= cost
            if max_cost < 0:
                raise ValidationError(Err.BLOCK_COST_EXCEEDS_MAX, "additions() for SpendBundle")
            items.extend(coins)
        return items

    def removals(self) -> List[Coin]:
        return [_.coin for _ in self.coin_spends]

    def name(self) -> bytes32:
        return self.get_hash()

    def debug(self, agg_sig_additional_data: bytes = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA) -> None:
        debug_spend_bundle(self, agg_sig_additional_data)

    @classmethod
    def from_json_dict(cls, json_dict: Dict[str, Any]) -> SpendBundle:
        if "coin_solutions" in json_dict and "coin_spends" not in json_dict:
            json_dict = dict(
                aggregated_signature=json_dict["aggregated_signature"], coin_spends=json_dict["coin_solutions"]
            )
        return streamable_from_dict(cls, json_dict)


# This function executes all the puzzles to compute the difference between
# additions and removals
def estimate_fees(spend_bundle: SpendBundle) -> int:
    """Unsafe to use for fees validation!!!"""
    removed_amount = 0
    added_amount = 0
    max_cost = DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM
    for cs in spend_bundle.coin_spends:
        removed_amount += cs.coin.amount
        coins, cost = compute_additions_with_cost(cs, max_cost=max_cost)
        max_cost -= cost
        if max_cost < 0:
            raise ValidationError(Err.BLOCK_COST_EXCEEDS_MAX, "estimate_fees() for SpendBundle")
        for c in coins:
            added_amount += c.amount
    return removed_amount - added_amount
