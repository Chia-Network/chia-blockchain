from dataclasses import dataclass
from typing import List, Optional, Dict, Set, Tuple
from blspy import G2Element

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.announcement import Announcement
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import bech32_encode, bech32_decode, convertbits
from chia.util.ints import uint64
from chia.wallet.util.puzzle_compression import (
    compress_object_with_puzzles,
    decompress_object_with_puzzles,
    lowest_best_version,
)
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    match_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.payment import Payment

OFFER_MOD = load_clvm("settlement_payments.clvm")
ZERO_32 = bytes32([0] * 32)


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

    @staticmethod
    def ph():
        return OFFER_MOD.get_tree_hash()

    @staticmethod
    def notarize_payments(
        requested_payments: Dict[Optional[bytes32], List[Payment]],  # `None` means you are requesting XCH
        coins: List[Coin],
    ) -> Dict[Optional[bytes32], List[NotarizedPayment]]:
        # This sort should be reproducible in CLVM with `>s`
        sorted_coins: List[Coin] = sorted(coins, key=Coin.name)
        sorted_coin_list: List[List] = [c.as_list() for c in sorted_coins]
        nonce: bytes32 = Program.to(sorted_coin_list).get_tree_hash()

        notarized_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = {}
        for tail_hash, payments in requested_payments.items():
            notarized_payments[tail_hash] = []
            for p in payments:
                puzzle_hash, amount, memos = tuple(p.as_condition_args())
                notarized_payments[tail_hash].append(NotarizedPayment(puzzle_hash, amount, memos, nonce))

        return notarized_payments

    # The announcements returned from this function must be asserted in whatever spend bundle is created by the wallet
    @staticmethod
    def calculate_announcements(
        notarized_payments: Dict[Optional[bytes32], List[NotarizedPayment]],
    ) -> List[Announcement]:
        announcements: List[Announcement] = []
        for tail, payments in notarized_payments.items():
            if tail is not None:
                settlement_ph: bytes32 = construct_cat_puzzle(CAT_MOD, tail, OFFER_MOD).get_tree_hash()
            else:
                settlement_ph = OFFER_MOD.get_tree_hash()

            msg: bytes32 = Program.to((payments[0].nonce, [p.as_condition_args() for p in payments])).get_tree_hash()
            announcements.append(Announcement(settlement_ph, msg))

        return announcements

    def __post_init__(self):
        # Verify that there is at least something being offered
        offered_coins: Dict[bytes32, List[Coin]] = self.get_offered_coins()
        if offered_coins == {}:
            raise ValueError("Bundle is not offering anything")

        # Verify that there are no duplicate payments
        for payments in self.requested_payments.values():
            payment_programs: List[bytes32] = [p.name() for p in payments]
            if len(set(payment_programs)) != len(payment_programs):
                raise ValueError("Bundle has duplicate requested payments")

    # This method does not get every coin that is being offered, only the `settlement_payment` children
    def get_offered_coins(self) -> Dict[Optional[bytes32], List[Coin]]:
        offered_coins: Dict[Optional[bytes32], List[Coin]] = {}

        for addition in self.bundle.additions():
            # Get the parent puzzle
            parent_puzzle: Program = list(
                filter(lambda cs: cs.coin.name() == addition.parent_coin_info, self.bundle.coin_spends)
            )[0].puzzle_reveal.to_program()

            # Determine it's TAIL (or lack of)
            matched, curried_args = match_cat_puzzle(parent_puzzle)
            tail_hash: Optional[bytes32] = None
            if matched:
                _, tail_hash_program, _ = curried_args
                tail_hash = bytes32(tail_hash_program.as_python())
                offer_ph: bytes32 = construct_cat_puzzle(CAT_MOD, tail_hash, OFFER_MOD).get_tree_hash()
            else:
                tail_hash = None
                offer_ph = OFFER_MOD.get_tree_hash()

            # Check if the puzzle_hash matches the hypothetical `settlement_payments` puzzle hash
            if addition.puzzle_hash == offer_ph:
                if tail_hash in offered_coins:
                    offered_coins[tail_hash].append(addition)
                else:
                    offered_coins[tail_hash] = [addition]

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
        offered_amounts: Dict[Optional[bytes32], int] = self.get_offered_amounts()
        requested_amounts: Dict[Optional[bytes32], int] = self.get_requested_amounts()

        arbitrage_dict: Dict[Optional[bytes32], int] = {}
        for asset_id in [*requested_amounts.keys(), *offered_amounts.keys()]:
            arbitrage_dict[asset_id] = offered_amounts.get(asset_id, 0) - requested_amounts.get(asset_id, 0)

        return arbitrage_dict

    # This is a method mostly for the UI that creates a JSON summary of the offer
    def summary(self) -> Tuple[Dict[str, int], Dict[str, int]]:
        offered_amounts: Dict[Optional[bytes32], int] = self.get_offered_amounts()
        requested_amounts: Dict[Optional[bytes32], int] = self.get_requested_amounts()

        def keys_to_strings(dic: Dict[Optional[bytes32], int]) -> Dict[str, int]:
            new_dic: Dict[str, int] = {}
            for key in dic:
                if key is None:
                    new_dic["xch"] = dic[key]
                else:
                    new_dic[key.hex()] = dic[key]
            return new_dic

        return keys_to_strings(offered_amounts), keys_to_strings(requested_amounts)

    # Also mostly for the UI, returns a dictionary of assets and how much of them is pended for this offer
    # This method is also imperfect for sufficiently complex spends
    def get_pending_amounts(self) -> Dict[str, int]:
        all_additions: List[Coin] = self.bundle.additions()
        all_removals: List[Coin] = self.bundle.removals()
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

        # Then we add a potential fee as pending XCH
        fee: int = sum(c.amount for c in all_removals) - sum(c.amount for c in all_additions)
        if fee > 0:
            pending_dict.setdefault("xch", 0)
            pending_dict["xch"] += fee

        # Then we gather anything else as unknown
        sum_of_additions_so_far: int = sum(pending_dict.values())
        unknown: int = sum([c.amount for c in non_ephemeral_removals]) - sum_of_additions_so_far
        if unknown > 0:
            pending_dict["unknown"] = unknown

        return pending_dict

    # This method returns all of the coins that are being used in the offer (without which it would be invalid)
    def get_involved_coins(self) -> List[Coin]:
        additions = self.bundle.additions()
        return list(filter(lambda c: c not in additions, self.bundle.removals()))

    # This returns the non-ephemeral removal that is an ancestor of the specified coin
    # This should maybe move to the SpendBundle object at some point
    def get_root_removal(self, coin: Coin) -> Coin:
        all_removals: Set[Coin] = set(self.bundle.removals())
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

    @classmethod
    def aggregate(cls, offers: List["Offer"]) -> "Offer":
        total_requested_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = {}
        total_bundle = SpendBundle([], G2Element())
        for offer in offers:
            # First check for any overlap in inputs
            total_inputs: Set[Coin] = {cs.coin for cs in total_bundle.coin_spends}
            offer_inputs: Set[Coin] = {cs.coin for cs in offer.bundle.coin_spends}
            if total_inputs & offer_inputs:
                raise ValueError("The aggregated offers overlap inputs")

            # Next, do the aggregation
            for tail, payments in offer.requested_payments.items():
                if tail in total_requested_payments:
                    total_requested_payments[tail].extend(payments)
                else:
                    total_requested_payments[tail] = payments

            total_bundle = SpendBundle.aggregate([total_bundle, offer.bundle])

        return cls(total_requested_payments, total_bundle)

    # Validity is defined by having enough funds within the offer to satisfy both sides
    def is_valid(self) -> bool:
        return all([value >= 0 for value in self.arbitrage().values()])

    # A "valid" spend means that this bundle can be pushed to the network and will succeed
    # This differs from the `to_spend_bundle` method which deliberately creates an invalid SpendBundle
    def to_valid_spend(self, arbitrage_ph: Optional[bytes32] = None) -> SpendBundle:
        if not self.is_valid():
            raise ValueError("Offer is currently incomplete")

        completion_spends: List[CoinSpend] = []
        for tail_hash, payments in self.requested_payments.items():
            offered_coins: List[Coin] = self.get_offered_coins()[tail_hash]

            # Because of CAT supply laws, we must specify a place for the leftovers to go
            arbitrage_amount: int = self.arbitrage()[tail_hash]
            all_payments: List[NotarizedPayment] = payments.copy()
            if arbitrage_amount > 0:
                assert arbitrage_amount is not None
                assert arbitrage_ph is not None
                all_payments.append(NotarizedPayment(arbitrage_ph, uint64(arbitrage_amount), []))

            for coin in offered_coins:
                inner_solutions = []
                if coin == offered_coins[0]:
                    nonces: List[bytes32] = [p.nonce for p in all_payments]
                    for nonce in list(dict.fromkeys(nonces)):  # dedup without messing with order
                        nonce_payments: List[NotarizedPayment] = list(filter(lambda p: p.nonce == nonce, all_payments))
                        inner_solutions.append((nonce, [np.as_condition_args() for np in nonce_payments]))

                if tail_hash:
                    # CATs have a special way to be solved so we have to do some calculation before getting the solution
                    parent_spend: CoinSpend = list(
                        filter(lambda cs: cs.coin.name() == coin.parent_coin_info, self.bundle.coin_spends)
                    )[0]
                    parent_coin: Coin = parent_spend.coin
                    matched, curried_args = match_cat_puzzle(parent_spend.puzzle_reveal.to_program())
                    assert matched
                    _, _, inner_puzzle = curried_args
                    spendable_cat = SpendableCAT(
                        coin,
                        tail_hash,
                        OFFER_MOD,
                        Program.to(inner_solutions),
                        lineage_proof=LineageProof(
                            parent_coin.parent_coin_info, inner_puzzle.get_tree_hash(), parent_coin.amount
                        ),
                    )
                    solution: Program = (
                        unsigned_spend_bundle_for_spendable_cats(CAT_MOD, [spendable_cat])
                        .coin_spends[0]
                        .solution.to_program()
                    )
                else:
                    solution = Program.to(inner_solutions)

                completion_spends.append(
                    CoinSpend(
                        coin,
                        construct_cat_puzzle(CAT_MOD, tail_hash, OFFER_MOD) if tail_hash else OFFER_MOD,
                        solution,
                    )
                )

        return SpendBundle.aggregate([SpendBundle(completion_spends, G2Element()), self.bundle])

    def to_spend_bundle(self) -> SpendBundle:
        # Before we serialze this as a SpendBundle, we need to serialze the `requested_payments` as dummy CoinSpends
        additional_coin_spends: List[CoinSpend] = []
        for tail_hash, payments in self.requested_payments.items():
            puzzle_reveal: Program = construct_cat_puzzle(CAT_MOD, tail_hash, OFFER_MOD) if tail_hash else OFFER_MOD
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
    def from_spend_bundle(cls, bundle: SpendBundle) -> "Offer":
        # Because of the `to_spend_bundle` method, we need to parse the dummy CoinSpends as `requested_payments`
        requested_payments: Dict[Optional[bytes32], List[NotarizedPayment]] = {}
        leftover_coin_spends: List[CoinSpend] = []
        for coin_spend in bundle.coin_spends:
            if coin_spend.coin.parent_coin_info == ZERO_32:
                matched, curried_args = match_cat_puzzle(coin_spend.puzzle_reveal.to_program())
                if matched:
                    _, tail_hash_program, _ = curried_args
                    tail_hash: Optional[bytes32] = bytes32(tail_hash_program.as_python())
                else:
                    tail_hash = None

                notarized_payments: List[NotarizedPayment] = []
                for payment_group in coin_spend.solution.to_program().as_iter():
                    nonce = bytes32(payment_group.first().as_python())
                    payment_args_list: List[Program] = payment_group.rest().as_iter()
                    notarized_payments.extend(
                        [NotarizedPayment.from_condition_and_nonce(condition, nonce) for condition in payment_args_list]
                    )
                requested_payments[tail_hash] = notarized_payments

            else:
                leftover_coin_spends.append(coin_spend)

        return cls(requested_payments, SpendBundle(leftover_coin_spends, bundle.aggregated_signature))

    def name(self) -> bytes32:
        return self.to_spend_bundle().name()

    def compress(self, version=None) -> bytes:
        as_spend_bundle = self.to_spend_bundle()
        if version is None:
            mods: List[bytes] = [bytes(s.puzzle_reveal.to_program().uncurry()[0]) for s in as_spend_bundle.coin_spends]
            version = max(lowest_best_version(mods), 2)  # 2 is the version where OFFER_MOD lives
        return compress_object_with_puzzles(bytes(as_spend_bundle), version)

    @classmethod
    def from_compressed(cls, compressed_bytes: bytes) -> "Offer":
        return Offer.from_bytes(decompress_object_with_puzzles(compressed_bytes))

    @classmethod
    def try_offer_decompression(cls, offer_bytes: bytes) -> "Offer":
        try:
            return cls.from_compressed(offer_bytes)
        except TypeError:
            pass
        return cls.from_bytes(offer_bytes)

    def to_bech32(self, prefix: str = "offer", compression_version=None) -> str:
        offer_bytes = self.compress(version=compression_version)
        encoded = bech32_encode(prefix, convertbits(list(offer_bytes), 8, 5))
        return encoded

    @classmethod
    def from_bech32(cls, offer_bech32: str) -> "Offer":
        hrpgot, data = bech32_decode(offer_bech32, max_length=len(offer_bech32))
        if data is None:
            raise ValueError("Invalid Offer")
        decoded = convertbits(list(data), 5, 8, False)
        decoded_bytes = bytes(decoded)
        return cls.try_offer_decompression(decoded_bytes)

    # Methods to make this a valid Streamable member
    # We basically hijack the SpendBundle versions for most of it
    @classmethod
    def parse(cls, f) -> "Offer":
        parsed_bundle = SpendBundle.parse(f)
        return cls.from_bytes(bytes(parsed_bundle))

    def stream(self, f):
        as_spend_bundle = SpendBundle.from_bytes(bytes(self))
        as_spend_bundle.stream(f)

    def __bytes__(self) -> bytes:
        return bytes(self.to_spend_bundle())

    @classmethod
    def from_bytes(cls, as_bytes: bytes) -> "Offer":
        # Because of the __bytes__ method, we need to parse the dummy CoinSpends as `requested_payments`
        bundle = SpendBundle.from_bytes(as_bytes)
        return cls.from_spend_bundle(bundle)
