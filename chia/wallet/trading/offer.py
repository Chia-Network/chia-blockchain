from __future__ import annotations

from dataclasses import dataclass
from typing import Any, BinaryIO, Dict, List, Optional, Set, Tuple, Union

from blspy import G2Element
from clvm_tools.binutils import disassemble

from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import bech32_decode, bech32_encode, convertbits
from chia.util.ints import uint64
from chia.wallet.outer_puzzles import (
    construct_puzzle,
    create_asset_id,
    get_inner_puzzle,
    get_inner_solution,
    match_puzzle,
    solve_puzzle,
)
from chia.wallet.payment import Payment
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle
from chia.wallet.util.puzzle_compression import (
    compress_object_with_puzzles,
    decompress_object_with_puzzles,
    lowest_best_version,
)

OFFER_MOD_OLD = load_clvm_maybe_recompile("settlement_payments_old.clvm")
OFFER_MOD = load_clvm_maybe_recompile("settlement_payments.clvm")
OFFER_MOD_OLD_HASH = OFFER_MOD_OLD.get_tree_hash()
OFFER_MOD_HASH = OFFER_MOD.get_tree_hash()
ZERO_32 = bytes32([0] * 32)


def detect_dependent_coin(
    names: List[bytes32], deps: Dict[bytes32, List[bytes32]], announcement_dict: Dict[bytes32, List[bytes32]]
) -> Optional[Tuple[bytes32, bytes32]]:
    # First, we check for any dependencies on coins in the same bundle
    for name in names:
        for dependency in deps[name]:
            for coin, announces in announcement_dict.items():
                if dependency in announces and coin != name:
                    # We found one, now remove it and anything that depends on it (except the "provider")
                    return name, coin
    return None


@dataclass(frozen=True)
class NotarizedPayment(Payment):
    nonce: bytes32 = ZERO_32

    @classmethod
    def from_condition_and_nonce(cls, condition: Program, nonce: bytes32) -> "NotarizedPayment":
        with_opcode: Program = Program.to((51, condition))  # Gotta do this because the super class is expecting it
        p = Payment.from_condition(with_opcode)
        puzzle_hash, amount, memos = tuple(p.as_condition_args())
        return cls(puzzle_hash, amount, memos, nonce)


