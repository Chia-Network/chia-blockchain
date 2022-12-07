from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional, Tuple, Type, Union

from blspy import AugSchemeMPL, G1Element, G2Element
from clvm_tools.binutils import disassemble

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.wallet.action_manager.action_aliases import DirectPayment, RequestPayment
from chia.wallet.action_manager.coin_info import CoinInfo
from chia.wallet.action_manager.protocols import ActionAlias, PuzzleSolutionDescription, SpendDescription
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import Solver, cast_to_int

# Using a place holder nonce to replace with the correct nonce at the end of spend construction (sha256 "bundle nonce")
BUNDLE_NONCE: bytes32 = bytes32.from_hexstr("bba981ec36ebb2a0df2052893646b01ffb483128626b68e70f767f48fc5fbdbb")


def nonce_payments(action: Solver) -> Solver:
    if action["type"] == RequestPayment.name() and "nonce" not in action:
        return Solver({**action.info, "nonce": "0x" + BUNDLE_NONCE.hex()})
    else:
        return action


def nonce_coin_list(coins: List[Coin]) -> bytes32:
    sorted_coin_list: List[List[Union[bytes32, uint64]]] = [coin_as_list(c) for c in sorted(coins, key=Coin.name)]
    as_program: Program = Program.to(sorted_coin_list)
    return as_program.get_tree_hash()


