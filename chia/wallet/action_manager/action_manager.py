from __future__ import annotations

from dataclasses import dataclass
import logging
import time
import traceback
from blspy import AugSchemeMPL, G1Element, G2Element
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from typing_extensions import Literal

from chia.data_layer.data_layer_wallet import DataLayerWallet
from chia.protocols.wallet_protocol import CoinState
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.db_wrapper import DBWrapper2
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.wallet.db_wallet.db_wallet_puzzles import ACS_MU_PH
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.action_aliases import RequestPayment
from chia.wallet.trading.offer import NotarizedPayment, Offer
from chia.wallet.trading.trade_status import TradeStatus
from chia.wallet.trading.trade_store import TradeStore
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
import ast
import dataclasses
import inspect
import math

from blspy import AugSchemeMPL, G1Element, G2Element
from clvm_tools.binutils import disassemble
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from chia.data_layer.data_layer_wallet import UpdateMetadataDL
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint16, uint64
from chia.wallet.db_wallet.db_wallet_puzzles import create_host_fullpuz, GRAFTROOT_DL_OFFERS, RequireDLInclusion
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import cast_to_int, PuzzleInfo, Solver
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import solution_for_delegated_puzzle
from chia.wallet.puzzles.puzzle_utils import (
    make_assert_coin_announcement,
    make_create_coin_announcement,
    make_create_coin_condition,
    make_create_puzzle_announcement,
    make_reserve_fee_condition,
)
from chia.wallet.trading.action_aliases import (
    ActionAlias,
    AssertAnnouncement,
    DirectPayment,
    Fee,
    MakeAnnouncement,
    OfferedAmount,
    RequestPayment,
)
from chia.wallet.action_manager.coin_info import CoinInfo
from chia.wallet.trading.offer import ADD_WRAPPED_ANNOUNCEMENT, Offer, OFFER_MOD
from chia.wallet.trading.wallet_actions import WalletAction
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_protocol import WalletProtocol


# Using a place holder nonce to replace with the correct nonce at the end of spend construction (sha256 "bundle nonce")
BUNDLE_NONCE: bytes32 = bytes.fromhex("bba981ec36ebb2a0df2052893646b01ffb483128626b68e70f767f48fc5fbdbb")


def nonce_payments(action: Solver) -> Solver:
    if action["type"] == RequestPayment.name():
        if "nonce" not in action:
            return Solver({**action.info, "nonce": "0x" + BUNDLE_NONCE.hex()})
    else:
        return action


def nonce_coin_list(coins: List[Coin]) -> bytes32:
    sorted_coin_list: List[List[Union[bytes32, uint64]]] = [coin_as_list(c) for c in coins]
    return Program.to(sorted_coin_list).get_tree_hash()


