from __future__ import annotations

import functools
from dataclasses import dataclass, replace
from typing import Iterable, List, Optional, Tuple, Type, TypeVar

from clvm.casts import int_to_bytes

from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.hash import std_hash
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, construct_cat_puzzle
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.payment import Payment
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_LAUNCHER_HASH, SINGLETON_MOD_HASH
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle
from chia.wallet.vc_wallet.vc_drivers import (
    COVENANT_LAYER_HASH,
    EML_TP_COVENANT_ADAPTER_HASH,
    EXTIGENT_METADATA_LAYER_HASH,
    GUARANTEED_NIL_TP,
    P2_ANNOUNCED_DELEGATED_PUZZLE,
    create_did_tp,
    create_eml_covenant_morpher,
)

# Mods
CREDENTIAL_RESTRICTION: Program = load_clvm_maybe_recompile(
    "credential_restriction.clsp",
    package_or_requirement="chia.wallet.vc_wallet.cr_puzzles",
    include_standard_libraries=True,
)
CREDENTIAL_RESTRICTION_HASH: bytes32 = CREDENTIAL_RESTRICTION.get_tree_hash()
PROOF_FLAGS_CHECKER: Program = load_clvm_maybe_recompile(
    "flag_proofs_checker.clsp",
    package_or_requirement="chia.wallet.vc_wallet.cr_puzzles",
    include_standard_libraries=True,
)


# Basic drivers
def construct_cr_layer(
    authorized_providers: List[bytes32],
    proofs_checker: Program,
    inner_puzzle: Program,
) -> Program:
    first_curry: Program = CREDENTIAL_RESTRICTION.curry(
        Program.to(
            (
                (
                    (
                        SINGLETON_MOD_HASH,
                        SINGLETON_LAUNCHER_HASH,
                    ),
                    (
                        EXTIGENT_METADATA_LAYER_HASH,
                        EML_TP_COVENANT_ADAPTER_HASH,
                    ),
                ),
                (
                    Program.to(EXTIGENT_METADATA_LAYER_HASH)
                    .curry(
                        Program.to(EXTIGENT_METADATA_LAYER_HASH).get_tree_hash(),
                        Program.to(None),
                        GUARANTEED_NIL_TP,
                        GUARANTEED_NIL_TP.get_tree_hash(),
                        P2_ANNOUNCED_DELEGATED_PUZZLE,
                    )
                    .get_tree_hash_precalc(
                        EXTIGENT_METADATA_LAYER_HASH, Program.to(EXTIGENT_METADATA_LAYER_HASH).get_tree_hash()
                    ),
                    (
                        Program.to(
                            int_to_bytes(2)
                            + Program.to((1, COVENANT_LAYER_HASH)).get_tree_hash_precalc(COVENANT_LAYER_HASH)
                        ),
                        Program.to(
                            (
                                [
                                    4,
                                    (1, create_eml_covenant_morpher(create_did_tp().get_tree_hash())),
                                    [4, (1, create_did_tp()), 1],
                                ],
                                None,
                            )
                        ).get_tree_hash(),
                    ),
                ),
            ),
        ),
        authorized_providers,
        proofs_checker,
    )
    return first_curry.curry(first_curry.get_tree_hash(), inner_puzzle)


# Coverage coming with CR-CAT Wallet
def match_cr_layer(
    uncurried_puzzle: UncurriedPuzzle,
) -> Optional[Tuple[List[bytes32], Program, Program]]:  # pragma: no cover
    if uncurried_puzzle.mod == CREDENTIAL_RESTRICTION:
        extra_uncurried_puzzle = uncurry_puzzle(uncurried_puzzle.mod)
        return (
            [bytes32(provider.atom) for provider in extra_uncurried_puzzle.args.at("rf").as_iter()],
            extra_uncurried_puzzle.args.at("rrf"),
            uncurried_puzzle.args.at("rf"),
        )
    else:
        return None


def solve_cr_layer(
    proof_of_inclusions: Program,
    proof_checker_solution: Program,
    provider_id: bytes32,
    vc_launcher_id: bytes32,
    vc_inner_puzhash: bytes32,
    my_coin_id: bytes32,
    inner_solution: Program,
) -> Program:
    solution: Program = Program.to(
        [
            proof_of_inclusions,
            proof_checker_solution,
            provider_id,
            vc_launcher_id,
            vc_inner_puzhash,
            my_coin_id,
            inner_solution,
        ]
    )
    return solution


