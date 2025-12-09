from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chia_rs import CoinSpend, G2Element, SpendBundle, SpendBundleConditions
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia.types.blockchain_format.coin import Coin
from chia.util.streamable import recurse_jsonify


@dataclass(frozen=True)
class UnspentLineageInfo:
    coin_id: bytes32
    parent_id: bytes32
    parent_parent_id: bytes32


@dataclass
class BundleCoinSpend:
    coin_spend: CoinSpend
    eligible_for_dedup: bool
    additions: list[Coin]
    # cost on the specific solution in this item. The cost includes execution
    # cost and conditions cost, not byte-cost.
    cost: uint64

    # if this spend is eligible for fast forward, this may be set to the
    # current unspent lineage belonging to this singleton, that we would rebase
    # this spend on top of if we were to make a block now
    # When finding MempoolItems by coin ID, we use Coin ID from it if it's set
    latest_singleton_lineage: UnspentLineageInfo | None

    @property
    def supports_fast_forward(self) -> bool:
        return self.latest_singleton_lineage is not None


@dataclass(frozen=True)
class MempoolItem:
    aggregated_signature: G2Element
    fee: uint64
    conds: SpendBundleConditions
    spend_bundle_name: bytes32
    height_added_to_mempool: uint32

    # If present, this SpendBundle is not valid at or before this height
    assert_height: uint32 | None = None

    # If present, this SpendBundle is not valid once the block height reaches
    # the specified height
    assert_before_height: uint32 | None = None
    assert_before_seconds: uint64 | None = None

    # Map of coin ID to coin spend data between the bundle and its
    # SpendBundleConditions
    bundle_coin_spends: dict[bytes32, BundleCoinSpend] = field(default_factory=dict)

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
    def additions(self) -> list[Coin]:
        additions: list[Coin] = []
        for spend in self.conds.spends:
            for puzzle_hash, amount, _ in spend.create_coin:
                coin = Coin(spend.coin_id, puzzle_hash, uint64(amount))
                additions.append(coin)
        return additions

    @property
    def removals(self) -> list[Coin]:
        return [bcs.coin_spend.coin for bcs in self.bundle_coin_spends.values()]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "spend_bundle": recurse_jsonify(self.to_spend_bundle()),
            "fee": recurse_jsonify(self.fee),
            "npc_result": {"Error": None, "conds": recurse_jsonify(self.conds)},
            "cost": recurse_jsonify(self.cost),
            "spend_bundle_name": recurse_jsonify(self.spend_bundle_name),
            "additions": recurse_jsonify(self.additions),
            "removals": recurse_jsonify(self.removals),
        }

    def to_spend_bundle(self) -> SpendBundle:
        return SpendBundle([bcs.coin_spend for bcs in self.bundle_coin_spends.values()], self.aggregated_signature)
