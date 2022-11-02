import dataclasses
import inspect
import math

from blspy import AugSchemeMPL, G1Element, G2Element
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint16, uint64
from chia.wallet.db_wallet.db_wallet_puzzles import create_host_fullpuz, GRAFTROOT_DL_OFFERS
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
    AssertAnnouncement,
    DirectPayment,
    Fee,
    MakeAnnouncement,
    OfferedAmount,
    RequestPayment,
)
from chia.wallet.trading.offer import ADD_WRAPPED_ANNOUNCEMENT, Offer, OFFER_MOD
from chia.wallet.trading.wallet_actions import WalletAction
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_protocol import WalletProtocol


async def old_request_to_new(
    wallet_state_manager: Any,
    offer_dict: Dict[Optional[bytes32], int],
    driver_dict: Dict[bytes32, PuzzleInfo],
    solver: Solver,
    fee: uint64,
) -> Tuple[Solver, Dict[bytes32, PuzzleInfo]]:
    """
    This method takes an old style offer dictionary and converts it to a new style action specification
    """
    final_solver: Dict[str, Any] = solver.info

    offered_assets: Dict[Optional[bytes32], int] = {k: v for k, v in offer_dict.items() if v < 0}
    requested_assets: Dict[Optional[bytes32], int] = {k: v for k, v in offer_dict.items() if v > 0}

    # When offers first came out, they only supported CATs and driver_dict did not exist
    # We need to fill in any requested assets that do not exist in driver_dict already as CATs
    cat_assets: Dict[bytes32, PuzzleInfo] = {
        key: PuzzleInfo({"type": AssetType.CAT.value, "tail": "0x" + key.hex()})
        for key in requested_assets
        if key is not None and key not in driver_dict
    }
    driver_dict.update(cat_assets)

    # Keep track of the DL assets since they show up under the offered asset's name
    dl_dependencies: List[Solver] = []
    # DLs need to do an announcement after they update so we'll keep track of those to add at the end
    additional_actions: List[Dict[str, Any]] = []

    final_solver.setdefault("actions", [])
    for asset_id, amount in offered_assets.items():

        # Get the wallet
        if asset_id is None:
            wallet = wallet_state_manager.main_wallet
        else:
            wallet = await wallet_state_manager.get_wallet_for_asset_id(asset_id.hex())

        # We need to fill in driver dict entries that we can and raise on discrepencies
        if callable(getattr(wallet, "get_puzzle_info", None)):
            puzzle_driver: PuzzleInfo = await wallet.get_puzzle_info(asset_id)
            if asset_id in driver_dict and driver_dict[asset_id] != puzzle_driver:
                raise ValueError(f"driver_dict specified {driver_dict[asset_id]}, was expecting {puzzle_driver}")
            else:
                driver_dict[asset_id] = puzzle_driver
        elif asset_id is not None:
            raise ValueError(f"Wallet for asset id {asset_id} is not properly integrated for trading")

        # Build the specification for the asset type we want to offer
        asset_types: List[Dict[str, Any]] = []
        if asset_id is not None:
            puzzle_info: PuzzleInfo = driver_dict[asset_id]
            while True:
                type_description: Dict[str, Any] = puzzle_info.info
                if "also" in type_description:
                    del type_description["also"]
                    puzzle_info = puzzle_info.also()
                    asset_types.append(type_description)
                else:
                    asset_types.append(type_description)
                    break

        # We're passing everything in as a dictionary now instead of a single asset_id/amount pair
        offered_asset: Dict[str, Any] = {"with": {"asset_types": asset_types, "amount": str(abs(amount))}, "do": []}

        try:
            if asset_id is not None:
                try:
                    this_solver: Optional[Solver] = solver[asset_id.hex()]
                except KeyError:
                    this_solver = solver["0x" + asset_id.hex()]
            else:
                this_solver = solver['']
        except KeyError:
            this_solver = None

        # Take note of of the dl dependencies if there are any
        if "dependencies" in this_solver:
            dl_dependencies.append(
                {
                    "type": "require_dl_inclusion",
                    "launcher_ids": ["0x" + dep["launcher_id"].hex() for dep in this_solver["dependencies"]],
                    "values_to_prove": [
                        ["0x" + v.hex() for v in dep["values_to_prove"]] for dep in this_solver["dependencies"]
                    ],
                }
            )

        if wallet.type() == WalletType.DATA_LAYER:
            # Data Layer offers initially were metadata updates, so we shouldn't allow any kind of sending
            assert this_solver is not None
            offered_asset["do"] = [
                [
                    {
                        "type": "update_metadata",
                        # The request used to require "new_root" be in solver so the potential KeyError is good
                        "new_metadata": "0x" + this_solver["new_root"].hex(),
                    }
                ],
            ]

            additional_actions.append(
                {
                    "with": offered_asset["with"],
                    "do": [
                        MakeAnnouncement("puzzle", Program.to(b"$")).to_solver(),
                    ],
                }
            )
        else:
            action_batch = [
                # This is the parallel to just specifying an amount to offer
                OfferedAmount(abs(amount)).to_solver()
            ]
            # Royalty payments are automatically worked in when you offer fungible assets for an NFT
            if asset_id is None or driver_dict[asset_id].type() != AssetType.SINGLETON.value:
                for payment in calculate_royalty_payments(requested_assets, abs(amount), driver_dict):
                    action_batch.append(OfferedAmount(payment.amount).to_solver())
                    offered_asset["with"]["amount"] = str(
                        cast_to_int(Solver(offered_asset["with"])["amount"]) + payment.amount
                    )

            # The standard XCH should pay the fee
            if asset_id is None and fee > 0:
                action_batch.append(Fee(fee).to_solver())
                offered_asset["with"]["amount"] = str(cast_to_int(Solver(offered_asset["with"])["amount"]) + fee)

            # Provenant NFTs by default clear their ownership on transfer
            elif driver_dict[asset_id].check_type(
                [
                    AssetType.SINGLETON.value,
                    AssetType.METADATA.value,
                    AssetType.OWNERSHIP.value,
                ]
            ):
                action_batch.append(
                    {
                        "type": "update_state",
                        "update": {
                            "new_owner": "()",
                        },
                    }
                )
            offered_asset["do"] = action_batch

        final_solver["actions"].append(offered_asset)

    final_solver["actions"].extend(additional_actions)

    # Make sure the fee gets into the solver
    if None not in offer_dict and fee > 0:
        final_solver["actions"].append(
            {
                "with": {"amount": fee},
                "do": [
                    Fee(fee).to_solver(),
                ],
            }
        )

    # Now lets use the requested items to fill in the bundle dependencies
    final_solver.setdefault("bundle_actions", [])
    final_solver["bundle_actions"].extend(dl_dependencies)
    for asset_id, amount in requested_assets.items():
        if asset_id is None:
            wallet = wallet_state_manager.main_wallet
        else:
            wallet = await wallet_state_manager.get_wallet_for_asset_id(asset_id.hex())

        p2_ph = await wallet_state_manager.main_wallet.get_new_puzzlehash()

        if wallet.type() != WalletType.DATA_LAYER:  # DL singletons are not sent as part of offers by default
            # Asset/amount pairs are assumed to mean requested_payments
            asset_types: List[Solver] = []
            asset_driver = driver_dict[asset_id]
            while True:
                if asset_driver.type() == AssetType.CAT.value:
                    asset_types.append(
                        Solver(
                            {
                                "type": AssetType.CAT.value,
                                "asset_id": asset_driver["tail"],
                            }
                        )
                    )
                elif asset_driver.type() == AssetType.SINGLETON.value:
                    asset_types.append(
                        Solver(
                            {
                                "type": AssetType.SINGLETON.value,
                                "launcher_id": asset_driver["launcher_id"],
                                "launcher_ph": asset_driver["launcher_ph"],
                            }
                        )
                    )
                elif asset_driver.type() == AssetType.METADATA.value:
                    asset_types.append(
                        Solver(
                            {
                                "type": AssetType.METADATA.value,
                                "metadata": asset_driver["metadata"],
                                "metadata_updater_hash": asset_driver["updater_hash"],
                            }
                        )
                    )
                elif asset_driver.type() == AssetType.OWNERSHIP.value:
                    asset_types.append(
                        Solver(
                            {
                                "type": AssetType.OWNERSHIP.value,
                                "owner": asset_driver["owner"],
                                "transfer_program": asset_driver["transfer_program"],
                            }
                        )
                    )

                if asset_driver.also() is None:
                    break
                else:
                    asset_driver = asset_driver.also()

            final_solver["dependencies"].append(
                {
                    "type": "requested_payment",
                    "asset_types": asset_types,
                    "payments": [
                        {
                            "puzhash": "0x" + p2_ph.hex(),
                            "amount": str(amount),
                            "memos": ["0x" + p2_ph.hex()],
                        }
                    ],
                }
            )

        # Also request the royalty payment as a formality
        if asset_id is None or driver_dict[asset_id].type() != AssetType.SINGLETON.value:
            final_solver["dependencies"].extend(
                [
                    {
                        "type": "requested_payment",
                        "asset_id": "0x" + asset_id.hex(),
                        "nonce": "0x" + asset_id.hex(),
                        "payments": [
                            {
                                "puzhash": "0x" + payment.address.hex(),
                                "amount": str(payment.amount),
                                "memos": ["0x" + memo.hex() for memo in payment.memos],
                            }
                        ],
                    }
                    for payment in calculate_royalty_payments(offered_assets, amount, driver_dict)
                ]
            )

    # Finally, we need to special case any stuff that the solver was previously used for
    if "solving_information" not in final_solver:
        final_solver.setdefault("solving_information", [])

    return Solver(final_solver)