_T_CRCAT = TypeVar("_T_CRCAT", bound="CRCAT")


@dataclass(frozen=True)
class CRCAT:
    coin: Coin
    tail_hash: bytes32
    lineage_proof: LineageProof
    authorized_providers: List[bytes32]
    proofs_checker: Program
    inner_puzzle_hash: bytes32

    @classmethod
    def launch(
        cls: Type[_T_CRCAT],
        # General CAT launching info
        origin_coin: Coin,
        payment: Payment,
        tail: Program,
        tail_solution: Program,
        # CR Layer params
        authorized_providers: List[bytes32],
        proofs_checker: Program,
        # Probably never need this but some tail might
        optional_lineage_proof: Optional[LineageProof] = None,
    ) -> Tuple[Program, CoinSpend, CRCAT]:
        """
        Launch a new CR-CAT from XCH.

        Returns a delegated puzzle to run that creates the eve CAT, an eve coin spend of the CAT, and the expected class
        representation after all relevant coin spends have been confirmed on chain.
        """
        tail_hash: bytes32 = tail.get_tree_hash()

        new_cr_layer_hash: bytes32 = construct_cr_layer(
            authorized_providers,
            proofs_checker,
            payment.puzzle_hash,  # type: ignore
        ).get_tree_hash_precalc(payment.puzzle_hash)
        new_cat_puzhash: bytes32 = construct_cat_puzzle(
            CAT_MOD,
            tail_hash,
            new_cr_layer_hash,  # type: ignore
        ).get_tree_hash_precalc(new_cr_layer_hash)

        eve_innerpuz: Program = Program.to(
            (
                1,
                [
                    [51, new_cr_layer_hash, payment.amount, payment.memos],
                    [51, None, -113, tail, tail_solution],
                    [60, None],
                    [1, payment.puzzle_hash, authorized_providers, proofs_checker],
                ],
            )
        )
        eve_cat_puzzle: Program = construct_cat_puzzle(
            CAT_MOD,
            tail_hash,
            eve_innerpuz,
        )
        eve_cat_puzzle_hash: bytes32 = eve_cat_puzzle.get_tree_hash()

        eve_coin: Coin = Coin(origin_coin.name(), eve_cat_puzzle_hash, payment.amount)
        dpuz: Program = Program.to(
            (
                1,
                [
                    [51, eve_cat_puzzle_hash, payment.amount],
                    [61, std_hash(eve_coin.name())],
                ],
            )
        )

        eve_proof: LineageProof = LineageProof(
            eve_coin.parent_coin_info,
            eve_innerpuz.get_tree_hash(),
            uint64(eve_coin.amount),
        )

        return (
            dpuz,
            CoinSpend(
                eve_coin,
                eve_cat_puzzle,
                Program.to(  # solve_cat
                    [
                        None,
                        optional_lineage_proof,
                        eve_coin.name(),
                        coin_as_list(eve_coin),
                        eve_proof.to_program(),
                        0,
                        0,
                    ]
                ),
            ),
            CRCAT(
                Coin(eve_coin.name(), new_cat_puzhash, payment.amount),
                tail_hash,
                eve_proof,
                authorized_providers,
                proofs_checker,
                payment.puzzle_hash,
            ),
        )

    def construct_puzzle(self, inner_puzzle: Program) -> Program:
        return construct_cat_puzzle(
            CAT_MOD,
            self.tail_hash,
            self.construct_cr_layer(inner_puzzle),
        )

    def construct_cr_layer(self, inner_puzzle: Program) -> Program:
        return construct_cr_layer(
            self.authorized_providers,
            self.proofs_checker,
            inner_puzzle,
        )

    @staticmethod
    def is_cr_cat(puzzle_reveal: UncurriedPuzzle) -> Tuple[bool, str]:
        """
        This takes an (uncurried) puzzle reveal and returns a boolean for whether the puzzle is a CR-CAT and an error
        message for if the puzzle is a mismatch.
        """
        if puzzle_reveal.mod != CAT_MOD:
            return False, "top most layer is not a CAT"  # pragma: no cover
        layer_below_cat: UncurriedPuzzle = uncurry_puzzle(puzzle_reveal.args.at("rrf"))
        if layer_below_cat.mod != CREDENTIAL_RESTRICTION:
            return False, "CAT is not credential restricted"  # pragma: no cover

        # Coverage coming with CR-CAT Wallet
        return True, ""  # pragma: no cover

    # Coverage coming with CR-CAT Wallet
    @staticmethod
    def get_inner_puzzle(puzzle_reveal: UncurriedPuzzle) -> Program:  # pragma: no cover
        return uncurry_puzzle(puzzle_reveal.args.at("rrf")).args.at("rf")

    @staticmethod
    def get_inner_solution(solution: Program) -> Program:  # pragma: no cover
        return solution.at("f").at("rrrrrrf")

    @classmethod
    def get_current_from_coin_spend(cls: Type[_T_CRCAT], spend: CoinSpend) -> CRCAT:  # pragma: no cover
        uncurried_puzzle: UncurriedPuzzle = uncurry_puzzle(spend.puzzle_reveal.to_program())
        first_uncurried_cr_layer: UncurriedPuzzle = uncurry_puzzle(uncurried_puzzle.args.at("rrf"))
        second_uncurried_cr_layer: UncurriedPuzzle = uncurry_puzzle(first_uncurried_cr_layer.mod)
        return CRCAT(
            spend.coin,
            bytes32(uncurried_puzzle.args.at("rf").atom),
            spend.solution.to_program().at("rf"),
            [bytes32(ap.atom) for ap in second_uncurried_cr_layer.args.at("rf").as_iter()],
            second_uncurried_cr_layer.args.at("rrf"),
            first_uncurried_cr_layer.args.at("f").get_tree_hash(),
        )

    @classmethod
    def get_next_from_coin_spend(
        cls: Type[_T_CRCAT],
        parent_spend: CoinSpend,
        conditions: Optional[Program] = None,  # For optimization purposes, the conditions may already have been run
    ) -> List[CRCAT]:
        """
        Given a coin spend, this will return the next CR-CATs that were created as an output of that spend.
        Inner puzzle output conditions may also be supplied as an optimization.

        This is the main method to use when syncing. It can also sync from a CAT spend that was not a CR-CAT so long
        as the spend output a remark condition that was (REMARK authorized_providers proofs_checker)
        """
        coin_name: bytes32 = parent_spend.coin.name()
        puzzle: Program = parent_spend.puzzle_reveal.to_program()
        solution: Program = parent_spend.solution.to_program()

        # Get info by uncurrying
        _, tail_hash_as_prog, potential_cr_layer = puzzle.uncurry()[1].as_iter()
        new_inner_puzzle_hash: Optional[bytes32] = None
        if potential_cr_layer.uncurry()[0].uncurry()[0] != CREDENTIAL_RESTRICTION:
            # If the previous spend is not a CR-CAT:
            # we look for a remark condition that tells us the authorized_providers and proofs_checker
            inner_solution: Program = solution.at("f")
            if conditions is None:
                conditions = potential_cr_layer.run(inner_solution)
            for condition in conditions.as_iter():
                if condition.at("f") == Program.to(1):
                    new_inner_puzzle_hash = bytes32(condition.at("rf").atom)
                    authorized_providers_as_prog: Program = condition.at("rrf")
                    proofs_checker: Program = condition.at("rrrf")
                    break
            else:
                raise ValueError(
                    "Previous spend was not a CR-CAT, nor did it properly remark the CR params"
                )  # pragma: no cover
            lineage_inner_puzhash: bytes32 = potential_cr_layer.get_tree_hash()
        else:
            # Otherwise the info we need will be in the puzzle reveal
            cr_first_curry, self_hash_and_innerpuz = potential_cr_layer.uncurry()
            _, authorized_providers_as_prog, proofs_checker = cr_first_curry.uncurry()[1].as_iter()
            _, inner_puzzle = self_hash_and_innerpuz.as_iter()
            inner_solution = solution.at("f").at("rrrrrrf")
            if conditions is None:
                conditions = inner_puzzle.run(inner_solution)
            inner_puzzle_hash: bytes32 = inner_puzzle.get_tree_hash()
            lineage_inner_puzhash = construct_cr_layer(
                authorized_providers_as_prog,
                proofs_checker,
                inner_puzzle_hash,  # type: ignore
            ).get_tree_hash_precalc(inner_puzzle_hash)

        # Convert all of the old stuff into python
        authorized_providers: List[bytes32] = [bytes32(p.atom) for p in authorized_providers_as_prog.as_iter()]
        new_lineage_proof: LineageProof = LineageProof(
            parent_spend.coin.parent_coin_info,
            lineage_inner_puzhash,
            uint64(parent_spend.coin.amount),
        )

        # Almost complete except the coin's full puzzle hash which we want to use the class method to calculate
        partially_completed_crcats: List[CRCAT] = [
            CRCAT(
                Coin(coin_name, bytes(32), uint64(condition.at("rrf").as_int())),
                bytes32(tail_hash_as_prog.atom),
                new_lineage_proof,
                authorized_providers,
                proofs_checker,
                bytes32(condition.at("rf").atom) if new_inner_puzzle_hash is None else new_inner_puzzle_hash,
            )
            for condition in conditions.as_iter()
            if condition.at("f").as_int() == 51 and condition.at("rrf") != Program.to(-113)
        ]

        return [
            replace(
                crcat,
                coin=Coin(
                    crcat.coin.parent_coin_info,
                    crcat.construct_puzzle(crcat.inner_puzzle_hash).get_tree_hash_precalc(  # type: ignore
                        crcat.inner_puzzle_hash
                    ),
                    crcat.coin.amount,
                ),
            )
            for crcat in partially_completed_crcats
        ]

    def do_spend(
        self,
        # CAT solving info
        previous_coin_id: bytes32,
        next_coin_proof: LineageProof,
        previous_subtotal: int,
        extra_delta: int,
        # CR layer solving info
        proof_of_inclusions: Program,
        proof_checker_solution: Program,
        provider_id: bytes32,
        vc_launcher_id: bytes32,
        vc_inner_puzhash: bytes32,
        # Inner puzzle and solution
        inner_puzzle: Program,
        inner_solution: Program,
        # For optimization purposes the conditions may already have been run
        conditions: Optional[Iterable[Program]] = None,
    ) -> Tuple[List[bytes32], CoinSpend, List["CRCAT"]]:
        """
        Spend a CR-CAT.

        Must give the CAT accounting information, the valid VC proof, and the inner puzzle and solution.  The function
        will return the announcement IDs for the VC to optionally assert, the spend of this CAT, and the class
        representations of any CR-CAT outputs.

        Likely, spend_many is more useful.
        """
        # Gather the output information
        announcement_ids: List[bytes32] = []
        new_inner_puzzle_hashes_and_amounts: List[Tuple[bytes32, uint64]] = []
        if conditions is None:
            conditions = inner_puzzle.run(inner_solution).as_iter()  # pragma: no cover
        assert conditions is not None
        for condition in conditions:
            if condition.at("f").as_int() == 51 and condition.at("rrf").as_int() != -113:
                new_inner_puzzle_hash: bytes32 = bytes32(condition.at("rf").atom)
                new_amount: uint64 = uint64(condition.at("rrf").as_int())
                announcement_ids.append(
                    std_hash(self.coin.name() + b"\xcd" + std_hash(new_inner_puzzle_hash + int_to_bytes(new_amount)))
                )
                new_inner_puzzle_hashes_and_amounts.append((new_inner_puzzle_hash, new_amount))

        return (
            announcement_ids,
            CoinSpend(
                self.coin,
                self.construct_puzzle(inner_puzzle),
                Program.to(  # solve_cat
                    [
                        solve_cr_layer(
                            proof_of_inclusions,
                            proof_checker_solution,
                            provider_id,
                            vc_launcher_id,
                            vc_inner_puzhash,
                            self.coin.name(),
                            inner_solution,
                        ),
                        self.lineage_proof.to_program(),
                        previous_coin_id,
                        coin_as_list(self.coin),
                        next_coin_proof.to_program(),
                        previous_subtotal,
                        extra_delta,
                    ]
                ),
            ),
            [
                CRCAT(
                    Coin(
                        self.coin.name(),
                        self.construct_puzzle(new_inner_puzzle_hash).get_tree_hash_precalc(  # type: ignore
                            new_inner_puzzle_hash
                        ),
                        new_amount,
                    ),
                    self.tail_hash,
                    LineageProof(
                        self.coin.parent_coin_info,
                        self.construct_cr_layer(self.inner_puzzle_hash).get_tree_hash_precalc(  # type: ignore
                            self.inner_puzzle_hash
                        ),
                        uint64(self.coin.amount),
                    ),
                    self.authorized_providers,
                    self.proofs_checker,
                    new_inner_puzzle_hash,
                )
                for new_inner_puzzle_hash, new_amount in new_inner_puzzle_hashes_and_amounts
            ],
        )

    @classmethod
    def spend_many(
        cls: Type[_T_CRCAT],
        inner_spends: List[Tuple[_T_CRCAT, Program, Program]],  # CRCAT, inner puzzle, inner solution
        # CR layer solving info
        proof_of_inclusions: Program,
        proof_checker_solution: Program,
        provider_id: bytes32,
        vc_launcher_id: bytes32,
        vc_inner_puzhash: bytes32,
    ) -> Tuple[List[bytes32], List[CoinSpend], List[CRCAT]]:
        """
        Spend a multiple CR-CATs.

        This class will handle all of the CAT accounting information, the only necessary information is the inner
        puzzle/solution, and the proof of a valid VC being spent along side all of the coins. There is currently no
        support for multiple VCs being used across the spend.  There is also currently no support for minting/melting.
        """

        def next_index(index: int) -> int:
            return 0 if index == len(inner_spends) - 1 else index + 1

        def prev_index(index: int) -> int:
            return index - 1

        sorted_inner_spends: List[Tuple[_T_CRCAT, Program, Program]] = sorted(
            inner_spends,
            key=lambda spend: spend[0].coin.name(),
        )

        all_expected_announcements: List[bytes32] = []
        all_coin_spends: List[CoinSpend] = []
        all_new_crcats: List[CRCAT] = []

        subtotal: int = 0
        for i, inner_spend in enumerate(sorted_inner_spends):
            crcat, inner_puzzle, inner_solution = inner_spend
            conditions: List[Program] = list(inner_puzzle.run(inner_solution).as_iter())
            output_amount: uint64 = uint64(
                sum(
                    c.at("rrf").as_int()
                    for c in conditions
                    if c.at("f").as_int() == 51 and c.at("rrf").as_int() != -113
                )
            )
            next_crcat, _, _ = sorted_inner_spends[next_index(i)]
            prev_crcat, _, _ = sorted_inner_spends[prev_index(i)]
            expected_announcements, coin_spend, new_crcats = crcat.do_spend(
                prev_crcat.coin.name(),
                LineageProof(
                    next_crcat.coin.parent_coin_info,
                    next_crcat.construct_cr_layer(
                        next_crcat.inner_puzzle_hash,  # type: ignore
                    ).get_tree_hash_precalc(next_crcat.inner_puzzle_hash),
                    uint64(next_crcat.coin.amount),
                ),
                subtotal,
                0,  # TODO: add support for mint/melt
                proof_of_inclusions,
                proof_checker_solution,
                provider_id,
                vc_launcher_id,
                vc_inner_puzhash,
                inner_puzzle,
                inner_solution,
                conditions=conditions,
            )
            all_expected_announcements.extend(expected_announcements)
            all_coin_spends.append(coin_spend)
            all_new_crcats.extend(new_crcats)

            subtotal = subtotal + crcat.coin.amount - output_amount

        return all_expected_announcements, all_coin_spends, all_new_crcats

    def expected_announcement(self) -> bytes32:
        """
        The announcement a VC must make to this CAT in order to spend it
        """
        return std_hash(self.coin.name() + b"\xca")


