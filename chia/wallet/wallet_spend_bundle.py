from __future__ import annotations

import dataclasses
from typing import Any, Dict, List

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.spend_bundle import SpendBundle, T_SpendBundle, aggregate_spend_bundles, sb_from_json_dict
from chia.util.streamable import streamable
from chia.wallet.util.debug_spend_bundle import debug_spend_bundle


@streamable
@dataclasses.dataclass(frozen=True)
class WalletSpendBundle(SpendBundle):
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (WalletSpendBundle, SpendBundle)):
            return False
        return self.coin_spends == other.coin_spends and self.aggregated_signature == other.aggregated_signature

    @classmethod
    def aggregate(cls, spend_bundles: List[T_SpendBundle]) -> WalletSpendBundle:
        assert all(
            isinstance(sb, WalletSpendBundle) for sb in spend_bundles
        ), "Expecting a list of WalletSpendBundle elements"
        return cls(*aggregate_spend_bundles(spend_bundles))

    @classmethod
    def from_json_dict(cls, json_dict: Dict[str, Any]) -> WalletSpendBundle:
        return sb_from_json_dict(cls, json_dict)

    def debug(self, agg_sig_additional_data: bytes = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA) -> None:
        debug_spend_bundle(self, agg_sig_additional_data)