def calculate_royalty_payments(
    requested_assets: Dict[Optional[bytes32], int],
    offered_amount: int,
    driver_dict: Dict[bytes32, PuzzleInfo],
) -> List[Payment]:
    """
    Given assets on one side of a trade and an amount being paid for them, return the payments that must be made
    """
    # First, let's take note of all the royalty enabled NFTs
    royalty_nft_assets: List[bytes32] = [
        asset
        for asset in requested_assets
        if asset is not None
        and driver_dict[asset].check_type(  # check if asset is an Royalty Enabled NFT
            [
                AssetType.SINGLETON.value,
                AssetType.METADATA.value,
                AssetType.OWNERSHIP.value,
            ]
        )
    ]

    # Then build what royalty payments we need to make
    royalty_payments: List[Payment] = []
    for asset_id in royalty_nft_assets:
        transfer_info = driver_dict[asset_id].also().also()  # type: ignore
        assert isinstance(transfer_info, PuzzleInfo)
        address: bytes32 = bytes32(transfer_info["transfer_program"]["royalty_address"])
        pts: uint16 = uint16(transfer_info["transfer_program"]["royalty_percentage"])
        extra_royalty_amount = uint64(math.floor(math.floor(offered_amount / len(royalty_nft_assets)) * (pts / 10000)))
        royalty_payments.append(Payment(address, extra_royalty_amount, [address]))

    return royalty_payments


