from __future__ import annotations

from collections.abc import Sequence

from chia_rs import AugSchemeMPL, G2Element

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle, T_SpendBundle
from chia.wallet.util.debug_spend_bundle import debug_spend_bundle


class WalletSpendBundle(SpendBundle):
    @classmethod
    def aggregate(cls, spend_bundles: Sequence[T_SpendBundle]) -> WalletSpendBundle:
        coin_spends: list[CoinSpend] = []
        sigs: list[G2Element] = []
        for bundle in spend_bundles:
            coin_spends += bundle.coin_spends
            sigs.append(bundle.aggregated_signature)
        aggregated_signature = AugSchemeMPL.aggregate(sigs)
        return cls(coin_spends, aggregated_signature)

    def debug(self, agg_sig_additional_data: bytes = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA) -> None:
        debug_spend_bundle(self, agg_sig_additional_data)  # pragma: no cover
