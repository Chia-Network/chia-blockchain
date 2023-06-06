from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Tuple, Type, Union

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
from chia.wallet.action_manager.protocols import ActionAlias, SpendDescription, WalletAction
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

    def spends_from_actions_and_infos(
        self,
        actions: List[Solver],
        bundle_actions: List[Solver],
        infos: List[SpendDescription],
        coin_specific_actions: Dict[Coin, List[Solver]],
        default_aliases: Dict[str, Type[ActionAlias]] = {},
        environment: Solver = Solver({}),
    ) -> Tuple[List[Solver], List[SpendDescription]]:
        """
        Helper function for build_spend
        """
        actions_left: List[Solver] = [*actions, *bundle_actions]
        spend_descriptions: List[SpendDescription] = []
        for spend in infos:
            actions_left.extend(coin_specific_actions[spend.coin])
            actions_left, new_description = spend.apply_actions(
                actions_left, default_aliases=default_aliases, environment=environment
            )
            for specific_action in coin_specific_actions[spend.coin]:
                if specific_action in actions_left:
                    raise ValueError(
                        f"Coin with ID {spend.coin.name()} could not create specific conditions: ",
                        f"{coin_specific_actions[spend.coin]}",
                    )

            spend_descriptions.append(new_description)

        if len(actions_left) > 0:
            for action in actions_left:
                if action not in bundle_actions:
                    raise ValueError(f"Could not complete action with specified coins {action}")

        return actions_left, spend_descriptions

    async def build_spend(
        self, request: Solver, previous_spends: List[SpendDescription] = [], environment: Solver = Solver({})
    ) -> SpendBundle:
        """
        This is the main method that turns request -> spend bundle
        """

        # we nonce all requested payments by default
        bundle_actions_left: List[Solver] = request["bundle_actions"]
        if "add_payment_nonces" not in request or request["add_payment_nonces"] != Program.to(None):
            bundle_actions_left = list(map(nonce_payments, bundle_actions_left))

        all_actions: List[Solver] = bundle_actions_left.copy()
        # We might be building a spend from the outputs of another spend
        all_descriptions: List[SpendDescription] = previous_spends.copy()
        new_spends: List[CoinSpend] = []
        for action_spec in request["actions"]:
            # Step 1: Determine which coins we need to complete the action
            coin_spec: Solver = action_spec["with"]
            coin_infos: List[SpendDescription] = await self.wallet_state_manager.get_coin_infos_for_spec(
                coin_spec, all_descriptions
            )

            # Step 2: Calculate what announcement each coin will have to make/assert for bundle coherence
            coin_announcements: Dict[Coin, List[Solver]] = {}
            flattened_coin_list: List[Coin] = [ci.coin for ci in coin_infos]
            for coin in flattened_coin_list:
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

            # Step 3: Based on the amount specified and the coins selected, add a change action by default
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
                                # Maybe the change_ph should be configurable too?
                                await self.wallet_state_manager.main_wallet.get_new_puzzlehash(),
                                uint64(selected_amount - specified_amount),
                                [],
                            ),
                            [],
                        ).to_solver()
                    )

            # we nonce all requested payments by default
            if "add_payment_nonces" not in request or request["add_payment_nonces"] != Program.to(None):
                actions = list(map(nonce_payments, actions))

            all_actions.extend(actions)

            # Step 4: Build a CoinSpend for each coin
            bundle_actions_left, spend_descriptions = self.spends_from_actions_and_infos(
                actions,
                bundle_actions_left,
                coin_infos,
                coin_announcements,
                self.wallet_state_manager.action_aliases,
                environment,
            )

            new_spends.extend([spend.spend(environment=environment) for spend in spend_descriptions])
            all_descriptions.extend(spend_descriptions)

        if len(bundle_actions_left) > 0:
            raise ValueError(f"Could not handle all bundle actions: {bundle_actions_left}")

        # Now we pay our debt for using dummy nonces before by finding out what actual nonces we needed to use
        spent_coins: List[Coin] = [cs.coin for cs in new_spends]
        replacement_nonce: bytes32 = nonce_coin_list(spent_coins)

        # Take note of all of the announcements we used dummy nonces for and what they should be
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

        # Operate directly on the serialized bytes to sub in the necessary replacements
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

    def deconstruct_spend(self, bundle: SpendBundle) -> Solver:
        """
        This method should ideally be the inverse of build_spend, however, there's no way to know which actions were
        specified as "bundle actions" so the returned summary will likely be different than the original
        """
        final_actions: List[Solver] = []
        final_signatures: List[Tuple[bytes32, G1Element, bytes, bool]] = []
        for spend in bundle.coin_spends:
            matches: List[SpendDescription] = SpendDescription.match(spend, self.wallet_state_manager)

            if matches == []:
                continue  # We skip spends we can't identify, if they're important, the spend will fail on chain
            elif len(matches) > 1:
                # QUESTION: Should we support this? Giving multiple interpretations?
                raise ValueError(f"There are multiple ways to describe spend with coin: {spend.coin}")

            spend_description: SpendDescription = matches[0]
            actions = spend_description.get_all_actions(self.wallet_state_manager.action_aliases)

            final_actions.append(
                Solver(
                    {"with": spend_description.get_full_description(), "do": [action.to_solver() for action in actions]}
                )
            )

            all_signature_info: List[Tuple[G1Element, bytes, bool]] = spend_description.get_all_signatures()
            # Throw the coin name in with the required signatures so that the signing code can do AGG_SIG_MEs
            final_signatures.extend([(bytes32(spend_description.coin.name()), *sig) for sig in all_signature_info])

        # Attempt to group coins in some way

        # Currently, the best attempt is to assume anything with the same asset type is fungible
        # and consolidate the amounts/actions
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

    def sign_spend(self, unsigned_spend: SpendBundle) -> SpendBundle:
        """
        Isolated away from the spend building process, here is where we sign the spend with our pubkey.
        In the future, this likely moves to a different device entirely.
        """
        signature_info: List[Tuple[bytes32, G1Element, bytes, bool]] = [
            (
                bytes32(solver["coin_id"]),
                G1Element.from_bytes(solver["pubkey"]),
                solver["data"],
                solver["me"] != Program.to(None),
            )
            for solver in (self.deconstruct_spend(unsigned_spend))["signatures"]
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

    def solve_spend(self, bundle: SpendBundle, environment: Solver) -> SpendBundle:
        """
        Given a bundle and an environment, this method makes the spend ready to go to chain

        A spend, once solved, is not guaranteed to be parsable be methods like deconstruct_spend
        """
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
                **environment.info,  # user environment always has priority
            }
        )

        spend_descriptions: List[SpendDescription] = []
        for spend in bundle.coin_spends:
            # Step 2: Get any wallets that claim to identify the puzzle
            matches: List[SpendDescription] = SpendDescription.match(spend, self.wallet_state_manager)

            if matches == []:
                continue  # We skip spends we can't identify, if they're important, the spend will fail on chain
            elif len(matches) > 1:
                # QUESTION: Should we support this? Giving multiple interpretations?
                raise ValueError(f"There are multiple ways to describe spend with coin: {spend.coin}")

            spend_descriptions.append(matches[0])

        # Step 3: Include all of the descriptions in the environment as well
        environment = Solver(
            {
                "spend_descriptions": [
                    {
                        "id": "0x" + spend.coin.name().hex(),
                        "outer": {
                            "actions": [action.to_solver() for action in spend.outer_solution_description.actions],
                            "coin_description": spend.outer_puzzle_description.coin_description,
                            "environment": spend.outer_solution_description.environment,
                        },
                        "inner": {
                            "actions": [action.to_solver() for action in spend.inner_solution_description.actions],
                            "coin_description": spend.inner_puzzle_description.coin_description,
                            "environment": spend.inner_solution_description.environment,
                        },
                    }
                    for spend in spend_descriptions
                ],
                **environment.info,  # user environment always has priority
            }
        )

        new_spends: List[CoinSpend] = []
        for description in spend_descriptions:
            actions: List[WalletAction] = description.get_all_actions(self.wallet_state_manager.action_aliases)
            # Step 4: Augment each action with the global environment
            augmented_actions: List[Solver] = [action.augment(environment).to_solver() for action in actions]
            remaining_actions, new_description = description.apply_actions(
                augmented_actions, self.wallet_state_manager.action_aliases, environment=environment
            )
            if len(remaining_actions) > 0:
                raise ValueError(
                    "Attempting to solve the spends with specified environment resulted in being unable to spend a coin"
                )
            new_spends.append(new_description.spend(environment=environment, optimize=True))

        return SpendBundle(new_spends, bundle.aggregated_signature)
