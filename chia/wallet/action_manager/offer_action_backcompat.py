from __future__ import annotations

import ast
import dataclasses
import math
from typing import Any, Dict, List, Optional, Tuple, Union

from clvm_tools.binutils import disassemble

from chia.data_layer.data_layer_wallet import OuterDriver as DLOuterDriver
from chia.data_layer.data_layer_wallet import UpdateMetadataDL
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint16, uint64
from chia.wallet.action_manager.action_aliases import Fee, MakeAnnouncement, OfferedAmount, RequestPayment
from chia.wallet.action_manager.protocols import SolutionDescription, SpendDescription
from chia.wallet.cat_wallet.cat_wallet import OuterDriver as CATOuterDriver
from chia.wallet.db_wallet.db_wallet_puzzles import (
    ACS_MU_PH,
    GRAFTROOT_DL_OFFERS,
    SINGLETON_TOP_LAYER_MOD,
    RequireDLInclusion,
    create_host_fullpuz,
)
from chia.wallet.nft_wallet.nft_wallet import NFTWallet
from chia.wallet.outer_puzzles import AssetType
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver, cast_to_int
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import solution_for_delegated_puzzle
from chia.wallet.trading.offer import OFFER_MOD, Offer
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet_protocol import WalletProtocol


async def old_request_to_new(
    wallet_state_manager: Any,
    offer_dict: Dict[Optional[bytes32], int],
    driver_dict: Dict[bytes32, PuzzleInfo],
    solver: Solver,
    fee: uint64,
) -> Solver:
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
        if asset_id is not None and callable(getattr(wallet, "get_puzzle_info", None)):
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
                    puzzle_info = PuzzleInfo(type_description["also"])
                    del type_description["also"]
                    asset_types.append(type_description)
                else:
                    asset_types.append(type_description)
                    break

        # We're passing everything in as a dictionary now instead of a single asset_id/amount pair
        offered_asset: Dict[str, Any] = {
            "with": {
                **({} if asset_id is None else {"asset_id": "0x" + asset_id.hex()}),
                "asset_description": asset_types,
            },
            "do": [],
        }

        # Get the specified solver for this asset id
        try:
            if asset_id is not None:
                try:
                    this_solver: Optional[Solver] = solver[asset_id.hex()]
                except KeyError:
                    this_solver = solver["0x" + asset_id.hex()]
            else:
                this_solver = solver[""]
        except KeyError:
            this_solver = None

        # Take note of of the dl dependencies if there are any
        if this_solver is not None and "dependencies" in this_solver:
            dl_dependencies.append(
                Solver(
                    {
                        "type": "require_dl_inclusion",
                        "launcher_ids": ["0x" + dep["launcher_id"].hex() for dep in this_solver["dependencies"]],
                        "values_to_prove": [
                            ["0x" + v.hex() for v in dep["values_to_prove"]] for dep in this_solver["dependencies"]
                        ],
                    }
                )
            )

        if wallet.type() == WalletType.DATA_LAYER:
            # Data Layer offers initially were metadata updates, so we shouldn't allow any kind of sending
            assert this_solver is not None
            offered_asset["do"] = [
                {
                    "type": "update_metadata",
                    # The request used to require "new_root" be in solver so the potential KeyError is good
                    "new_metadata": "(0x" + this_solver["new_root"].hex() + ")",
                }
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
            offered_asset["with"]["amount"] = str(abs(amount))
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
            # Provenant NFTs by default clear their ownership on transfer
            elif driver_dict[asset_id].check_type(
                [
                    AssetType.SINGLETON.value,
                    AssetType.METADATA.value,
                    AssetType.OWNERSHIP.value,
                ]
            ):
                action_batch.append(
                    Solver(
                        {
                            "type": "update_state",
                            "update": {
                                "new_owner": "()",
                            },
                        }
                    )
                )
            # The standard XCH should pay the fee
            if asset_id is None and fee > 0:
                action_batch.append(Fee(fee).to_solver())
                offered_asset["with"]["amount"] = str(cast_to_int(Solver(offered_asset["with"])["amount"]) + fee)
            offered_asset["do"] = action_batch

        final_solver["actions"].append(offered_asset)

    final_solver["actions"].extend(additional_actions)

    # Make sure the fee gets into the solver
    if None not in offer_dict and fee > 0:
        final_solver["actions"].append(
            {
                "with": {"amount": str(fee)},
                "do": [
                    Fee(fee).to_solver(),
                ],
            }
        )

    # Now lets use the requested items to fill in the bundle dependencies
    final_solver.setdefault("bundle_actions", [])
    final_solver["bundle_actions"].extend(dl_dependencies)
    for asset_id, amount in requested_assets.items():
        asset_types = []
        # It wouldn't break backwards compatibility if we added the option to specify this
        p2_ph = await wallet_state_manager.main_wallet.get_new_puzzlehash()

        # DL singletons are not sent as part of offers by default
        if asset_id is not None and not (
            driver_dict[asset_id].check_type(
                [
                    AssetType.SINGLETON.value,
                    AssetType.METADATA.value,
                ]
            )
            and driver_dict[asset_id].also()["updater_hash"] == ACS_MU_PH  # type: ignore
        ):
            asset_driver = driver_dict[asset_id]

            # Fill in asset types for the requested asset
            if asset_driver.type() == AssetType.CAT.value:
                asset_types = [
                    solver.info for solver in CATOuterDriver.get_asset_types(Solver({"tail": "0x" + asset_id.hex()}))
                ]
            elif asset_driver.check_type(
                [
                    AssetType.SINGLETON.value,
                    AssetType.METADATA.value,
                ]
            ):
                nft_dict: Dict[str, Any] = {
                    "launcher_id": asset_driver.info["launcher_id"],
                    "metadata": asset_driver.info["metadata"],
                    "metadata_updater_hash": asset_driver.info["updater_hash"],
                }
                # Royalty enabled NFTs have some more info to fill in
                if asset_driver.check_type(
                    [
                        AssetType.SINGLETON.value,
                        AssetType.METADATA.value,
                        AssetType.OWNERSHIP.value,
                    ]
                ):
                    nft_dict["owner"] = asset_driver.info["owner"]
                    nft_dict["transfer_program"] = asset_driver.info["transfer_program"]

                asset_types = [solver.info for solver in NFTWallet.get_asset_types(Solver(nft_dict))]

            final_solver["bundle_actions"].append(
                {
                    "type": "request_payment",
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
    """
    This takes a serialized program. Starting from a specified point where an uncurried program should be, it jumps
    backwards in the serialization to (a mod ...) and takes note of how many curried arguments are in ...

    If the number of curried arguments is less than the target amount, it will repeat the above process.

    The goal is that even if a mod is curried multiple times, it will keep expanding until it captures the full program
    with all of them.
    """
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
    """
    This is the inverse operation from above. A program is uncurried until it is a target base mod.
    """
    curried_args: List[Program] = []
    while program != target_mod:
        program, new_curried_args = program.uncurry()
        curried_args[:0] = new_curried_args.as_iter()
    return curried_args


def request_payment_to_legacy_encoding(action: RequestPayment, add_nonce: Optional[bytes32] = None) -> CoinSpend:
    """
    This method takes a RequestPayment WalletAction and converts it to the CoinSpend encoding that is in use in offers
    """
    puzzle_reveal: Program = OFFER_MOD
    for typ in action.asset_types:
        puzzle_reveal = Program.to(
            [
                2,
                (1, typ["mod"]),
                RequestPayment.build_environment(
                    typ["solution_template"],
                    typ["committed_args"],
                    typ["committed_args"],
                    puzzle_reveal,
                ),
            ]
        )

    dummy_solution: Program = Program.to(
        [
            (
                action.nonce if add_nonce is None or action.nonce is not None else add_nonce,
                [p.as_condition_args() for p in action.payments],
            )
        ]
    )
    return CoinSpend(
        Coin(bytes32([0] * 32), puzzle_reveal.get_tree_hash(), uint64(0)),
        puzzle_reveal,
        dummy_solution,
    )


async def spend_to_offer(wallet_state_manager: Any, bundle: SpendBundle) -> Offer:
    """
    This converts from new action-style spend bundle -> Offer class
    """
    new_spends: List[CoinSpend] = []
    environment: Solver = Solver({})
    for spend in bundle.coin_spends:
        # Step 1: Get any wallets that claim to identify the puzzle
        matches: List[SpendDescription] = await SpendDescription.match(spend, wallet_state_manager)

        if matches == []:
            continue  # We skip spends we can't identify, if they're important, the spend will fail on chain
        elif len(matches) > 1:
            # QUESTION: Should we support this? Giving multiple interpretations?
            raise ValueError(f"There are multiple ways to describe spend with coin: {spend.coin}")

        actions = matches[0].get_all_actions(wallet_state_manager.action_aliases)
        # Step 2: Re-order the actions so that DL graftroots are the last applied
        # DL Inclusion graftroots are expected by old clients to be the outermost graftroot puzzle
        dl_graftroot_actions: List[Solver] = []
        all_other_actions: List[Solver] = []
        for action in actions:
            if isinstance(action, RequireDLInclusion):
                dl_graftroot_actions.append(action.to_solver())
                # Add the dummy spend that used to encode the requested payment
                for launcher_id in action.launcher_ids:
                    puzzle_reveal = create_host_fullpuz(OFFER_MOD, bytes32([0] * 32), launcher_id)
                    dummy_solution = Program.to([(bytes32([0] * 32), [[bytes32([0] * 32), uint64(1), []]])])
                    new_spends.append(
                        CoinSpend(
                            Coin(bytes32([0] * 32), puzzle_reveal.get_tree_hash(), uint64(0)),
                            puzzle_reveal,
                            dummy_solution,
                        )
                    )
            else:
                if isinstance(action, RequestPayment):
                    # Add the dummy spend that used to encode the requested payment
                    new_spends.append(request_payment_to_legacy_encoding(action))
                all_other_actions.append(action.to_solver())

        if len(dl_graftroot_actions) > 1:
            raise ValueError("Legacy offers only support one graftroot for dl inclusions")

        sorted_actions: List[Solver] = [*all_other_actions, *dl_graftroot_actions]

        remaining_actions, new_description = await matches[0].apply_actions(
            sorted_actions, default_aliases=wallet_state_manager.action_aliases, environment=environment
        )
        new_spend: CoinSpend = await new_description.spend(environment=environment)

        # Step 3: Erase the graftroot metadata from the delegated solution, the old client won't know to dump it
        re_matched_spend: Optional[
            Tuple[SolutionDescription, Program]
        ] = await new_description.outer_puzzle_description.driver.match_solution(new_spend.solution.to_program())
        if re_matched_spend is None:
            raise RuntimeError("Internal logic error, spend could not be rematched")
        inner_most_solution: Program = re_matched_spend[1]
        delegated_solution: Program = inner_most_solution.at("rrf")
        if delegated_solution.atom is None and delegated_solution.first() == Program.to("graftroot"):
            if dl_graftroot_actions == []:
                new_delegated_solution = Program.to(None)
            else:
                new_delegated_solution = Program.to([None, None, None, None, None])
            inner_most_solution = Program.to(
                [inner_most_solution.first(), inner_most_solution.at("rf"), new_delegated_solution]
            )

        new_full_solution: Program = (
            # In python 3.8+ we can use `@runtime_checkable` on the driver protocols
            await new_description.outer_puzzle_description.driver.construct_outer_solution(  # type: ignore
                new_description.outer_solution_description.actions,
                inner_most_solution,
                global_environment=environment,
                local_environment=new_description.outer_solution_description.environment,
                optimize=False,
            )
        )

        # Step 4: Fill in the ring info for CATs in a way so as not to make the CAT spend raise
        if isinstance(new_description.outer_puzzle_description.driver, CATOuterDriver):
            cat_args = list(new_full_solution.as_iter())
            if Program.to(None) in cat_args[2:5]:
                new_full_solution = Program.to(
                    [
                        cat_args[0],
                        cat_args[1],
                        new_spend.coin.name(),
                        [new_spend.coin.parent_coin_info, new_spend.coin.puzzle_hash, new_spend.coin.amount],
                        [
                            new_spend.coin.parent_coin_info,
                            (
                                # In python 3.8+ we can use `@runtime_checkable` on the driver protocols
                                await new_description.inner_puzzle_description.driver.construct_inner_puzzle()  # type: ignore  # noqa
                            ).get_tree_hash(),
                            new_spend.coin.amount,
                        ],
                        cat_args[5],
                        cat_args[6],
                    ]
                )

        new_spend = dataclasses.replace(
            new_spend,
            solution=new_full_solution,
        )

        if len(remaining_actions) > 0:
            raise ValueError("Attempting to convert the spends to an offer resulted in being unable to spend a coin")
        new_spends.append(new_spend)

    return Offer.from_spend_bundle(SpendBundle(new_spends, bundle.aggregated_signature))


def legacy_rp_puzzle_to_asset_types(rp_puzzle: Program) -> List[Solver]:
    """
    Give the old style of encoding requested payments, we know what the inner puzzle is and that all args are committed
    so we can actually generally get the asset types that are encoded in the offer.
    """
    if rp_puzzle == OFFER_MOD:
        return []

    mod, curried_args = rp_puzzle.uncurry()
    args_list = list(curried_args.as_iter())

    # Recursive loop where we uncurry, check each arg for the OFFER_MOD, if we haven't found it recurse on each arg
    for curried_arg in args_list:
        if curried_arg == OFFER_MOD:
            deeper_asset_types: List[Solver] = []
            break
        inner_mod, _ = curried_arg.uncurry()
        if inner_mod != curried_arg:
            try:
                deeper_asset_types = legacy_rp_puzzle_to_asset_types(curried_arg)
                break
            except ValueError:
                continue
    else:
        raise ValueError("Could not find the offer mod in the requested payments puzzle")

    # We know the solution template is always (1 1 1 ... . $)
    solution_template: List[str] = ["1" if i != args_list.index(curried_arg) else "0" for i in range(0, len(args_list))]
    solution_template.extend([".", "$"])
    # "curried_arg" at this point will be the INNER_PUZZLE so we don't want to include that in committed args
    committed_args: List[str] = [disassemble(arg) if arg != curried_arg else "()" for arg in args_list]
    committed_args.extend([".", "()"])
    this_asset_type = Solver(
        {
            "mod": disassemble(mod),
            "solution_template": "(" + " ".join(solution_template) + ")",
            "committed_args": "(" + " ".join(committed_args) + ")",
        }
    )
    return [this_asset_type, *deeper_asset_types]


def offer_to_spend(offer: Offer) -> SpendBundle:
    """
    The inverse of spend_to_offer: convert an old Offer class into a new action-style spendbundle
    """
    new_spends: List[CoinSpend] = []
    requested_spends: List[CoinSpend] = [
        cs for cs in offer.to_spend_bundle().coin_spends if cs.coin.parent_coin_info == bytes32([0] * 32)
    ]
    for spend in offer.bundle.coin_spends:
        # Operating directly on the serialization, we're going to jump to either the first instance of
        # the DL graftroot mod, or the announcements we expect from the requested payments
        solution_bytes: bytes = bytes(spend.solution)
        dl_inclusion_index: int = solution_bytes.find(bytes(GRAFTROOT_DL_OFFERS))
        announcement_hash_index: int = -1
        dl_inclusions: List[RequireDLInclusion] = []
        requested_payments: List[RequestPayment] = []
        for requested_spend in requested_spends:
            for announcement in requested_spend.solution.to_program().as_iter():
                announcement_hash: bytes32 = Announcement(
                    requested_spend.puzzle_reveal.get_tree_hash(), announcement.get_tree_hash()
                ).name()
                new_index = solution_bytes.find(announcement_hash)
                if new_index != -1:
                    # We want the earliest possible index
                    announcement_hash_index = (
                        new_index if announcement_hash_index == -1 else min(announcement_hash_index, new_index)
                    )
                    # Construct the WalletActions as we're looping through
                    asset_types: List[Solver] = legacy_rp_puzzle_to_asset_types(
                        requested_spend.puzzle_reveal.to_program()
                    )
                    nonce: bytes32 = bytes32(announcement.first().as_python())
                    payments: List[Payment] = [
                        Payment.from_condition(Program.to((51, condition)))
                        for condition in announcement.rest().as_iter()
                    ]
                    requested_payments.append(RequestPayment(asset_types, nonce, payments))

        # Take note of the DL graftroot (old offers never supported more than 1)
        if dl_inclusion_index != -1:
            delegated_puzzle = find_full_prog_from_mod_in_serialized_program(solution_bytes, dl_inclusion_index, 4)
            inner_puzzle, singleton_structs, _, values_to_prove = uncurry_to_mod(delegated_puzzle, GRAFTROOT_DL_OFFERS)
            dl_inclusions.append(
                RequireDLInclusion(
                    [bytes32(struct.at("rf").as_python()) for struct in singleton_structs.as_iter()],
                    [
                        [bytes32(value.as_python()) for value in values.as_iter()]
                        for values in values_to_prove.as_iter()
                    ],
                )
            )
        elif announcement_hash_index != -1:
            delegated_puzzle = Program.from_bytes(solution_bytes[announcement_hash_index - 9 :])
        else:
            # No DL or RP graftroots means we can skip this spend, it's fine as it is
            new_spends.append(spend)
            continue

        # Now we need to re-add the metadata that was deleted when we serialized down to an Offer
        innermost_solution: Program = Program.from_bytes(
            solution_bytes[solution_bytes.find(bytes(delegated_puzzle)) - 3 :]
        )

        metadata: Program = Program.to(None)
        ordered_aliases: List[Union[RequestPayment, RequireDLInclusion]] = [*requested_payments, *dl_inclusions]
        for alias in ordered_aliases:
            graftroot = alias.de_alias()
            metadata = Program.to([graftroot.puzzle_wrapper, graftroot.solution_wrapper, graftroot.metadata]).cons(
                metadata
            )

        inner_delegated_puzzle: Program = delegated_puzzle
        if dl_inclusion_index != -1:
            inner_delegated_puzzle = inner_puzzle
        if announcement_hash_index != -1:
            for _ in requested_payments:
                inner_delegated_puzzle = inner_delegated_puzzle.at("rrfrfr")

        metadata = Program.to("graftroot").cons(Program.to(inner_delegated_puzzle).cons(metadata))

        new_solution: SerializedProgram = SerializedProgram.from_bytes(
            solution_bytes.replace(
                bytes(innermost_solution), bytes(solution_for_delegated_puzzle(delegated_puzzle, metadata))
            )
        )

        new_spends.append(CoinSpend(spend.coin, spend.puzzle_reveal, new_solution))

    return SpendBundle(
        new_spends,
        offer.bundle.aggregated_signature,
    )


async def generate_summary_complement(
    wallet_state_manager: Any, summary: Solver, additional_summary: Solver, fee: uint64 = uint64(0)
) -> Solver:
    """
    Given a new action-style summary, generate the complement that would have been generated by the trade manager
    """
    comp_actions: List[Solver] = []
    comp_bundle_actions: List[Solver] = []
    bundle_actions = summary["bundle_actions"] if "bundle_actions" in summary else []
    paid_fee: bool = fee == 0
    # Loop through all actions, bundle or not
    for total_action in [*summary["actions"], *bundle_actions]:
        actions_to_loop = [total_action] if total_action in bundle_actions else total_action["do"]
        for action in actions_to_loop:
            # OfferedAmount generates a corresponding RequestPayment
            if action["type"] == OfferedAmount.name():
                new_p2_puzhash: bytes32 = await wallet_state_manager.main_wallet.get_new_puzzlehash()
                self_payment: Payment = Payment(new_p2_puzhash, uint64(cast_to_int(action["amount"])), [new_p2_puzhash])
                asset_types: List[Solver] = (
                    total_action["with"]["asset_types"] if "asset_types" in total_action["with"] else []
                )
                comp_bundle_actions.append(RequestPayment(asset_types, None, [self_payment]).to_solver())
            # RequestPayment generates a corresponding OfferedAmount
            elif action["type"] == RequestPayment.name():
                requested_payment = RequestPayment.from_solver(action)
                offered_amount: int = sum(p.amount for p in requested_payment.payments)
                total_amount: int = offered_amount
                pay_fee_now: bool = not paid_fee and requested_payment.asset_types == []
                if pay_fee_now:
                    total_amount += fee
                comp_actions.append(
                    Solver(
                        {
                            "with": {"asset_types": requested_payment.asset_types, "amount": str(total_amount)},
                            "do": [
                                OfferedAmount(offered_amount).to_solver(),
                                *([Fee(fee).to_solver()] if pay_fee_now else []),
                            ],
                        }
                    )
                )
                if pay_fee_now:
                    paid_fee = True
    return Solver(
        {
            "actions": [
                *comp_actions,
                *([{"with": {"amount": str(fee)}, "do": [Fee(fee).to_solver()]}] if not paid_fee else []),
                *(additional_summary["actions"] if "actions" in additional_summary else []),
            ],
            "bundle_actions": [
                *comp_bundle_actions,
                *(additional_summary["bundle_actions"] if "bundle_actions" in additional_summary else []),
            ],
        }
    )


async def old_solver_to_new(wallet_state_manager: Any, old_solver: Solver) -> Solver:
    """
    Given a solver that would be used for an offer, convert it into a new action-style summary and environment
    """
    actions: List[Solver] = []
    bundle_actions: List[Solver] = []
    for key, solver in old_solver.info.items():
        # "dependencies" was the old way of specifying DL inclusion requirements
        if "dependencies" in old_solver[key]:
            bundle_actions.append(
                Solver(
                    {
                        "type": "require_dl_inclusion",
                        "launcher_ids": ["0x" + dep["launcher_id"].hex() for dep in old_solver[key]["dependencies"]],
                        "values_to_prove": [
                            ["0x" + v.hex() for v in dep["values_to_prove"]] for dep in old_solver[key]["dependencies"]
                        ],
                    }
                )
            )

        # Make sure the asset id is bytes32 before going into the next DL specific part
        try:
            bytes32.from_hexstr(key)
        except ValueError:
            continue

        # The solver used to specify what update to make to your DLs in exchange for others'
        wallet: WalletProtocol = await wallet_state_manager.get_wallet_for_asset_id(key)
        if WalletType(wallet.type()) == WalletType.DATA_LAYER:
            asset_types = DLOuterDriver.get_asset_types(
                Solver({"launcher_id": "0x" + key if key[0:2] != "0x" else key})
            )
            actions.append(
                Solver(
                    {
                        "with": {
                            "asset_types": asset_types,
                        },
                        "do": [
                            {
                                "type": "update_metadata",
                                "new_metadata": "(0x" + Solver(solver)["new_root"].hex() + ")",
                            }
                        ],
                    }
                )
            )
            actions.append(
                Solver(
                    {
                        "with": {
                            "asset_types": asset_types,
                        },
                        "do": [MakeAnnouncement("puzzle", Program.to(b"$")).to_solver()],
                    }
                )
            )

    # Proofs of inclusion is now a feature of the environment, used to solve the graftroot before it hits the chain
    dl_inclusion_proofs: Optional[List[Program]] = None
    if "proofs_of_inclusion" in old_solver:
        dl_inclusion_proofs = []
        for proof in old_solver["proofs_of_inclusion"]:
            dl_inclusion_proofs.append(Program.to((proof[1], proof[2])))

    return Solver(
        {
            "actions": actions,
            "bundle_actions": bundle_actions,
            **(
                {}
                if dl_inclusion_proofs is None
                else {"dl_inclusion_proofs": [disassemble(proof) for proof in dl_inclusion_proofs]}
            ),
            **old_solver.info,
        }
    )


def new_summary_to_old(new_summary: Solver) -> Dict[str, Any]:
    """
    Convert a new action-style summary into a summary that old clients will have no problem interpreting
    """
    old_summary: Dict[str, Any] = {"offered": [], "requested": []}  # old format
    for total_action in new_summary["actions"]:
        # Assets in the old summary are expecting fungible total amounts, not amount per spend
        asset_description: Dict[str, Any] = total_action["with"].info
        if "amount" in asset_description:
            del asset_description["amount"]
        offered_descriptions: List[Dict[str, Any]] = []
        requested_descriptions: List[Dict[str, Any]] = []
        for action in total_action["do"]:
            if action["type"] == OfferedAmount.name():
                # Recreate offered_descriptions, but add the amount into the existing amount if it exists
                new_offered_descriptions: List[Dict[str, Any]] = []
                added_amount: bool = False
                for description in offered_descriptions:
                    if "amount" in description:
                        new_offered_descriptions.append(
                            {"amount": str(int(description["amount"]) + int(action.info["amount"]))}
                        )
                        added_amount = True
                    else:
                        new_offered_descriptions.append(description)
                offered_descriptions = new_offered_descriptions
                if not added_amount:
                    offered_descriptions.append({"amount": action.info["amount"]})
            elif action["type"] == RequestPayment.name():
                payment_request: RequestPayment = RequestPayment.from_solver(action)
                # Old style summaries have an asset id in them
                if len(payment_request.asset_types) > 0:
                    outer_mod: Program = payment_request.asset_types[0]["mod"]
                    if outer_mod == CAT_MOD:
                        asset_id: str = payment_request.asset_types[0]["committed_args"].at("rf").as_python().hex()
                    elif outer_mod == SINGLETON_TOP_LAYER_MOD:
                        asset_id = payment_request.asset_types[0]["committed_args"].at("frf").as_python().hex()

                # similar to offered_descriptions above, recreate them all, adding the amount in if it already exists
                new_requested_descriptions: List[Dict[str, Any]] = []
                added_amount = False
                for description in requested_descriptions:
                    if "amount" in description:
                        new_requested_descriptions.append(
                            {
                                **({"asset_id": asset_id} if len(payment_request.asset_types) > 0 else {}),
                                "asset_types": payment_request.asset_types,
                                "amount": str(
                                    int(description["amount"]) + sum(p.amount for p in payment_request.payments)
                                ),
                            }
                        )
                        added_amount = True
                    else:
                        new_requested_descriptions.append(description)
                requested_descriptions = new_requested_descriptions
                if not added_amount:
                    requested_descriptions.append(
                        {
                            **({"asset_id": asset_id} if len(payment_request.asset_types) > 0 else {}),
                            "asset_types": payment_request.asset_types,
                            "amount": str(sum(p.amount for p in payment_request.payments)),
                        }
                    )
            elif action["type"] == UpdateMetadataDL.name():
                offered_descriptions.append({"new_root": action.info["new_metadata"][1:-1]})
            elif action["type"] == RequireDLInclusion.name():
                dl_requirement: RequireDLInclusion = RequireDLInclusion.from_solver(action)
                offered_descriptions.append(
                    {
                        "dependencies": [
                            {"launcher_id": launcher_id.hex(), "values_to_prove": [v.hex() for v in values]}
                            for launcher_id, values in zip(dl_requirement.launcher_ids, dl_requirement.values_to_prove)
                        ]
                    }
                )

        offered: Dict[str, Any] = asset_description.copy()
        requested: Dict[str, Any] = {}
        for description in offered_descriptions:
            offered.update(description)
        for description in requested_descriptions:
            requested.update(description)

        if offered_descriptions != []:
            old_summary["offered"].append(offered)
        if requested_descriptions != []:
            old_summary["requested"].append(requested)

    # This is a bit hacky but it works for right now
    old_summary_dict: Dict[str, Any] = ast.literal_eval(repr(old_summary))
    return old_summary_dict
