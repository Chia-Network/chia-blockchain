from dataclasses import dataclass
from typing import List

from blspy import AugSchemeMPL, G2Element

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.streamable import Streamable, streamable

from .coin_solution import CoinSolution


@dataclass(frozen=True)
@streamable
class SpendBundle(Streamable):
    """
    This is a list of coins being spent along with their solution programs, and a single
    aggregated signature. This is the object that most closely corresponds to a bitcoin
    transaction (although because of non-interactive signature aggregation, the boundaries
    between transactions are more flexible than in bitcoin).
    """

    coin_solutions: List[CoinSolution]
    aggregated_signature: G2Element

    @classmethod
    def aggregate(cls, spend_bundles) -> "SpendBundle":
        coin_solutions: List[CoinSolution] = []
        sigs: List[G2Element] = []
        for bundle in spend_bundles:
            coin_solutions += bundle.coin_solutions
            sigs.append(bundle.aggregated_signature)
        aggregated_signature = AugSchemeMPL.aggregate(sigs)
        return cls(coin_solutions, aggregated_signature)

    def additions(self) -> List[Coin]:
        items: List[Coin] = []
        for coin_solution in self.coin_solutions:
            items.extend(coin_solution.additions())
        return items

    def announcements(self) -> List[Announcement]:
        items: List[Announcement] = []
        for coin_solution in self.coin_solutions:
            items.extend(coin_solution.announcements())
        return items

    def removals(self) -> List[Coin]:
        """ This should be used only by wallet"""
        return [_.coin for _ in self.coin_solutions]

    def fees(self) -> int:
        """ Unsafe to use for fees validation!!! """
        amount_in = sum(_.amount for _ in self.removals())
        amount_out = sum(_.amount for _ in self.additions())

        return amount_in - amount_out

    def removal_names(self) -> List[bytes32]:
        return [_.coin.name() for _ in self.coin_solutions]

    def addition_names(self) -> List[bytes32]:
        return [_.name() for _ in self.additions()]

    def name(self) -> bytes32:
        return self.get_hash()

    def not_ephemeral_spends(self):
        all_removals = self.removals()
        all_additions = self.additions()
        result: List[Coin] = []

        for rem in all_removals:
            if rem in all_additions:
                continue
            result.append(rem)

        return result

    def not_ephemeral_additions(self):
        all_removals = self.removals()
        all_additions = self.additions()
        result: List[Coin] = []

        for add in all_additions:
            if add in all_removals:
                continue
            result.append(add)

        return result
