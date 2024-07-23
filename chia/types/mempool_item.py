from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.util.ints import uint32, uint64
from chia.util.streamable import recurse_jsonify


@dataclass(frozen=True)
class BundleCoinSpend:
    coin_spend: CoinSpend
    eligible_for_dedup: bool
    eligible_for_fast_forward: bool
    additions: List[Coin]
    # cost on the specific solution in this item
    cost: Optional[uint64] = None


@dataclass(frozen=True)
class MempoolItem:
    spend_bundle: SpendBundle
    fee: uint64
    conds: SpendBundleConditions
    spend_bundle_name: bytes32
    height_added_to_mempool: uint32

    # If present, this SpendBundle is not valid at or before this height
    assert_height: Optional[uint32] = None

    # If present, this SpendBundle is not valid once the block height reaches
    # the specified height
    assert_before_height: Optional[uint32] = None
    assert_before_seconds: Optional[uint64] = None

    # Map of coin ID to coin spend data between the bundle and its
    # SpendBundleConditions
    bundle_coin_spends: Dict[bytes32, BundleCoinSpend] = field(default_factory=dict)

    def __lt__(self, other: MempoolItem) -> bool:
        return self.fee_per_cost < other.fee_per_cost

    def __hash__(self) -> int:
        return hash(self.spend_bundle_name)

    @property
    def fee_per_cost(self) -> float:
        return int(self.fee) / int(self.cost)

    @property
    def name(self) -> bytes32:
        return self.spend_bundle_name

    @property
    def cost(self) -> uint64:
        return uint64(0 if self.conds is None else self.conds.cost)

    @property
    def additions(self) -> List[Coin]:
        additions: List[Coin] = []
        for spend in self.conds.spends:
            for puzzle_hash, amount, _ in spend.create_coin:
                coin = Coin(spend.coin_id, puzzle_hash, uint64(amount))
                additions.append(coin)
        return additions

    @property
    def removals(self) -> List[Coin]:
        return self.spend_bundle.removals()

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "spend_bundle": recurse_jsonify(self.spend_bundle),
            "fee": recurse_jsonify(self.fee),
            "npc_result": {"Error": None, "conds": recurse_jsonify(self.conds)},
            "cost": recurse_jsonify(self.cost),
            "spend_bundle_name": recurse_jsonify(self.spend_bundle_name),
            "additions": recurse_jsonify(self.additions),
            "removals": recurse_jsonify(self.removals),
        }