@dataclass(frozen=True)
class WalletActionManager:
    """
    This class defines methods for creating spends from user input and performing actions on those spends
    once they are created.
    """
    wallet_state_manager: Any
    log: logging.Logger = logging.getLogger(__name__)

    async def spends_from_actions_and_infos(
        self,
        actions: List[Solver],
        bundle_actions: List[Solver],
        infos: List[CoinInfo],
        coin_specific_actions: Dict[Coin, List[Solver]],
        default_aliases: Dict[str, ActionAlias] = {},
    ) -> Tuple[List[Solver], List[CoinSpend]]:
        """
        Helper function for build_spend
        """
        actions_left: List[Solver] = [*actions, *bundle_actions]
        coin_spends: List[CoinSpend] = []
        for coin in infos:
            actions_left.extend(coin_specific_actions[coin.coin])
            actions_left, new_spend = await coin.create_spend_for_actions(actions_left, default_aliases)
            for specific_action in coin_specific_actions[coin.coin]:
                if specific_action in actions_left:
                    raise ValueError(
                        f"Coin with ID {coin.coin.name()} could not create specific conditions: ",
                        f"{coin_specific_actions[coin.coin]}",
                    )

            coin_spends.append(new_spend)

        if len(actions_left) > 0:
            for action in actions_left:
                if action not in bundle_actions:
                    raise ValueError(f"Could not complete action with specified coins {action}")

        return actions_left, coin_spends

    async def build_spend(self, request: Solver, previous_actions: List[CoinSpend] = []) -> SpendBundle:
        bundle_actions_left: List[Solver] = request["bundle_actions"]
        if "add_payment_nonces" not in request or request["add_payment_nonces"] != Program.to(None):
            bundle_actions_left = list(map(nonce_payments, bundle_actions_left))

        all_actions: List[Solver] = bundle_actions_left.copy()
        new_actions: List[CoinSpend] = previous_actions.copy()
        # Step 1: Determine which coins we need to complete the action
        for action_spec in request["actions"]:
            coin_spec: Solver = action_spec["with"]
            coin_infos: List[CoinInfo] = await self.wallet_state_manager.get_coin_infos_for_spec(coin_spec, new_actions)

            # Step 2: Calculate what announcement each coin will have to make/assert for bundle coherence
            coin_announcements: Dict[Coin, List[Solver]] = {}
            flattened_coin_list: List[Coin] = [ci.coin for ci in coin_infos]
            for i, coin in enumerate(flattened_coin_list):
                coin_announcements[coin] = [
                    Solver(
                        {
                            "type": "make_announcement",
                            "announcement_type": "coin",
                            "announcement_data": "0x" + BUNDLE_NONCE.hex(),
                        }
                    ),
                    Solver(
                        {
                            "type": "assert_announcement",
                            "announcement_type": "coin",
                            "announcement_data": "0x" + BUNDLE_NONCE.hex(),
                            # Using a placeholder to replace with the correct origin at the very end
                            # (sha256tree (coin_id . "next coin"))
                            "origin": "0x" + Program.to((coin.name(), "next coin")).get_tree_hash().hex(),
                        }
                    ),
                ]

            # Step 3: Construct all of the spends based on the actions specified
            actions: List[Solver] = action_spec["do"]
            if "change" not in request or request["change"] != Program.to(None):
                selected_amount: int = sum(ci.coin.amount for ci in coin_infos)
                specified_amount: int = (
                    0 if "amount" not in action_spec["with"] else cast_to_int(action_spec["with"]["amount"])
                )
                if selected_amount - specified_amount > 0:
                    actions.append(
                        DirectPayment(
                            Payment(
                                await self.wallet_state_manager.main_wallet.get_new_puzzlehash(),
                                uint64(selected_amount - specified_amount),
                                [],
                            ),
                            [],
                        ).to_solver()
                    )

            if "add_payment_nonces" not in request or request["add_payment_nonces"] != Program.to(None):
                actions = list(map(nonce_payments, actions))

            all_actions.extend(actions)

            bundle_actions_left, coin_spends = await self.spends_from_actions_and_infos(
                actions, bundle_actions_left, coin_infos, coin_announcements, self.wallet_state_manager.action_aliases
            )

            new_actions.extend(coin_spends)

        spent_coins: List[Coin] = [cs.coin for cs in new_actions]
        replacement_nonce: bytes32 = nonce_coin_list(spent_coins)

        strings_to_replace: List[Tuple[bytes32, bytes32]] = []
        for action in all_actions:
            if action["type"] == RequestPayment.name() and action["nonce"] == BUNDLE_NONCE:
                payment_action: RequestPayment = RequestPayment.from_solver(action)
                nonced_payment: RequestPayment = dataclasses.replace(payment_action, nonce=replacement_nonce)
                strings_to_replace.append(
                    (
                        payment_action.construct_announcement_assertion().name(),
                        nonced_payment.construct_announcement_assertion().name(),
                    )
                )

        nonced_new_actions: List[CoinSpend] = []
        for i, spend in enumerate(new_actions):
            next_coin: Coin = spent_coins[0 if i == len(spent_coins) - 1 else i + 1]
            fake_origin_info: bytes32 = Program.to((spend.coin.name(), "next coin")).get_tree_hash()
            assertion_to_replace: bytes32 = Announcement(fake_origin_info, BUNDLE_NONCE).name()
            replacement_assertion: bytes32 = Announcement(next_coin.name(), replacement_nonce).name()

            spend_bytes: bytes = bytes(spend)
            spend_bytes = spend_bytes.replace(BUNDLE_NONCE, replacement_nonce).replace(
                assertion_to_replace, replacement_assertion
            )
            for string, replacement in strings_to_replace:
                spend_bytes = spend_bytes.replace(string, replacement)

            new_spend = CoinSpend.from_bytes(spend_bytes)
            nonced_new_actions.append(new_spend)

        return SpendBundle(nonced_new_actions, G2Element())

    async def deconstruct_spend(self, bundle: SpendBundle) -> Solver:
        final_actions: List[Solver] = []
        final_signatures: List[Tuple[bytes32, G1Element, bytes, bool]] = []
        for spend in bundle.coin_spends:
            # Step 1: Get any wallets that claim to identify the puzzle
            matches: List[Tuple[CoinInfo, List[WalletAction], List[Tuple[G1Element, bytes, bool]]]] = []
            mod, curried_args = spend.puzzle_reveal.uncurry()
            for wallet in self.wallet_state_manager.outer_wallets:
                match = await wallet.match_spend(self.wallet_state_manager, spend, mod, curried_args)
                if match is not None:
                    matches.append(match)

            if matches == []:
                continue  # We skip spends we can't identify, if they're important, the spend will fail on chain
            elif len(matches) > 1:
                # QUESTION: Should we support this? Giving multiple interpretations?
                raise ValueError(f"There are multiple ways to describe spend with coin: {spend.coin}")

            # Step 2: Attempt to find matching aliases for the actions
            info, actions, sigs = matches[0]
            actions = info.alias_actions(actions, self.wallet_state_manager.action_aliases)

            final_actions.append(Solver({"with": info.description, "do": [action.to_solver() for action in actions]}))
            final_signatures.extend([(info.coin.name(), *sig) for sig in sigs])

        # Step 4: Attempt to group coins in some way
        asset_types: List[List[Solver]] = []
        amounts: List[int] = []
        action_lists: List[List[Solver]] = []
        for action in final_actions:
            types: List[Solver] = action["with"]["asset_types"] if "asset_types" in action["with"] else []
            if types in asset_types:
                index = asset_types.index(types)
                amounts[index] += cast_to_int(action["with"]["amount"])
                action_lists[index].extend(action["do"])
            else:
                asset_types.append(types)
                amounts.append(cast_to_int(action["with"]["amount"]))
                action_lists.append(action["do"])

        grouped_actions: List[Solver] = []
        for typs, amount, do in zip(asset_types, amounts, action_lists):
            grouped_actions.append(Solver({"with": {"asset_types": typs, "amount": amount}, "do": do}))

        return Solver(
            {
                "actions": grouped_actions,
                "bundle_actions": [],
                "signatures": [
                    {
                        "coin_id": "0x" + coin_id.hex(),
                        "pubkey": "0x" + bytes(pubkey).hex(),
                        "data": "0x" + msg.hex(),
                        "me": "1" if me else "()",
                    }
                    for coin_id, pubkey, msg, me in final_signatures
                ],
            }
        )

    async def sign_spend(self, unsigned_spend: SpendBundle) -> SpendBundle:
        signature_info: List[Tuple[bytes32, G1Element, bytes, bool]] = [
            (
                bytes32(solver["coin_id"]),
                G1Element.from_bytes(solver["pubkey"]),
                solver["data"],
                solver["me"] != Program.to(None),
            )
            for solver in (await self.deconstruct_spend(unsigned_spend))["signatures"]
        ]

        signatures: List[G2Element] = []
        for coin_id, pk, msg, me in signature_info:
            secret_key = self.wallet_state_manager.main_wallet.secret_key_store.secret_key_for_public_key(pk)
            if secret_key is not None:
                assert bytes(secret_key.get_g1()) == bytes(pk)
                if me:
                    msg_to_sign: bytes = msg + coin_id + self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
                else:
                    msg_to_sign = msg
                signature = AugSchemeMPL.sign(secret_key, msg_to_sign)
                signatures.append(signature)

        return SpendBundle(unsigned_spend.coin_spends, AugSchemeMPL.aggregate(signatures))

    async def solve_spend(self, bundle: SpendBundle, environment: Solver) -> SpendBundle:
        # Step 1: Inject all of the spends into the environment
        environment = Solver(
            {
                "spends": [
                    {
                        "coin": {
                            "parent_coin_info": "0x" + spend.coin.parent_coin_info.hex(),
                            "puzzle_hash": "0x" + spend.coin.puzzle_hash.hex(),
                            "amount": str(spend.coin.amount),
                        },
                        "puzzle_reveal": disassemble(spend.puzzle_reveal.to_program()),
                        "solution": disassemble(spend.puzzle_reveal.to_program()),
                    }
                    for spend in bundle.coin_spends
                ],
                **environment.info,
            }
        )

        new_spends: List[CoinSpend] = []
        for spend in bundle.coin_spends:
            # Step 2: Get any wallets that claim to identify the puzzle
            matches: List[Tuple[CoinInfo, List[WalletAction]]] = []
            mod, curried_args = spend.puzzle_reveal.uncurry()
            for wallet in self.wallet_state_manager.outer_wallets:
                match = await wallet.match_spend(self.wallet_state_manager, spend, mod, curried_args)
                if match is not None:
                    matches.append(match)

            if matches == []:
                continue  # We skip spends we can't identify, if they're important, the spend will fail on chain
            elif len(matches) > 1:
                # QUESTION: Should we support this? Giving multiple interpretations?
                raise ValueError(f"There are multiple ways to describe spend with coin: {spend.coin}")

            # Step 3: Attempt to find matching aliases for the actions
            info, actions, _ = matches[0]
            actions = info.alias_actions(actions, self.wallet_state_manager.action_aliases)
            # Step 4: Augment each action with the environment
            augmented_actions: List[Solver] = [action.augment(environment).to_solver() for action in actions]
            temp_spend = spend
            remaining_actions, spend = await info.create_spend_for_actions(
                augmented_actions, self.wallet_state_manager.action_aliases, optimize=True
            )
            if len(remaining_actions) > 0:
                raise ValueError(
                    "Attempting to solve the spends with specified environment resulted in being unable to spend a coin"
                )
            new_spends.append(spend)

        return SpendBundle(new_spends, bundle.aggregated_signature)