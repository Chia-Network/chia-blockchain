from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional

import pytest
from blspy import G2Element

from chia.clvm.spend_sim import sim_and_client
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.trading.offer import OFFER_MOD, NotarizedPayment, Offer

acs = Program.to(1)
acs_ph = acs.get_tree_hash()


# Some methods mapping strings to CATs
def str_to_tail(tail_str: str) -> Program:
    return Program.to([3, [], [1, tail_str], []])


def str_to_tail_hash(tail_str: str) -> bytes32:
    return Program.to([3, [], [1, tail_str], []]).get_tree_hash()


def str_to_cat_hash(tail_str: str) -> bytes32:
    return construct_cat_puzzle(CAT_MOD, str_to_tail_hash(tail_str), acs).get_tree_hash()


# This method takes a dictionary of strings mapping to amounts and generates the appropriate CAT/XCH coins
async def generate_coins(
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

    # This bundle creates all of the initial coins
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
                cr.coin for cr in await (sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))
            ]
        else:
            coin_dict[None] = list(
                filter(
                    lambda c: c.amount < 250000000000,
                    [
                        cr.coin
                        for cr in await (sim_client.get_coin_records_by_puzzle_hash(acs_ph, include_spent_coins=False))
                    ],
                )
            )

    return coin_dict


# `generate_secure_bundle` simulates a wallet's `generate_signed_transaction`
# but doesn't bother with non-offer announcements
def generate_secure_bundle(
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


class TestOfferLifecycle:
    @pytest.mark.asyncio()
    async def test_complex_offer(self, cost_logger):
        async with sim_and_client() as (sim, sim_client):
            coins_needed: Dict[Optional[str], List[int]] = {
                None: [500, 400, 300],
                "red": [250, 100],
                "blue": [3000],
            }
            all_coins: Dict[Optional[str], List[Coin]] = await generate_coins(sim, sim_client, coins_needed)
            chia_coins: List[Coin] = all_coins[None]
            red_coins: List[Coin] = all_coins["red"]
            blue_coins: List[Coin] = all_coins["blue"]

            driver_dict: Dict[bytes32, PuzzleInfo] = {
                str_to_tail_hash("red"): PuzzleInfo(
                    {"type": AssetType.CAT.value, "tail": "0x" + str_to_tail_hash("red").hex()}
                ),
                str_to_tail_hash("blue"): PuzzleInfo(
                    {"type": AssetType.CAT.value, "tail": "0x" + str_to_tail_hash("blue").hex()}
                ),
            }

            driver_dict_as_infos: Dict[str, Any] = {}
            for key, value in driver_dict.items():
                driver_dict_as_infos[key.hex()] = value.info

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
            chia_announcements: List[Announcement] = Offer.calculate_announcements(chia_requested_payments, driver_dict)
            chia_secured_bundle: SpendBundle = generate_secure_bundle(chia_coins, chia_announcements, 1000)
            chia_offer = Offer(chia_requested_payments, chia_secured_bundle, driver_dict)
            assert not chia_offer.is_valid()

            # Create a RED Offer for XCH
            red_coins_1 = red_coins[0:1]
            red_coins_2 = red_coins[1:]
            red_requested_payments: Dict[Optional[bytes32], List[Payment]] = {
                None: [
                    Payment(acs_ph, 300, [b"red memo"]),
                    Payment(acs_ph, 350, [b"red memo"]),
                ]
            }

            red_requested_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = Offer.notarize_payments(
                red_requested_payments, red_coins_1
            )
            red_announcements: List[Announcement] = Offer.calculate_announcements(red_requested_payments, driver_dict)
            red_secured_bundle: SpendBundle = generate_secure_bundle(
                red_coins_1, red_announcements, sum([c.amount for c in red_coins_1]), tail_str="red"
            )
            red_offer = Offer(red_requested_payments, red_secured_bundle, driver_dict)
            assert not red_offer.is_valid()

            red_requested_payments_2: Dict[Optional[bytes32], List[Payment]] = {
                None: [
                    Payment(acs_ph, 50, [b"red memo"]),
                ]
            }

            red_requested_payments_2: Dict[Optional[bytes32], List[NotarizedPayment]] = Offer.notarize_payments(
                red_requested_payments_2, red_coins_2
            )
            red_announcements_2: List[Announcement] = Offer.calculate_announcements(
                red_requested_payments_2, driver_dict
            )
            red_secured_bundle_2: SpendBundle = generate_secure_bundle(
                red_coins_2, red_announcements_2, sum([c.amount for c in red_coins_2]), tail_str="red"
            )
            red_offer_2 = Offer(red_requested_payments_2, red_secured_bundle_2, driver_dict)
            assert not red_offer_2.is_valid()

            # Test aggregation of offers
            new_offer = Offer.aggregate([chia_offer, red_offer, red_offer_2])
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
            blue_announcements: List[Announcement] = Offer.calculate_announcements(blue_requested_payments, driver_dict)
            blue_secured_bundle: SpendBundle = generate_secure_bundle(
                blue_coins, blue_announcements, 2000, tail_str="blue"
            )
            blue_offer = Offer(blue_requested_payments, blue_secured_bundle, driver_dict)
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
                driver_dict_as_infos,
            )
            assert new_offer.get_pending_amounts() == {
                "xch": 1200,
                str_to_tail_hash("red").hex(): 350,
                str_to_tail_hash("blue").hex(): 3000,
            }
            assert new_offer.is_valid()

            # Test preventing TAIL from running during exchange
            blue_cat_puz: Program = construct_cat_puzzle(CAT_MOD, str_to_tail_hash("blue"), OFFER_MOD)
            blue_spend: CoinSpend = CoinSpend(
                Coin(bytes32(32), blue_cat_puz.get_tree_hash(), uint64(0)),
                blue_cat_puz,
                Program.to([[bytes32(32), [bytes32(32), 200, ["hey there"]]]]),
            )
            new_spends_list: List[CoinSpend] = [blue_spend, *new_offer.to_spend_bundle().coin_spends]
            tail_offer: Offer = Offer.from_spend_bundle(SpendBundle(new_spends_list, G2Element()))
            valid_spend = tail_offer.to_valid_spend(bytes32(32))
            real_blue_spend = [spend for spend in valid_spend.coin_spends if b"hey there" in bytes(spend)][0]
            real_blue_spend_replaced = replace(
                real_blue_spend,
                solution=real_blue_spend.solution.to_program().replace(
                    ffrfrf=Program.to(-113), ffrfrr=Program.to([str_to_tail("blue"), []])
                ),
            )
            valid_spend = SpendBundle(
                [real_blue_spend_replaced, *[spend for spend in valid_spend.coin_spends if spend != real_blue_spend]],
                G2Element(),
            )
            with pytest.raises(ValueError, match="clvm raise"):
                valid_spend.additions()

            # Test (de)serialization
            assert Offer.from_bytes(bytes(new_offer)) == new_offer

            # Test compression
            assert Offer.from_compressed(new_offer.compress()) == new_offer

            # Make sure we can actually spend the offer once it's valid
            arbitrage_ph: bytes32 = Program.to([3, [], [], 1]).get_tree_hash()
            offer_bundle: SpendBundle = new_offer.to_valid_spend(arbitrage_ph)

            result = await sim_client.push_tx(cost_logger.add_cost("Complex Offer", offer_bundle))
            assert result == (MempoolInclusionStatus.SUCCESS, None)
            await sim.farm_block()