@dataclasses.dataclass(frozen=True)
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
        default_aliases: Dict[str, Type[ActionAlias]] = {},
        environment: Solver = Solver({}),
    ) -> Tuple[List[Solver], List[CoinSpend], List[SpendDescription]]:
        """
        Helper function for build_spend
        """
        actions_left: List[Solver] = [*actions, *bundle_actions]
        coin_spends: List[CoinSpend] = []
        spend_descriptions: List[SpendDescription] = []
        for coin in infos:
            actions_left.extend(coin_specific_actions[coin.coin])
            actions_left, environment, new_spend, new_description = await coin.create_spend_for_actions(
                actions_left, default_aliases
            )
            for specific_action in coin_specific_actions[coin.coin]:
                if specific_action in actions_left:
                    raise ValueError(
                        f"Coin with ID {coin.coin.name()} could not create specific conditions: ",
                        f"{coin_specific_actions[coin.coin]}",
                    )

            coin_spends.append(new_spend)
            spend_descriptions.append(new_description)

        if len(actions_left) > 0:
            for action in actions_left:
                if action not in bundle_actions:
                    raise ValueError(f"Could not complete action with specified coins {action}")

        return actions_left, coin_spends, spend_descriptions

    async def build_spend(self, request: Solver, previous_spends: List[SpendDescription] = []) -> SpendBundle:
        bundle_actions_left: List[Solver] = request["bundle_actions"]
        if "add_payment_nonces" not in request or request["add_payment_nonces"] != Program.to(None):
            bundle_actions_left = list(map(nonce_payments, bundle_actions_left))

        all_actions: List[Solver] = bundle_actions_left.copy()
        all_descriptions: List[SpendDescription] = previous_spends.copy()
        new_spends: List[CoinSpend] = []
        # Step 1: Determine which coins we need to complete the action
        for action_spec in request["actions"]:
            coin_spec: Solver = action_spec["with"]
            coin_infos: List[CoinInfo] = await self.wallet_state_manager.get_coin_infos_for_spec(
                coin_spec, all_descriptions
            )

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

            bundle_actions_left, coin_spends, spend_descriptions = await self.spends_from_actions_and_infos(
                actions,
                bundle_actions_left,
                coin_infos,
                coin_announcements,
                self.wallet_state_manager.action_aliases,
                Solver({}),
            )

            new_spends.extend(coin_spends)
            all_descriptions.extend(spend_descriptions)

        if len(bundle_actions_left) > 0:
            raise ValueError(f"Could not handle all bundle actions: {bundle_actions_left}")

        spent_coins: List[Coin] = [cs.coin for cs in new_spends]
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

        nonced_new_spends: List[CoinSpend] = []
        for i, spend in enumerate(new_spends):
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
            nonced_new_spends.append(new_spend)

        return SpendBundle(nonced_new_spends, G2Element())

    async def deconstruct_spend(self, bundle: SpendBundle) -> Solver:
        final_actions: List[Solver] = []
        final_signatures: List[Tuple[bytes32, G1Element, bytes, bool]] = []
        for spend in bundle.coin_spends:
            # Step 1: Get any wallets that claim to identify the puzzle
            matches: List[SpendDescription] = []
            mod, curried_args = spend.puzzle_reveal.uncurry()
            for outer_wallet in self.wallet_state_manager.outer_wallets:
                outer_match: Optional[
                    Tuple[PuzzleSolutionDescription, Program, Program]
                ] = await outer_wallet.match_puzzle_and_solution(spend, mod, curried_args)
                if outer_match is not None:
                    outer_description, inner_puzzle, inner_solution = outer_match
                    mod, curried_args = inner_puzzle.uncurry()
                    for inner_wallet in self.wallet_state_manager.inner_wallets:
                        inner_description: Optional[
                            PuzzleSolutionDescription
                        ] = await inner_wallet.match_puzzle_and_solution(
                            spend.coin, inner_puzzle, inner_solution, mod, curried_args
                        )
                        if inner_description is not None:
                            matches.append(SpendDescription(spend.coin, outer_description, inner_description))

            if matches == []:
                continue  # We skip spends we can't identify, if they're important, the spend will fail on chain
            elif len(matches) > 1:
                # QUESTION: Should we support this? Giving multiple interpretations?
                raise ValueError(f"There are multiple ways to describe spend with coin: {spend.coin}")

            # Step 2: Attempt to find matching aliases for the actions
            spend_description: SpendDescription = matches[0]
            info = CoinInfo.from_spend_description(spend_description)
            actions = info.alias_actions(spend_description.get_all_actions(), self.wallet_state_manager.action_aliases)

            final_actions.append(Solver({"with": info.description, "do": [action.to_solver() for action in actions]}))

            all_signature_info: List[Tuple[G1Element, bytes, bool]] = spend_description.get_all_signatures()
            final_signatures.extend([(bytes32(info.coin.name()), *sig) for sig in all_signature_info])

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
                        "solution": disassemble(spend.solution.to_program()),
                    }
                    for spend in bundle.coin_spends
                ],
                **environment.info,
            }
        )

        spend_descriptions: List[SpendDescription] = []
        for spend in bundle.coin_spends:
            # Step 2: Get any wallets that claim to identify the puzzle
            matches: List[SpendDescription] = []
            mod, curried_args = spend.puzzle_reveal.uncurry()
            for outer_wallet in self.wallet_state_manager.outer_wallets:
                outer_match: Optional[
                    Tuple[PuzzleSolutionDescription, Program, Program]
                ] = await outer_wallet.match_puzzle_and_solution(spend, mod, curried_args)
                if outer_match is not None:
                    outer_description, inner_puzzle, inner_solution = outer_match
                    mod, curried_args = inner_puzzle.uncurry()
                    for inner_wallet in self.wallet_state_manager.inner_wallets:
                        inner_description: Optional[
                            PuzzleSolutionDescription
                        ] = await inner_wallet.match_puzzle_and_solution(
                            spend.coin, inner_puzzle, inner_solution, mod, curried_args
                        )
                        if inner_description is not None:
                            matches.append(SpendDescription(spend.coin, outer_description, inner_description))

            if matches == []:
                continue  # We skip spends we can't identify, if they're important, the spend will fail on chain
            elif len(matches) > 1:
                # QUESTION: Should we support this? Giving multiple interpretations?
                raise ValueError(f"There are multiple ways to describe spend with coin: {spend.coin}")

            spend_descriptions.append(matches[0])

        environment = Solver(
            {
                **environment.info,
                "spend_descriptions": [
                    {
                        "id": "0x" + spend.coin.name().hex(),
                        "outer": {
                            "actions": [action.to_solver() for action in spend.outer_description.actions],
                            "signatures_required": [
                                {
                                    "pubkey": "0x" + bytes(pubkey).hex(),
                                    "data": "0x" + data.hex(),
                                    "me": "1" if me else "()",
                                }
                                for pubkey, data, me in spend.outer_description.signatures_required
                            ],
                            "coin_description": spend.outer_description.coin_description,
                            "environment": spend.outer_description.environment,
                        },
                        "inner": {
                            "actions": [action.to_solver() for action in spend.inner_description.actions],
                            "signatures_required": [
                                {
                                    "pubkey": "0x" + bytes(pubkey).hex(),
                                    "data": "0x" + data.hex(),
                                    "me": "1" if me else "()",
                                }
                                for pubkey, data, me in spend.inner_description.signatures_required
                            ],
                            "coin_description": spend.inner_description.coin_description,
                            "environment": spend.inner_description.environment,
                        },
                    }
                    for spend in spend_descriptions
                ],
            }
        )

        new_spends: List[CoinSpend] = []
        for description in spend_descriptions:
            # Step 3: Attempt to find matching aliases for the actions
            info = CoinInfo.from_spend_description(description)
            actions = info.alias_actions(description.get_all_actions(), self.wallet_state_manager.action_aliases)
            environment = Solver({**environment.info, **description.get_full_environment().info})
            # Step 4: Augment each action with the environment
            augmented_actions: List[Solver] = [action.augment(environment).to_solver() for action in actions]
            remaining_actions, environment, spend, _ = await info.create_spend_for_actions(
                augmented_actions, self.wallet_state_manager.action_aliases, environment, optimize=True
            )
            if len(remaining_actions) > 0:
                raise ValueError(
                    "Attempting to solve the spends with specified environment resulted in being unable to spend a coin"
                )
            new_spends.append(spend)

        return SpendBundle(new_spends, bundle.aggregated_signature)
