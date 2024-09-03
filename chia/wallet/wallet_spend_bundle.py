from __future__ import annotations

from typing import Any, Dict, List, Tuple

from chia_rs import AugSchemeMPL, G2Element

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle, T_SpendBundle
from chia.wallet.util.debug_spend_bundle import debug_spend_bundle


class WalletSpendBundle(SpendBundle):

    @classmethod
    def from_bytes(cls, bytes: bytes) -> WalletSpendBundle:
        sb = SpendBundle.from_bytes(bytes)
        return cls(sb.coin_spends, sb.aggregated_signature)

    @classmethod
    def parse_rust(cls, blob: bytes, flag: bool = False) -> Tuple[WalletSpendBundle, int]:
        bundle, advance = super(WalletSpendBundle, WalletSpendBundle).parse_rust(blob)
        return cls(bundle.coin_spends, bundle.aggregated_signature), advance

    @classmethod
    def from_json_dict(cls, json_dict: Dict[str, Any]) -> WalletSpendBundle:
        sb = SpendBundle.from_json_dict(json_dict)
        return cls(sb.coin_spends, sb.aggregated_signature)

    @classmethod
    def aggregate(cls, spend_bundles: List[T_SpendBundle]) -> WalletSpendBundle:
        coin_spends: List[CoinSpend] = []
        sigs: List[G2Element] = []
        for bundle in spend_bundles:
            coin_spends += bundle.coin_spends
            sigs.append(bundle.aggregated_signature)
        aggregated_signature = AugSchemeMPL.aggregate(sigs)
        return cls(coin_spends, aggregated_signature)

    def debug(self, agg_sig_additional_data: bytes = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA) -> None:
        debug_spend_bundle(self, agg_sig_additional_data)  # pragma: no cover