@dataclass(frozen=True)
class CRCATSpend:
    crcat: CRCAT
    inner_puzzle: Program
    inner_solution: Program
    children: List[CRCAT]
    provider_specified: bool
    inner_conditions: List[Program]

    # Coverage coming with CR-CAT wallet
    @classmethod
    def from_coin_spend(cls, spend: CoinSpend) -> CRCATSpend:  # pragma: no cover
        inner_puzzle: Program = CRCAT.get_inner_puzzle(uncurry_puzzle(spend.puzzle_reveal.to_program()))
        inner_solution: Program = CRCAT.get_inner_solution(spend.solution.to_program())
        inner_conditions: Program = inner_puzzle.run(inner_solution)
        return cls(
            CRCAT.get_current_from_coin_spend(spend),
            inner_puzzle,
            inner_solution,
            CRCAT.get_next_from_coin_spend(spend, conditions=inner_conditions),
            spend.solution.to_program().at("f").at("rrrrf") == Program.to(None),
            list(inner_conditions.as_iter()),
        )


@dataclass(frozen=True)
class ProofsChecker:
    flags: List[str]

    def as_program(self) -> Program:
        def byte_sort_flags(f1: str, f2: str) -> int:
            return 1 if Program.to([10, (1, f1), (1, f2)]).run([]) == Program.to(None) else -1

        return PROOF_FLAGS_CHECKER.curry(
            [
                Program.to((flag, 1))
                for flag in sorted(
                    self.flags,
                    key=functools.cmp_to_key(byte_sort_flags),
                )
            ]
        )