def find_full_prog_from_mod_in_serialized_program(full_program: bytes, start: int, num_curried_args: int) -> Program:
    curried_args: int = 0
    while curried_args < num_curried_args:
        start -= 5
        curried_mod = Program.from_bytes(full_program[start:])
        new_curried_args = list(curried_mod.uncurry()[1].as_iter())
        curried_args += len(new_curried_args)
    if curried_args > num_curried_args:
        raise ValueError(f"Too many curried args: {curried_mod}")
    return curried_mod


def uncurry_to_mod(program: Program, target_mod: Program) -> List[Program]:
    curried_args: List[Program] = []
    while program != target_mod:
        program, new_curried_args = program.uncurry()
        curried_args[:0] = new_curried_args.as_iter()
    return curried_args


def spend_to_offer_bytes(bundle: SpendBundle) -> bytes:
    """
    This is a function to convert an unsigned spendbundle into a legacy offer so that old clients can parse it
    correctly. It only supports exactly what was supported at the time of its creation and will raise if there is
    anything unfamiliar about the unsigned spend. If there is a raise, it means that this new client is trying to
    create a spend for an old client that the old client cannot interpret.
    """
    new_spends: List[CoinSpend] = []
    for spend in bundle.coin_spends:
        full_solution_bytes = bytes(spend.solution)

        requested_payments_announcements: List[bytes32] = []
        dl_requirements: List[Program] = []
        graftroot_solution_bytes: Optional[bytes] = None
        solution_bytes: bytes = full_solution_bytes
        while True:
            requested_payments_index: int = solution_bytes.find(bytes(ADD_WRAPPED_ANNOUNCEMENT))
            dl_inclusion_index: int = solution_bytes.find(bytes(GRAFTROOT_DL_OFFERS))
            if requested_payments_index == -1 and dl_inclusion_index == -1:
                break
            elif requested_payments_index == -1:
                index: int = dl_inclusion_index
                num_args: int = 4
            elif dl_inclusion_index == -1:
                index = requested_payments_index
                num_args = 6
            else:
                if requested_payments_index < dl_inclusion_index:
                    index = requested_payments_index
                    num_args = 6
                else:
                    index = dl_inclusion_index
                    num_args = 4

            delegated_puzzle = find_full_prog_from_mod_in_serialized_program(solution_bytes, index, num_args)
            if graftroot_solution_bytes is None:
                delegated_puzzle_bytes = bytes(delegated_puzzle)
                graftroot_solution_index = full_solution_bytes.find(delegated_puzzle_bytes) - 3
                graftroot_solution_bytes = full_solution_bytes[graftroot_solution_index:]
                graftroot_solution = Program.from_bytes(graftroot_solution_bytes)
                delegated_solution = graftroot_solution.at("rrf")
                remaining_metadatas = delegated_solution.rest()

            delegated_puzzle_mod = (
                ADD_WRAPPED_ANNOUNCEMENT if index == requested_payments_index else GRAFTROOT_DL_OFFERS
            )

            if delegated_puzzle_mod == ADD_WRAPPED_ANNOUNCEMENT:
                # FIX
                (
                    mod_hashes,
                    templates,
                    committed_values,
                    puzzle_hash,
                    announcement,
                    delegated_puzzle,
                ) = uncurry_to_mod(delegated_puzzle, delegated_puzzle_mod)

                def build_environment(template: Program, values: Program, puzzle_reveal: Program) -> Program:
                    if template.atom is None:
                        return Program.to(
                            [
                                4,
                                build_environment(values.first(), template.first()),
                                build_environment(values.rest(), template.rest()),
                            ]
                        )
                    elif template == Program.to(1):
                        return Program.to((1, values)).get_tree_hash()
                    elif template == Program.to(-1):
                        raise ValueError("Offers do not support requested payments with partial information")
                    elif template == Program.to(0):
                        return Program.to((1, puzzle_reveal))
                    elif template == Program.to("$"):
                        return Program.to(1)

                puzzle_reveal: Program = OFFER_MOD
                for template, metadata in zip(templates.as_iter(), remaining_metadatas.at("frrfr").as_iter()):
                    mod: Program = metadata.first()
                    value_preimages: Program = metadata.rest()
                    puzzle_reveal = Program.to(
                        [2, (1, mod), build_environment(template, value_preimages, puzzle_reveal)]
                    )

                dummy_solution: Program = Program.to([remaining_metadatas.at("frrff")])
                new_spends.append(
                    CoinSpend(
                        Coin(bytes32([0] * 32), puzzle_reveal.get_tree_hash(), uint64(0)), puzzle_reveal, dummy_solution
                    )
                )
                requested_payments_announcements.append(
                    Announcement(puzzle_reveal.get_tree_hash(), announcement.as_python()).name()
                )
            else:  # if delegated_puzzle_mod == GRAFTROOT_DL_OFFERS
                delegated_puzzle, singleton_structs, metatada_hashes, values_to_prove = uncurry_to_mod(
                    delegated_puzzle, delegated_puzzle_mod
                )
                if dl_requirements != []:
                    raise ValueError("Offers only support one DL requirement per coin")
                dl_requirements = [singleton_structs, metatada_hashes, values_to_prove]

                for struct in singleton_structs.as_iter():
                    puzzle_reveal = create_host_fullpuz(OFFER_MOD, bytes32([0] * 32), bytes32(struct.at("rf").as_python()))
                    dummy_solution = Program.to([(bytes32([0] * 32), [[bytes32([0] * 32), uint64(1), []]])])
                    new_spends.append(
                        CoinSpend(
                            Coin(bytes32([0] * 32), puzzle_reveal.get_tree_hash(), uint64(0)), puzzle_reveal, dummy_solution
                        )
                    )

            solution_bytes = bytes(delegated_puzzle)
            remaining_metadatas = remaining_metadatas.rest()

        if graftroot_solution_bytes is None:
            new_spends.append(spend)
        else:
            delegated_solution = Program.to(None)
            # (mod (CONDITION INNER_PUZZLE inner_solution) (c CONDITION (a INNER_PUZZLE inner_solution)))
            NEW_ANNOUNCEMENT_MOD: Program = Program.to([4, 2, [2, 5, 11]])
            for announcement in requested_payments_announcements:
                delegated_puzzle = NEW_ANNOUNCEMENT_MOD.curry(Program.to([63, announcement]), delegated_puzzle)
                delegated_solution = delegated_solution.cons(None)

            if dl_requirements != []:
                delegated_puzzle = GRAFTROOT_DL_OFFERS.curry(delegated_puzzle, *dl_requirements)
                delegated_solution = Program.to([None, None, None, None, delegated_solution])

            new_spends.append(
                CoinSpend(
                    spend.coin,
                    spend.puzzle_reveal,
                    solution_for_delegated_puzzle(delegated_puzzle, delegated_solution),
                )
            )

    return bytes(SpendBundle(new_spends, bundle.aggregated_signature))