@dataclass(frozen=True)
class Offer:
    requested_payments: Dict[
        Optional[bytes32], List[NotarizedPayment]
    ]  # The key is the asset id of the asset being requested
    bundle: SpendBundle
    driver_dict: Dict[bytes32, PuzzleInfo]  # asset_id -> asset driver
    old: bool = False

    @staticmethod
    def ph() -> bytes32:
        return OFFER_MOD_HASH

    @staticmethod
    def notarize_payments(
        requested_payments: Dict[Optional[bytes32], List[Payment]],  # `None` means you are requesting XCH
        coins: List[Coin],
    ) -> Dict[Optional[bytes32], List[NotarizedPayment]]:
        # This sort should be reproducible in CLVM with `>s`
        sorted_coins: List[Coin] = sorted(coins, key=Coin.name)
        sorted_coin_list: List[List[Union[bytes32, uint64]]] = [coin_as_list(c) for c in sorted_coins]
        nonce: bytes32 = Program.to(sorted_coin_list).get_tree_hash()

        notarized_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = {}
        for asset_id, payments in requested_payments.items():
            notarized_payments[asset_id] = []
            for p in payments:
                puzzle_hash, amount, memos = tuple(p.as_condition_args())
                notarized_payments[asset_id].append(NotarizedPayment(puzzle_hash, amount, memos, nonce))

        return notarized_payments

    # The announcements returned from this function must be asserted in whatever spend bundle is created by the wallet
    @staticmethod
    def calculate_announcements(
        notarized_payments: Dict[Optional[bytes32], List[NotarizedPayment]],
        driver_dict: Dict[bytes32, PuzzleInfo],
        old: bool = False,
    ) -> List[Announcement]:
        announcements: List[Announcement] = []
        for asset_id, payments in notarized_payments.items():
            if asset_id is not None:
                if asset_id not in driver_dict:
                    raise ValueError("Cannot calculate announcements without driver of requested item")
                settlement_ph: bytes32 = construct_puzzle(
                    driver_dict[asset_id], OFFER_MOD_OLD if old else OFFER_MOD
                ).get_tree_hash()
            else:
                settlement_ph = OFFER_MOD_OLD_HASH if old else OFFER_MOD_HASH

            msg: bytes32 = Program.to((payments[0].nonce, [p.as_condition_args() for p in payments])).get_tree_hash()
            announcements.append(Announcement(settlement_ph, msg))

        return announcements

    def __post_init__(self) -> None:
        # Verify that there are no duplicate payments
        for payments in self.requested_payments.values():
            payment_programs: List[bytes32] = [p.name() for p in payments]
            if len(set(payment_programs)) != len(payment_programs):
                raise ValueError("Bundle has duplicate requested payments")

        # Verify we have a type for every kind of asset
        for asset_id in self.requested_payments:
            if asset_id is not None and asset_id not in self.driver_dict:
                raise ValueError("Offer does not have enough driver information about the requested payments")

    def additions(self) -> List[Coin]:
        final_list: List[Coin] = []
        for cs in self.bundle.coin_spends:
            try:
                final_list.extend(cs.additions())
            except Exception:
                pass
        return final_list

    def removals(self) -> List[Coin]:
        return self.bundle.removals()

    def incomplete_spends(self) -> List[CoinSpend]:
        final_list: List[CoinSpend] = []
        for cs in self.bundle.coin_spends:
            try:
                cs.additions()
            except Exception:
                final_list.append(cs)
        return final_list

    # This method does not get every coin that is being offered, only the `settlement_payment` children
    # It's also a little heuristic, but it should get most things
    def get_offered_coins(self) -> Dict[Optional[bytes32], List[Coin]]:
        offered_coins: Dict[Optional[bytes32], List[Coin]] = {}

        for parent_spend in self.bundle.coin_spends:
            coins_for_this_spend: List[Coin] = []

            parent_puzzle: UncurriedPuzzle = uncurry_puzzle(parent_spend.puzzle_reveal.to_program())
            parent_solution: Program = parent_spend.solution.to_program()
            additions: List[Coin] = parent_spend.additions()

            puzzle_driver = match_puzzle(parent_puzzle)
            if puzzle_driver is not None:
                asset_id = create_asset_id(puzzle_driver)
                inner_puzzle: Optional[Program] = get_inner_puzzle(puzzle_driver, parent_puzzle)
                inner_solution: Optional[Program] = get_inner_solution(puzzle_driver, parent_solution)
                assert inner_puzzle is not None and inner_solution is not None

                # We're going to look at the conditions created by the inner puzzle
                conditions: Program = inner_puzzle.run(inner_solution)
                expected_num_matches: int = 0
                offered_amounts: List[int] = []
                for condition in conditions.as_iter():
                    if condition.first() == 51 and condition.rest().first() in [OFFER_MOD_HASH, OFFER_MOD_OLD_HASH]:
                        expected_num_matches += 1
                        offered_amounts.append(condition.rest().rest().first().as_int())

                # Start by filtering additions that match the amount
                matching_spend_additions = [a for a in additions if a.amount in offered_amounts]

                if len(matching_spend_additions) == expected_num_matches:
                    coins_for_this_spend.extend(matching_spend_additions)
                # We didn't quite get there so now lets narrow it down by puzzle hash
                else:
                    # If we narrowed down too much, we can't trust the amounts so start over with all additions
                    if len(matching_spend_additions) < expected_num_matches:
                        matching_spend_additions = additions
                    matching_spend_additions = [
                        a
                        for a in matching_spend_additions
                        if a.puzzle_hash
                        in [
                            construct_puzzle(puzzle_driver, OFFER_MOD_OLD_HASH).get_tree_hash_precalc(  # type: ignore
                                OFFER_MOD_OLD_HASH
                            ),
                            construct_puzzle(puzzle_driver, OFFER_MOD_HASH).get_tree_hash_precalc(  # type: ignore
                                OFFER_MOD_HASH
                            ),
                        ]
                    ]
                    if len(matching_spend_additions) == expected_num_matches:
                        coins_for_this_spend.extend(matching_spend_additions)
                    else:
                        raise ValueError("Could not properly guess offered coins from parent spend")
            else:
                # It's much easier if the asset is bare XCH
                asset_id = None
                coins_for_this_spend.extend(
                    [a for a in additions if a.puzzle_hash in [OFFER_MOD_HASH, OFFER_MOD_OLD_HASH]]
                )

            # We only care about unspent coins
            coins_for_this_spend = [c for c in coins_for_this_spend if c not in self.bundle.removals()]

            if coins_for_this_spend != []:
                offered_coins.setdefault(asset_id, [])
                offered_coins[asset_id].extend(coins_for_this_spend)

        return offered_coins

    def get_offered_amounts(self) -> Dict[Optional[bytes32], int]:
        offered_coins: Dict[Optional[bytes32], List[Coin]] = self.get_offered_coins()
        offered_amounts: Dict[Optional[bytes32], int] = {}
        for asset_id, coins in offered_coins.items():
            offered_amounts[asset_id] = uint64(sum([c.amount for c in coins]))
        return offered_amounts

    def get_requested_payments(self) -> Dict[Optional[bytes32], List[NotarizedPayment]]:
        return self.requested_payments

    def get_requested_amounts(self) -> Dict[Optional[bytes32], int]:
        requested_amounts: Dict[Optional[bytes32], int] = {}
        for asset_id, coins in self.get_requested_payments().items():
            requested_amounts[asset_id] = uint64(sum([c.amount for c in coins]))
        return requested_amounts

    def arbitrage(self) -> Dict[Optional[bytes32], int]:
        """
        Returns a dictionary of the type of each asset and amount that is involved in the trade
        With the amount being how much their offered amount within the offer
        exceeds/falls short of their requested amount.
        """
        offered_amounts: Dict[Optional[bytes32], int] = self.get_offered_amounts()
        requested_amounts: Dict[Optional[bytes32], int] = self.get_requested_amounts()

        arbitrage_dict: Dict[Optional[bytes32], int] = {}
        for asset_id in [*requested_amounts.keys(), *offered_amounts.keys()]:
            arbitrage_dict[asset_id] = offered_amounts.get(asset_id, 0) - requested_amounts.get(asset_id, 0)

        return arbitrage_dict

    # This is a method mostly for the UI that creates a JSON summary of the offer
    def summary(self) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, Dict[str, Any]]]:
        offered_amounts: Dict[Optional[bytes32], int] = self.get_offered_amounts()
        requested_amounts: Dict[Optional[bytes32], int] = self.get_requested_amounts()

        def keys_to_strings(dic: Dict[Optional[bytes32], Any]) -> Dict[str, Any]:
            new_dic: Dict[str, Any] = {}
            for key in dic:
                if key is None:
                    new_dic["xch"] = dic[key]
                else:
                    new_dic[key.hex()] = dic[key]
            return new_dic

        driver_dict: Dict[str, Any] = {}
        for key, value in self.driver_dict.items():
            driver_dict[key.hex()] = value.info

        return keys_to_strings(offered_amounts), keys_to_strings(requested_amounts), driver_dict

    # Also mostly for the UI, returns a dictionary of assets and how much of them is pended for this offer
    # This method is also imperfect for sufficiently complex spends
    def get_pending_amounts(self) -> Dict[str, int]:
        all_additions: List[Coin] = self.additions()
        all_removals: List[Coin] = self.removals()
        non_ephemeral_removals: List[Coin] = list(filter(lambda c: c not in all_additions, all_removals))

        pending_dict: Dict[str, int] = {}
        # First we add up the amounts of all coins that share an ancestor with the offered coins (i.e. a primary coin)
        for asset_id, coins in self.get_offered_coins().items():
            name = "xch" if asset_id is None else asset_id.hex()
            pending_dict[name] = 0
            for coin in coins:
                root_removal: Coin = self.get_root_removal(coin)

                for addition in filter(lambda c: c.parent_coin_info == root_removal.name(), all_additions):
                    pending_dict[name] += addition.amount

        # Then we gather anything else as unknown
        sum_of_additions_so_far: int = sum(pending_dict.values())
        unknown: int = sum([c.amount for c in non_ephemeral_removals]) - sum_of_additions_so_far
        if unknown > 0:
            pending_dict["unknown"] = unknown

        return pending_dict

    # This method returns all of the coins that are being used in the offer (without which it would be invalid)
    def get_involved_coins(self) -> List[Coin]:
        additions = self.additions()
        return list(filter(lambda c: c not in additions, self.removals()))

    # This returns the non-ephemeral removal that is an ancestor of the specified coin
    # This should maybe move to the SpendBundle object at some point
    def get_root_removal(self, coin: Coin) -> Coin:
        all_removals: Set[Coin] = set(self.removals())
        all_removal_ids: Set[bytes32] = {c.name() for c in all_removals}
        non_ephemeral_removals: Set[Coin] = {
            c for c in all_removals if c.parent_coin_info not in {r.name() for r in all_removals}
        }
        if coin.name() not in all_removal_ids and coin.parent_coin_info not in all_removal_ids:
            raise ValueError("The specified coin is not a coin in this bundle")

        while coin not in non_ephemeral_removals:
            coin = next(c for c in all_removals if c.name() == coin.parent_coin_info)

        return coin

    # This will only return coins that are ancestors of settlement payments
    def get_primary_coins(self) -> List[Coin]:
        primary_coins: Set[Coin] = set()
        for _, coins in self.get_offered_coins().items():
            for coin in coins:
                primary_coins.add(self.get_root_removal(coin))
        return list(primary_coins)

    # This returns the minimum coins that when spent will invalidate the rest of the bundle
    def get_cancellation_coins(self) -> List[Coin]:
        # First, we're going to gather:
        dependencies: Dict[bytes32, List[bytes32]] = {}  # all of the hashes that each coin depends on
        announcements: Dict[bytes32, List[bytes32]] = {}  # all of the hashes of the announcement that each coin makes
        coin_names: List[bytes32] = []  # The names of all the coins
        for spend in [cs for cs in self.bundle.coin_spends if cs.coin not in self.bundle.additions()]:
            name = bytes32(spend.coin.name())
            coin_names.append(name)
            dependencies[name] = []
            announcements[name] = []
            conditions: Program = spend.puzzle_reveal.run_with_cost(INFINITE_COST, spend.solution)[1]
            for condition in conditions.as_iter():
                if condition.first() == 60:  # create coin announcement
                    announcements[name].append(Announcement(name, condition.at("rf").as_python()).name())
                elif condition.first() == 61:  # assert coin announcement
                    dependencies[name].append(bytes32(condition.at("rf").as_python()))

        # We now enter a loop that is attempting to express the following logic:
        # "If I am depending on another coin in the same bundle, you may as well cancel that coin instead of me"
        # By the end of the loop, we should have filtered down the list of coin_names to include only those that will
        # cancel everything else
        while True:
            removed = detect_dependent_coin(coin_names, dependencies, announcements)
            if removed is None:
                break
            removed_coin, provider = removed
            removed_announcements: List[bytes32] = announcements[removed_coin]
            remove_these_keys: List[bytes32] = [removed_coin]
            while True:
                for coin, deps in dependencies.items():
                    if set(deps) & set(removed_announcements) and coin != provider:
                        remove_these_keys.append(coin)
                removed_announcements = []
                for coin in remove_these_keys:
                    dependencies.pop(coin)
                    removed_announcements.extend(announcements.pop(coin))
                coin_names = [n for n in coin_names if n not in remove_these_keys]
                if removed_announcements == []:
                    break
                else:
                    remove_these_keys = []

        return [cs.coin for cs in self.bundle.coin_spends if cs.coin.name() in coin_names]

    @classmethod
    def aggregate(cls, offers: List[Offer]) -> Offer:
        total_requested_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = {}
        total_bundle = SpendBundle([], G2Element())
        total_driver_dict: Dict[bytes32, PuzzleInfo] = {}
        old: bool = False
        for i, offer in enumerate(offers):
            # First check for any overlap in inputs
            total_inputs: Set[Coin] = {cs.coin for cs in total_bundle.coin_spends}
            offer_inputs: Set[Coin] = {cs.coin for cs in offer.bundle.coin_spends}
            if total_inputs & offer_inputs:
                raise ValueError("The aggregated offers overlap inputs")

            # Next, do the aggregation
            for asset_id, payments in offer.requested_payments.items():
                if asset_id in total_requested_payments:
                    total_requested_payments[asset_id].extend(payments)
                else:
                    total_requested_payments[asset_id] = payments

            for key, value in offer.driver_dict.items():
                if key in total_driver_dict and total_driver_dict[key] != value:
                    raise ValueError(f"The offers to aggregate disagree on the drivers for {key.hex()}")

            total_bundle = SpendBundle.aggregate([total_bundle, offer.bundle])
            total_driver_dict.update(offer.driver_dict)
            if i == 0:
                old = offer.old
            else:
                if offer.old != old:
                    raise ValueError("Attempting to aggregate two offers with different mods")

        return cls(total_requested_payments, total_bundle, total_driver_dict, old)

    # Validity is defined by having enough funds within the offer to satisfy both sides
    def is_valid(self) -> bool:
        return all([value >= 0 for value in self.arbitrage().values()])

    # A "valid" spend means that this bundle can be pushed to the network and will succeed
    # This differs from the `to_spend_bundle` method which deliberately creates an invalid SpendBundle
    def to_valid_spend(self, arbitrage_ph: Optional[bytes32] = None) -> SpendBundle:
        if not self.is_valid():
            raise ValueError("Offer is currently incomplete")

        completion_spends: List[CoinSpend] = []
        all_offered_coins: Dict[Optional[bytes32], List[Coin]] = self.get_offered_coins()
        total_arbitrage_amount: Dict[Optional[bytes32], int] = self.arbitrage()
        for asset_id, payments in self.requested_payments.items():
            offered_coins: List[Coin] = all_offered_coins[asset_id]

            # Because of CAT supply laws, we must specify a place for the leftovers to go
            arbitrage_amount: int = total_arbitrage_amount[asset_id]
            all_payments: List[NotarizedPayment] = payments.copy()
            if arbitrage_amount > 0:
                assert arbitrage_amount is not None
                assert arbitrage_ph is not None
                all_payments.append(NotarizedPayment(arbitrage_ph, uint64(arbitrage_amount), []))

            # Some assets need to know about siblings so we need to collect all spends first to be able to use them
            coin_to_spend_dict: Dict[Coin, CoinSpend] = {}
            coin_to_solution_dict: Dict[Coin, Program] = {}
            for coin in offered_coins:
                parent_spend: CoinSpend = list(
                    filter(lambda cs: cs.coin.name() == coin.parent_coin_info, self.bundle.coin_spends)
                )[0]
                coin_to_spend_dict[coin] = parent_spend

                inner_solutions = []
                if coin == offered_coins[0]:
                    nonces: List[bytes32] = [p.nonce for p in all_payments]
                    for nonce in list(dict.fromkeys(nonces)):  # dedup without messing with order
                        nonce_payments: List[NotarizedPayment] = list(filter(lambda p: p.nonce == nonce, all_payments))
                        inner_solutions.append((nonce, [np.as_condition_args() for np in nonce_payments]))
                coin_to_solution_dict[coin] = Program.to(inner_solutions)

            for coin in offered_coins:
                if asset_id:
                    if coin.puzzle_hash == construct_puzzle(
                        self.driver_dict[asset_id], OFFER_MOD_OLD_HASH  # type: ignore
                    ).get_tree_hash_precalc(OFFER_MOD_OLD_HASH):
                        offer_mod: Program = OFFER_MOD_OLD
                    else:
                        offer_mod = OFFER_MOD
                    siblings: str = "("
                    sibling_spends: str = "("
                    sibling_puzzles: str = "("
                    sibling_solutions: str = "("
                    disassembled_offer_mod: str = disassemble(offer_mod)
                    for sibling_coin in offered_coins:
                        if sibling_coin != coin:
                            siblings += (
                                "0x"
                                + sibling_coin.parent_coin_info.hex()
                                + sibling_coin.puzzle_hash.hex()
                                + bytes(uint64(sibling_coin.amount)).hex()
                                + " "
                            )
                            sibling_spends += "0x" + bytes(coin_to_spend_dict[sibling_coin]).hex() + " "
                            sibling_puzzles += disassembled_offer_mod + " "
                            sibling_solutions += disassemble(coin_to_solution_dict[sibling_coin]) + " "
                    siblings += ")"
                    sibling_spends += ")"
                    sibling_puzzles += ")"
                    sibling_solutions += ")"

                    solution: Program = solve_puzzle(
                        self.driver_dict[asset_id],
                        Solver(
                            {
                                "coin": "0x"
                                + coin.parent_coin_info.hex()
                                + coin.puzzle_hash.hex()
                                + bytes(uint64(coin.amount)).hex(),
                                "parent_spend": "0x" + bytes(coin_to_spend_dict[coin]).hex(),
                                "siblings": siblings,
                                "sibling_spends": sibling_spends,
                                "sibling_puzzles": sibling_puzzles,
                                "sibling_solutions": sibling_solutions,
                            }
                        ),
                        offer_mod,
                        Program.to(coin_to_solution_dict[coin]),
                    )
                else:
                    if coin.puzzle_hash == OFFER_MOD_OLD_HASH:
                        offer_mod = OFFER_MOD_OLD
                    else:
                        offer_mod = OFFER_MOD
                    solution = Program.to(coin_to_solution_dict[coin])

                completion_spends.append(
                    CoinSpend(
                        coin,
                        construct_puzzle(self.driver_dict[asset_id], offer_mod) if asset_id else offer_mod,
                        solution,
                    )
                )

        return SpendBundle.aggregate([SpendBundle(completion_spends, G2Element()), self.bundle])

    def to_spend_bundle(self) -> SpendBundle:
        # Before we serialze this as a SpendBundle, we need to serialze the `requested_payments` as dummy CoinSpends
        additional_coin_spends: List[CoinSpend] = []
        for asset_id, payments in self.requested_payments.items():
            puzzle_reveal: Program = construct_puzzle(self.driver_dict[asset_id], OFFER_MOD) if asset_id else OFFER_MOD
            inner_solutions = []
            nonces: List[bytes32] = [p.nonce for p in payments]
            for nonce in list(dict.fromkeys(nonces)):  # dedup without messing with order
                nonce_payments: List[NotarizedPayment] = list(filter(lambda p: p.nonce == nonce, payments))
                inner_solutions.append((nonce, [np.as_condition_args() for np in nonce_payments]))

            additional_coin_spends.append(
                CoinSpend(
                    Coin(
                        ZERO_32,
                        puzzle_reveal.get_tree_hash(),
                        uint64(0),
                    ),
                    puzzle_reveal,
                    Program.to(inner_solutions),
                )
            )

        return SpendBundle.aggregate(
            [
                SpendBundle(additional_coin_spends, G2Element()),
                self.bundle,
            ]
        )

    @classmethod
    def from_spend_bundle(cls, bundle: SpendBundle) -> Offer:
        # Because of the `to_spend_bundle` method, we need to parse the dummy CoinSpends as `requested_payments`
        requested_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = {}
        driver_dict: Dict[bytes32, PuzzleInfo] = {}
        leftover_coin_spends: List[CoinSpend] = []
        old: bool = False
        for coin_spend in bundle.coin_spends:
            if not old and bytes(OFFER_MOD_OLD) in bytes(coin_spend):
                old = True

            driver = match_puzzle(uncurry_puzzle(coin_spend.puzzle_reveal.to_program()))
            if driver is not None:
                asset_id = create_asset_id(driver)
                assert asset_id is not None
                driver_dict[asset_id] = driver
            else:
                asset_id = None
            if coin_spend.coin.parent_coin_info == ZERO_32:
                notarized_payments: List[NotarizedPayment] = []
                for payment_group in coin_spend.solution.to_program().as_iter():
                    nonce = bytes32(payment_group.first().as_python())
                    payment_args_list: List[Program] = payment_group.rest().as_iter()
                    notarized_payments.extend(
                        [NotarizedPayment.from_condition_and_nonce(condition, nonce) for condition in payment_args_list]
                    )

                requested_payments[asset_id] = notarized_payments
            else:
                leftover_coin_spends.append(coin_spend)

        return cls(requested_payments, SpendBundle(leftover_coin_spends, bundle.aggregated_signature), driver_dict, old)

    def name(self) -> bytes32:
        return self.to_spend_bundle().name()

    def compress(self, version: Optional[int] = None) -> bytes:
        as_spend_bundle = self.to_spend_bundle()
        if version is None:
            mods: List[bytes] = [bytes(s.puzzle_reveal.to_program().uncurry()[0]) for s in as_spend_bundle.coin_spends]
            version = max(lowest_best_version(mods), 6)  # Clients lower than version 6 should not be able to parse
        return compress_object_with_puzzles(bytes(as_spend_bundle), version)

    @classmethod
    def from_compressed(cls, compressed_bytes: bytes) -> Offer:
        return Offer.from_bytes(decompress_object_with_puzzles(compressed_bytes))

    @classmethod
    def try_offer_decompression(cls, offer_bytes: bytes) -> Offer:
        try:
            return cls.from_compressed(offer_bytes)
        except TypeError:
            pass
        return cls.from_bytes(offer_bytes)

    def to_bech32(self, prefix: str = "offer", compression_version: Optional[int] = None) -> str:
        offer_bytes = self.compress(version=compression_version)
        encoded = bech32_encode(prefix, convertbits(list(offer_bytes), 8, 5))
        return encoded

    @classmethod
    def from_bech32(cls, offer_bech32: str) -> Offer:
        hrpgot, data = bech32_decode(offer_bech32, max_length=len(offer_bech32))
        if data is None:
            raise ValueError("Invalid Offer")
        decoded = convertbits(list(data), 5, 8, False)
        decoded_bytes = bytes(decoded)
        return cls.try_offer_decompression(decoded_bytes)

    # Methods to make this a valid Streamable member
    # We basically hijack the SpendBundle versions for most of it
    @classmethod
    def parse(cls, f: BinaryIO) -> Offer:
        parsed_bundle = SpendBundle.parse(f)
        return cls.from_bytes(bytes(parsed_bundle))

    def stream(self, f: BinaryIO) -> None:
        as_spend_bundle = SpendBundle.from_bytes(bytes(self))
        as_spend_bundle.stream(f)

    def __bytes__(self) -> bytes:
        return bytes(self.to_spend_bundle())

    @classmethod
    def from_bytes(cls, as_bytes: bytes) -> Offer:
        # Because of the __bytes__ method, we need to parse the dummy CoinSpends as `requested_payments`
        bundle = SpendBundle.from_bytes(as_bytes)
        return cls.from_spend_bundle(bundle)
