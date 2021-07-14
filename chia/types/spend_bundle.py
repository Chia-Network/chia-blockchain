from dataclasses import dataclass
from typing import List

from blspy import AugSchemeMPL, G2Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.streamable import Streamable, streamable
from chia.wallet.util.debug_spend_bundle import debug_spend_bundle

from .coin_spend import CoinSpend


@dataclass(frozen=True)
@streamable
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
    def aggregate(cls, spend_bundles) -> "SpendBundle":
        coin_spends: List[CoinSpend] = []
        sigs: List[G2Element] = []
        for bundle in spend_bundles:
            coin_spends += bundle.coin_spends
            sigs.append(bundle.aggregated_signature)
        aggregated_signature = AugSchemeMPL.aggregate(sigs)
        return cls(coin_spends, aggregated_signature)

    def additions(self) -> List[Coin]:
        items: List[Coin] = []
        for coin_spend in self.coin_spends:
            items.extend(coin_spend.additions())
        return items

    def removals(self) -> List[Coin]:
        """This should be used only by wallet"""
        return [_.coin for _ in self.coin_spends]

    def fees(self) -> int:
        """Unsafe to use for fees validation!!!"""
        amount_in = sum(_.amount for _ in self.removals())
        amount_out = sum(_.amount for _ in self.additions())

        return amount_in - amount_out

    def name(self) -> bytes32:
        return self.get_hash()

    def debug(self, agg_sig_additional_data=bytes([3] * 32)):
        debug_spend_bundle(self, agg_sig_additional_data)

    def not_ephemeral_additions(self):
        all_removals = self.removals()
        all_additions = self.additions()
        result: List[Coin] = []

        for add in all_additions:
            if add in all_removals:
                continue
            result.append(add)

        return result
