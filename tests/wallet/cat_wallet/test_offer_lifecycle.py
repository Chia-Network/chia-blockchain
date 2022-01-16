import pytest

from typing import Dict, Optional, List
from blspy import G2Element

from chia.clvm.spend_sim import SpendSim, SimClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.program import Program
from chia.types.announcement import Announcement
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    construct_cat_puzzle,
    SpendableCAT,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.payment import Payment
from chia.wallet.trading.offer import Offer, NotarizedPayment

from tests.clvm.benchmark_costs import cost_of_spend_bundle

acs = Program.to(1)
acs_ph = acs.get_tree_hash()


# Some methods mapping strings to CATs
def str_to_tail(tail_str: str) -> Program:
    return Program.to([3, [], [1, tail_str], []])


def str_to_tail_hash(tail_str: str) -> bytes32:
    return Program.to([3, [], [1, tail_str], []]).get_tree_hash()


def str_to_cat_hash(tail_str: str) -> bytes32:
    return construct_cat_puzzle(CAT_MOD, str_to_tail_hash(tail_str), acs).get_tree_hash()


class TestOfferLifecycle:
    cost: Dict[str, int] = {}

    @pytest.fixture(scope="function")
    async def setup_sim(self):
        sim = await SpendSim.create()
        sim_client = SimClient(sim)
        await sim.farm_block()
        return sim, sim_client

    # This method takes a dictionary of strings mapping to amounts and generates the appropriate CAT/XCH coins
    async def generate_coins(
        self,
        sim,
        sim_client,
        requested_coins: Dict[Optional[str], List[uint64]],
    ) -> Dict[Optional[str], List[Coin]]:
        await sim.farm_block(acs_ph)
        parent_coin: Coin = [cr.coin for cr in await (sim_client.get_coin_records_by_puzzle_hash(acs_ph))][0]

        # We need to gather a list of initial coins to create as well as spends that do the eve spend for every CAT
        payments: List[Payment] = []
        cat_bundles: List[SpendBundle] = []
        for tail_str, amounts in requested_coins.items():
            for amount in amounts:
                if tail_str:
                    tail: Program = str_to_tail(tail_str)  # Making a fake but unique TAIL
                    cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, tail.get_tree_hash(), acs)
                    payments.append(Payment(cat_puzzle.get_tree_hash(), amount, []))
                    cat_bundles.append(
                        unsigned_spend_bundle_for_spendable_cats(
                            CAT_MOD,
                            [
                                SpendableCAT(
                                    Coin(parent_coin.name(), cat_puzzle.get_tree_hash(), amount),
                                    tail.get_tree_hash(),
                                    acs,
                                    Program.to([[51, acs_ph, amount], [51, 0, -113, tail, []]]),
                                )
                            ],
                        )
                    )
                else:
                    payments.append(Payment(acs_ph, amount, []))

        # This bundle create all of the initial coins
        parent_bundle = SpendBundle(
            [
                CoinSpend(
                    parent_coin,
                    acs,
                    Program.to([[51, p.puzzle_hash, p.amount] for p in payments]),
                )
            ],
            G2Element(),
        )

        # Then we aggregate it with all of the eve spends
        await sim_client.push_tx(SpendBundle.aggregate([parent_bundle, *cat_bundles]))
        await sim.farm_block()

        # Search for all of the coins and put them into a dictionary
        coin_dict: Dict[Optional[str], List[Coin]] = {}
        for tail_str, _ in requested_coins.items():
            if tail_str:
                tail_hash: bytes32 = str_to_tail_hash(tail_str)
                cat_ph: bytes32 = construct_cat_puzzle(CAT_MOD, tail_hash, acs).get_tree_hash()
                coin_dict[tail_str] = [
                    cr.coin
                    for cr in await (sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))
                ]
            else:
                coin_dict[None] = list(
                    filter(
                        lambda c: c.amount < 250000000000,
                        [
                            cr.coin
                            for cr in await (
                                sim_client.get_coin_records_by_puzzle_hash(acs_ph, include_spent_coins=False)
                            )
                        ],
                    )
                )

        return coin_dict

    # This method simulates a wallet's `generate_signed_transaction` but doesn't bother with non-offer announcements
    def generate_secure_bundle(
        self,
        selected_coins: List[Coin],
        announcements: List[Announcement],
        offered_amount: uint64,
        tail_str: Optional[str] = None,
    ) -> SpendBundle:
        announcement_assertions: List[List] = [[63, a.name()] for a in announcements]
        selected_coin_amount: int = sum([c.amount for c in selected_coins])
        non_primaries: List[Coin] = [] if len(selected_coins) < 2 else selected_coins[1:]
        inner_solution: List[List] = [
            [51, Offer.ph(), offered_amount],  # Offered coin
            [51, acs_ph, uint64(selected_coin_amount - offered_amount)],  # Change
            *announcement_assertions,
        ]

        if tail_str is None:
            bundle = SpendBundle(
                [
                    CoinSpend(
                        selected_coins[0],
                        acs,
                        Program.to(inner_solution),
                    ),
                    *[CoinSpend(c, acs, Program.to([])) for c in non_primaries],
                ],
                G2Element(),
            )
        else:
            spendable_cats: List[SpendableCAT] = [
                SpendableCAT(
                    c,
                    str_to_tail_hash(tail_str),
                    acs,
                    Program.to(
                        [
                            [51, 0, -113, str_to_tail(tail_str), Program.to([])],  # Use the TAIL rather than lineage
                            *(inner_solution if c == selected_coins[0] else []),
                        ]
                    ),
                )
                for c in selected_coins
            ]
            bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cats)

        return bundle

    @pytest.mark.asyncio()
    async def test_complex_offer(self, setup_sim):
        sim, sim_client = setup_sim

        try:
            coins_needed: Dict[Optional[str], List[int]] = {
                None: [500, 400, 300],
                "red": [250, 100],
                "blue": [3000],
            }
            all_coins: Dict[Optional[str], List[Coin]] = await self.generate_coins(sim, sim_client, coins_needed)
            chia_coins: List[Coin] = all_coins[None]
            red_coins: List[Coin] = all_coins["red"]
            blue_coins: List[Coin] = all_coins["blue"]

            # Create an XCH Offer for RED
            chia_requested_payments: Dict[Optional[bytes32], List[Payment]] = {
                str_to_tail_hash("red"): [
                    Payment(acs_ph, 100, [b"memo"]),
                    Payment(acs_ph, 200, [b"memo"]),
                ]
            }

            chia_requested_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = Offer.notarize_payments(
                chia_requested_payments, chia_coins
            )
            chia_announcements: List[Announcement] = Offer.calculate_announcements(chia_requested_payments)
            chia_secured_bundle: SpendBundle = self.generate_secure_bundle(chia_coins, chia_announcements, 1000)
            chia_offer = Offer(chia_requested_payments, chia_secured_bundle)
            assert not chia_offer.is_valid()

            # Create a RED Offer for XCH
            red_requested_payments: Dict[Optional[bytes32], List[Payment]] = {
                None: [
                    Payment(acs_ph, 300, [b"red memo"]),
                    Payment(acs_ph, 400, [b"red memo"]),
                ]
            }

            red_requested_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = Offer.notarize_payments(
                red_requested_payments, red_coins
            )
            red_announcements: List[Announcement] = Offer.calculate_announcements(red_requested_payments)
            red_secured_bundle: SpendBundle = self.generate_secure_bundle(
                red_coins, red_announcements, 350, tail_str="red"
            )
            red_offer = Offer(red_requested_payments, red_secured_bundle)
            assert not red_offer.is_valid()

            # Test aggregation of offers
            new_offer = Offer.aggregate([chia_offer, red_offer])
            assert new_offer.get_offered_amounts() == {None: 1000, str_to_tail_hash("red"): 350}
            assert new_offer.get_requested_amounts() == {None: 700, str_to_tail_hash("red"): 300}
            assert new_offer.is_valid()

            # Create yet another offer of BLUE for XCH and RED
            blue_requested_payments: Dict[Optional[bytes32], List[Payment]] = {
                None: [
                    Payment(acs_ph, 200, [b"blue memo"]),
                ],
                str_to_tail_hash("red"): [
                    Payment(acs_ph, 50, [b"blue memo"]),
                ],
            }

            blue_requested_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = Offer.notarize_payments(
                blue_requested_payments, blue_coins
            )
            blue_announcements: List[Announcement] = Offer.calculate_announcements(blue_requested_payments)
            blue_secured_bundle: SpendBundle = self.generate_secure_bundle(
                blue_coins, blue_announcements, 2000, tail_str="blue"
            )
            blue_offer = Offer(blue_requested_payments, blue_secured_bundle)
            assert not blue_offer.is_valid()

            # Test a re-aggregation
            new_offer: Offer = Offer.aggregate([new_offer, blue_offer])
            assert new_offer.get_offered_amounts() == {
                None: 1000,
                str_to_tail_hash("red"): 350,
                str_to_tail_hash("blue"): 2000,
            }
            assert new_offer.get_requested_amounts() == {None: 900, str_to_tail_hash("red"): 350}
            assert new_offer.summary() == (
                {
                    "xch": 1000,
                    str_to_tail_hash("red").hex(): 350,
                    str_to_tail_hash("blue").hex(): 2000,
                },
                {"xch": 900, str_to_tail_hash("red").hex(): 350},
            )
            assert new_offer.get_pending_amounts() == {
                "xch": 1200,
                str_to_tail_hash("red").hex(): 350,
                str_to_tail_hash("blue").hex(): 3000,
            }
            assert new_offer.is_valid()

            # Test (de)serialization
            assert Offer.from_bytes(bytes(new_offer)) == new_offer

            # Make sure we can actually spend the offer once it's valid
            arbitrage_ph: bytes32 = Program.to([3, [], [], 1]).get_tree_hash()
            offer_bundle: SpendBundle = new_offer.to_valid_spend(arbitrage_ph)
            result = await sim_client.push_tx(offer_bundle)
            assert result == (MempoolInclusionStatus.SUCCESS, None)
            self.cost["complex offer"] = cost_of_spend_bundle(offer_bundle)
            await sim.farm_block()
        finally:
            await sim.close()

    def test_cost(self):
        import json
        import logging

        log = logging.getLogger(__name__)
        log.warning(json.dumps(self.cost))
