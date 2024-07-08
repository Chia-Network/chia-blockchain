from __future__ import annotations

from typing import List

from chia_rs import AugSchemeMPL, G2Element, SpendBundle

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import T_SpendBundle
from chia.wallet.util.debug_spend_bundle import debug_spend_bundle


class WalletSpendBundle(SpendBundle):
    def __new__(cls, coin_spends: List[CoinSpend], aggregated_signature: G2Element) -> WalletSpendBundle:
        wsb = super().__new__(cls, coin_spends, aggregated_signature)
        assert isinstance(wsb, WalletSpendBundle)
        return wsb

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (WalletSpendBundle, SpendBundle)):
            return False
        return self.coin_spends == other.coin_spends and self.aggregated_signature == other.aggregated_signature

    @staticmethod
    def from_bytes(bytes: bytes) -> WalletSpendBundle:
        sb = SpendBundle.from_bytes(bytes)
        return WalletSpendBundle(sb.coin_spends, sb.aggregated_signature)

    @classmethod
    def aggregate(cls, spend_bundles: List[T_SpendBundle]) -> WalletSpendBundle:
        assert all(
            isinstance(sb, WalletSpendBundle) for sb in spend_bundles
        ), "Expecting a list of WalletSpendBundle elements"
        coin_spends: List[CoinSpend] = []
        sigs: List[G2Element] = []
        for bundle in spend_bundles:
            coin_spends += bundle.coin_spends
            sigs.append(bundle.aggregated_signature)
        aggregated_signature = AugSchemeMPL.aggregate(sigs)
        return WalletSpendBundle(coin_spends, aggregated_signature)

    def debug(self, agg_sig_additional_data: bytes = DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA) -> None:
        debug_spend_bundle(self, agg_sig_additional_data)