def sort_coin_list(coins: List[Coin]) -> List[Coin]:
    # This sort should be reproducible in CLVM with `>s`
    return sorted(coins, key=Coin.name)


def select_independent_coin(coins: List[Coin]) -> Coin:
    return sort_coin_list(coins)[0]


def nonce_coin_list(coins: List[Coin]) -> bytes32:
    sorted_coin_list: List[List[Union[bytes32, uint64]]] = [coin_as_list(c) for c in coins]
    return Program.to(sorted_coin_list).get_tree_hash()


def potentially_add_nonce(action: WalletAction, nonce: bytes32) -> WalletAction:
    if action.name() == RequestPayment.name():
        if action.nonce is None:
            return dataclasses.replace(action, nonce=nonce)

    return action


async def build_spend(wallet_state_manager: Any, solver: Solver, previous_actions: List[CoinSpend]) -> List[CoinSpend]:
    outer_wallets: Dict[Coin, OuterWallet] = {}
    inner_wallets: Dict[Coin, InnerWallet] = {}
    outer_constructors: Dict[Coin, Solver] = {}
    inner_constructors: Dict[Coin, Solver] = {}

    # Keep track of all the new spends in case we want to secure them with announcements
    spend_group: List[CoinSpend] = []

    for action_spec in solver["actions"]:
        # Step 1: Determine which coins, wallets, and puzzle reveals we need to complete the action
        coin_spec: Solver = action_spec["with"]

        coin_infos: Dict[
            Coin, Tuple[OuterWallet, Solver, InnerWallet, Solver]
        ] = await wallet_state_manager.get_coin_infos_for_spec(coin_spec, previous_actions)

        for coin, info in coin_infos.items():
            outer_wallet, outer_constructor, inner_wallet, inner_constructor = info
            outer_wallets[coin] = outer_wallet
            inner_wallets[coin] = inner_wallet
            outer_constructors[coin] = outer_constructor
            inner_constructors[coin] = inner_constructor

        # Step 2: Figure out what coins are responsible for each action
        outer_actions: Dict[Coin, List[WalletAction]] = {}
        inner_actions: Dict[Coin, List[WalletAction]] = {}
        actions_left: List[Solver] = action_spec["do"]
        group_nonce: bytes32 = nonce_coin_list(coin for coin in coin_infos)
        for coin in coin_infos:
            outer_wallet = outer_wallets[coin]
            inner_wallet = inner_wallets[coin]
            # Get a list of the actions that each wallet supports
            outer_action_parsers = outer_wallet.get_outer_actions()
            inner_action_parsers = inner_wallet.get_inner_actions()

            # Apply any actions that the coin supports
            new_actions_left: List[Solver] = []
            coin_outer_actions: List[WalletAction] = []
            coin_inner_actions: List[WalletAction] = []
            for action in actions_left:
                if action["type"] in wallet_state_manager.action_aliases:
                    alias = wallet_state_manager.action_aliases[action["type"]].from_solver(action)
                    if "add_payment_nonces" not in solver or solver["add_payment_nonces"] != Program.to(None):
                        alias = potentially_add_nonce(alias, group_nonce)
                    action = alias.de_alias().to_solver()
                if action["type"] in outer_action_parsers:
                    coin_outer_actions.append(outer_action_parsers[action["type"]](action))
                elif action["type"] in inner_action_parsers:
                    coin_inner_actions.append(inner_action_parsers[action["type"]](action))
                else:
                    new_actions_left.append(action)

            # Let the outer wallet potentially modify the actions (for example, adding hints to payments)
            new_outer_actions, new_inner_actions = await outer_wallet.check_and_modify_actions(
                coin, coin_outer_actions, coin_inner_actions
            )

            # Double check that the new inner actions are still okay with the inner wallet
            for inner_action in new_inner_actions:
                if inner_action.name() not in inner_action_parsers:
                    continue

            outer_actions[coin] = new_outer_actions
            inner_actions[coin] = new_inner_actions
            actions_left = new_actions_left

        if len(actions_left) > 0:  # Not all actions were handled
            raise ValueError(f"Could not complete actions with specified coins {actions_left}")

        # Step 3: Create all of the coin spends
        new_coin_spends: List[CoinSpend] = []
        for coin in coin_infos:
            outer_wallet = outer_wallets[coin]
            inner_wallet = inner_wallets[coin]

            # Create the inner puzzle and solution first
            inner_puzzle = await inner_wallet.construct_inner_puzzle(inner_constructors[coin])
            inner_solution = await inner_wallet.construct_inner_solution(inner_actions[coin])

            # Then feed those to the outer wallet
            outer_puzzle = await outer_wallet.construct_outer_puzzle(outer_constructors[coin], inner_puzzle)
            outer_solution = await outer_wallet.construct_outer_solution(outer_actions[coin], inner_solution)

            new_coin_spends.append(CoinSpend(coin, outer_puzzle, outer_solution))

        # (Optional) Step 4: Investigate the coin spends and fill in the change data
        if "change" not in solver or solver["change"] != Program.to(None):
            input_amount: int = sum(cs.coin.amount for cs in new_coin_spends)
            output_amount: int = sum(c.amount for cs in new_coin_spends for c in cs.additions())
            fees: int = sum(cs.reserved_fee() for cs in new_coin_spends)
            if output_amount + fees < input_amount:
                change_satisfied: bool = False
                coin_spends_after_change: List[CoinSpend] = []
                for coin_spend in new_coin_spends:
                    if change_satisfied:
                        coin_spends_after_change.append(coin_spend)
                        continue

                    outer_wallet = outer_wallets[coin_spend.coin]
                    inner_wallet = inner_wallets[coin_spend.coin]
                    # Get a list of the actions that each wallet supports
                    outer_action_parsers = outer_wallet.get_outer_actions()
                    inner_action_parsers = inner_wallet.get_inner_actions()

                    change_action = DirectPayment(
                        Payment(await inner_wallet.get_new_puzzlehash(), input_amount - (output_amount + fees), []), []
                    ).de_alias()

                    if change_action.name() in outer_action_parsers:
                        new_outer_actions = [*outer_actions[coin_spend.coin], change_action]
                        new_inner_actions = inner_actions[coin_spend.coin]
                    elif change_action.name() in inner_action_parsers:
                        new_outer_actions = outer_actions[coin_spend.coin]
                        new_inner_actions = [*inner_actions[coin_spend.coin], change_action]

                    # Let the outer wallet potentially modify the actions (for example, adding hints to payments)
                    new_outer_actions, new_inner_actions = await outer_wallet.check_and_modify_actions(
                        coin_spend.coin, new_outer_actions, new_inner_actions
                    )
                    # Double check that the new inner actions are still okay with the inner wallet
                    for inner_action in new_inner_actions:
                        if inner_action.name() not in inner_action_parsers:
                            coin_spends_after_change.append(coin_spend)
                            continue

                    outer_actions[coin_spend.coin] = new_outer_actions
                    inner_actions[coin_spend.coin] = new_inner_actions

                    inner_solution = await inner_wallet.construct_inner_solution(new_inner_actions)
                    outer_solution = await outer_wallet.construct_outer_solution(new_outer_actions, inner_solution)

                    coin_spends_after_change.append(dataclasses.replace(coin_spend, solution=outer_solution))

                    change_satisfied = True

                if not change_satisfied:
                    raise ValueError("Could not create change for the specified spend")

                new_coin_spends = coin_spends_after_change

        previous_actions.extend(new_coin_spends)
        spend_group.extend(new_coin_spends)

    # Step 5: Secure the coin spends with an announcement ring
    coin_spends_after_announcements: List[CoinSpend] = []
    nonce: bytes32 = nonce_coin_list([cs.coin for cs in spend_group])
    for i, coin_spend in enumerate(spend_group):
        outer_wallet = outer_wallets[coin_spend.coin]
        inner_wallet = inner_wallets[coin_spend.coin]
        # Get a list of the actions that each wallet supports
        outer_action_parsers = outer_wallet.get_outer_actions()
        inner_action_parsers = inner_wallet.get_inner_actions()

        next_coin: Coin = spend_group[0 if i == len(spend_group) - 1 else i + 1].coin

        # Make an announcement for the previous coin and assert the next coin's announcement
        make_announcement = MakeAnnouncement("coin", Program.to(nonce)).de_alias()
        assert_announcement = AssertAnnouncement("coin", next_coin.name(), Program.to(nonce)).de_alias()

        if make_announcement.name() in outer_action_parsers:
            new_outer_actions = [*outer_actions[coin_spend.coin], make_announcement]
            new_inner_actions = inner_actions[coin_spend.coin]
        elif make_announcement.name() in inner_action_parsers:
            new_outer_actions = outer_actions[coin_spend.coin]
            new_inner_actions = [*inner_actions[coin_spend.coin], make_announcement]
        else:
            raise ValueError(f"Bundle cannot be secured because coin: {coin_spend.coin} can't make announcements")

        if assert_announcement.name() in outer_action_parsers:
            new_outer_actions = [*new_outer_actions, assert_announcement]
            new_inner_actions = new_inner_actions
        elif assert_announcement.name() in inner_action_parsers:
            new_outer_actions = new_outer_actions
            new_inner_actions = [*new_inner_actions, assert_announcement]
        else:
            raise ValueError(f"Bundle cannot be secured because coin: {coin_spend.coin} can't assert announcements")

        # Let the outer wallet potentially modify the actions (for example, adding hints to payments)
        new_outer_actions, new_inner_actions = await outer_wallet.check_and_modify_actions(
            coin_spend.coin, new_outer_actions, new_inner_actions
        )
        # Double check that the new inner actions are still okay with the inner wallet
        for inner_action in new_inner_actions:
            if inner_action.name() not in inner_action_parsers:
                coin_spends_after_announcements.append(coin_spend)
                continue

        outer_actions[coin_spend.coin] = new_outer_actions
        inner_actions[coin_spend.coin] = new_inner_actions

        inner_solution = await inner_wallet.construct_inner_solution(new_inner_actions)
        outer_solution = await outer_wallet.construct_outer_solution(new_outer_actions, inner_solution)

        coin_spends_after_announcements.append(dataclasses.replace(coin_spend, solution=outer_solution))

    previous_actions = coin_spends_after_announcements

    # Step 6: Add any bundle actions
    coin_spends_after_bundle_actions: List[CoinSpend] = []
    bundle_actions_left: List[Solver] = solver["bundle_actions"]
    for coin_spend in previous_actions:
        if len(bundle_actions_left) == 0:
            coin_spends_after_bundle_actions.append(coin_spend)
            continue

        outer_wallet = outer_wallets[coin_spend.coin]
        inner_wallet = inner_wallets[coin_spend.coin]
        # Get a list of the actions that each wallet supports
        outer_action_parsers = outer_wallet.get_outer_actions()
        inner_action_parsers = inner_wallet.get_inner_actions()

        # Apply any actions that the coin supports
        new_actions_left: List[Solver] = []
        coin_outer_actions: List[WalletAction] = outer_actions[coin_spend.coin]
        coin_inner_actions: List[WalletAction] = inner_actions[coin_spend.coin]
        for action in bundle_actions_left:
            if action["type"] in wallet_state_manager.action_aliases:
                alias = wallet_state_manager.action_aliases[action["type"]].from_solver(action)
                if "add_payment_nonces" not in solver or solver["add_payment_nonces"] != Program.to(None):
                    alias = potentially_add_nonce(alias, nonce)
                action = alias.de_alias().to_solver()
            if action["type"] in outer_action_parsers:
                coin_outer_actions.append(outer_action_parsers[action["type"]](action))
            elif action["type"] in inner_action_parsers:
                coin_inner_actions.append(inner_action_parsers[action["type"]](action))
            else:
                new_actions_left.append(action)

        # Let the outer wallet potentially modify the actions (for example, adding hints to payments)
        new_outer_actions, new_inner_actions = await outer_wallet.check_and_modify_actions(
            coin, coin_outer_actions, coin_inner_actions
        )

        # Double check that the new inner actions are still okay with the inner wallet
        for inner_action in new_inner_actions:
            if inner_action.name() not in inner_action_parsers:
                continue

        outer_actions[coin_spend.coin] = new_outer_actions
        inner_actions[coin_spend.coin] = new_inner_actions

        inner_solution = await inner_wallet.construct_inner_solution(new_inner_actions)
        outer_solution = await outer_wallet.construct_outer_solution(new_outer_actions, inner_solution)

        coin_spends_after_bundle_actions.append(dataclasses.replace(coin_spend, solution=outer_solution))
        bundle_actions_left = new_actions_left

    if len(bundle_actions_left) > 0:
        raise ValueError(f"Could not handle all bundle actions: {bundle_actions_left}")

    previous_actions = coin_spends_after_bundle_actions

    return previous_actions


@dataclass(frozen=True)
class WalletActions:
    request: Solver
    bundle: SpendBundle
