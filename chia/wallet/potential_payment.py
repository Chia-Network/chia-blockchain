from typing import Optional, List, Dict, Tuple, Set

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint64
from chia.wallet.payment import Payment
from chia.wallet.puzzles.puzzle_utils import (
    make_create_coin_condition,
    make_assert_coin_announcement,
    make_create_coin_announcement,
    make_reserve_fee_condition,
)
from chia.wallet.wallet import Wallet

from clvm.casts import int_to_bytes

class PotentialPayment:
    wallet: Wallet
    selected_coins: List[Coin]
    origin_id: bytes32  # The ID of the coin that will create child coins
    fee: int  # Fees can be negative to signify minting of value
    conditions_for_coins: Optional[Dict[bytes32, List[List]]]

    def __init__(self, wallet, selected_coins, origin_id, fee):
        self.wallet = wallet
        self.selected_coins = selected_coins
        self.origin_id = origin_id
        self.fee = fee
        self.conditions_for_coins = None

    @classmethod
    async def create(
        cls,
        wallet: Wallet,
        amount_to_select: uint64,
        fee: int,
        coins: Optional[List[Coin]] = None,
        origin_id: Optional[bytes32] = None,
    ):
        total_amount_needed = (amount_to_select + max(0, fee))

        if coins is None:
            coins = list(await wallet.select_coins(total_amount_needed))

        if origin_id is None:
            origin_id = coins[0].name()

        assert origin_id in [c.name() for c in coins]
        assert total_amount_needed <= sum([c.amount for c in coins])

        return cls(wallet, coins, origin_id, fee)

    async def set_payments(self, payments: List[Payment]):
        payment_sum = sum([p.amount for p in payments])
        output_amount = sum([c.amount for c in self.selected_coins]) - self.fee
        assert payment_sum <= output_amount
        change = (output_amount - payment_sum)
        change_ph = await self.wallet.get_new_puzzlehash()

        conditions_dict = {}
        for coin in self.selected_coins:
            conditions_dict[coin.name()] = []

        conditions_dict[self.origin_id].append(make_create_coin_condition(change_ph, change, []))
        for p in payments:
            conditions_dict[self.origin_id].append(make_create_coin_condition(p.puzzle_hash, p.amount, p.memos))
            if p.extra_conditions is not None:
                for extra_condition in p.extra_conditions:
                    conditions_dict[self.origin_id].append(extra_condition)

        self.conditions_for_coins = conditions_dict


    @classmethod
    def bundle(cls, pps: List['PotentialPayment']) -> List['PotentialPayment']:
        """
        We have to make sure that all melt values are in some way dependent on all of the mint values.
        If we don't do this, a farmer can separate a melt from a mint and create extra fees for themselves.

        In addition, we need to make sure to add a RESERVE_FEE condition so that the farmer actually gets the fee
        and not some node along the way.
        """
        # The tuples in the list are (pps list index, coin_name)
        mint_values: List[Tuple[int, bytes32]] = []  # "Minting" also includes a change in value of 0
        melt_values: List[Tuple[int, bytes32]] = []

        for i in range(len(pps)):
            for coin in pps[i].selected_coins:
                sum_of_outputs = 0
                for condition in pps[i].conditions_for_coins[coin.name()]:
                    if condition[0] == ConditionOpcode.CREATE_COIN:
                        sum_of_outputs += condition[2]
                if coin.amount > sum_of_outputs:
                    melt_values.append((i, coin.name()))
                elif sum_of_outputs >= coin.amount:
                    mint_values.append((i, coin.name()))

        dgraph = DependencyGraph(pps)
        new_relationships: Dict[bytes32, List[bytes32]] = {}

        for i, melt in melt_values:
            melt_deps = dgraph.get_coin_dependencies(melt)
            for q, mint in mint_values:
                if mint not in melt_deps:
                    if mint not in new_relationships:
                        new_relationships[mint] = []
                    if len([dep for dep in melt_deps if dep in new_relationships[mint]]) == 0:
                        pps[q].conditions_for_coins[mint].append(make_create_coin_announcement("$"))
                        pps[i].conditions_for_coins[melt].append(make_assert_coin_announcement(Announcement(mint, "$").name()))
                        new_relationships[mint].append(melt)

        fee_sum = sum([pp.fee for pp in pps])
        pps[0].conditions_for_coins[pps[0].origin_id].append(make_reserve_fee_condition(fee_sum))

        return pps


class DependencyGraph:
    dependencies: Dict[bytes32, List[bytes32]]  # {coin_with_dependency: [list_of_dependencies]}

    def __init__(self, pps: List['PotentialPayment'], allow_external_dependencies=False):
        created_announcements: Dict[bytes32, bytes32] = {}  # {coin_making_announcement: announcement_name}
        asserted_announcements: Dict[bytes32, bytes32] = {}  # {coin_asserting_announcement: announcement_name}

        dependencies: Dict[bytes32, List[bytes32]] = {}  # {coin_with_dependency: [list_of_dependencies]}

        for pp in pps:
            for coin in pp.selected_coins:
                dependencies[coin.name()] = []
                for condition in pp.conditions_for_coins[coin.name()]:
                    if condition[0] == ConditionOpcode.CREATE_COIN_ANNOUNCEMENT:
                        created_announcements[coin.name()] = Announcement(coin.name(), condition[1]).name()
                    elif condition[0] == ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT:
                        created_announcements[coin.name()] = Announcement(coin.puzzle_hash, condition[1]).name()
                    elif condition[0] in [
                        ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT,
                        ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT,
                    ]:
                        asserted_announcements[coin.name()] = condition[1]

        for asserting_coin, asserted_announcement in asserted_announcements.items():
            if asserted_announcement in created_announcements.values():
                for creating_coin, created_announcement in created_announcements.items():
                    if created_announcement == asserted_announcement:
                        dependencies[asserting_coin].append(creating_coin)
            elif not allow_external_dependencies:
                raise ValueError(f"Coin {asserting_coin} has an external dependency")

        self.dependencies = dependencies

    def get_coin_dependencies(self, coin_name: bytes32, known_dependencies=set()) -> Set[bytes32]:
        for dependency in self.dependencies[coin_name]:
            if dependency not in known_dependencies:
                known_dependencies.add(dependency)
                known_dependencies = self.get_coin_dependencies(dependency, known_dependencies)

        return known_dependencies