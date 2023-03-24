from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, List, Optional, Tuple, Type, TypeVar

from clvm.casts import int_to_bytes

from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.util.ints import uint64
from chia.util.hash import std_hash
from chia.wallet.cat_wallet.cat_utils import construct_cat_puzzle
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.load_clvm import load_clvm_maybe_recompile
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_MOD_HASH,
    SINGLETON_LAUNCHER_HASH,
)
from chia.wallet.nft_wallet.nft_puzzles import NFT_OWNERSHIP_LAYER_HASH
from chia.wallet.payment import Payment
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle
from chia.wallet.vc_wallet.vc_drivers import (
    NFT_TP_COVENANT_ADAPTER_HASH,
    GUARANTEED_NIL_TP,
    P2_ANNOUNCED_DELEGATED_PUZZLE,
    COVENANT_LAYER_HASH,
    create_ownership_layer_covenant_morpher,
    create_did_tp,
)


# Mods
CREDENTIAL_RESTRICTION: Program = load_clvm_maybe_recompile(
    "credential_restriction.clsp",
    package_or_requirement="chia.wallet.vc_wallet.cr_puzzles",
    include_standard_libraries=True,
)
CREDENTIAL_RESTRICTION_HASH: bytes32 = CREDENTIAL_RESTRICTION.get_tree_hash()


# Basic drivers
def construct_cr_layer(
    authorized_providers: List[bytes32],
    proofs_checker: Program,
    inner_puzzle: Program,
) -> Program:
    first_curry: Program = CREDENTIAL_RESTRICTION.curry(
        Program.to(
            [
                SINGLETON_MOD_HASH,
                SINGLETON_LAUNCHER_HASH,
                NFT_OWNERSHIP_LAYER_HASH,
                NFT_TP_COVENANT_ADAPTER_HASH,
                Program.to(NFT_OWNERSHIP_LAYER_HASH)
                .curry(
                    Program.to(NFT_OWNERSHIP_LAYER_HASH).get_tree_hash(),
                    Program.to(None),
                    GUARANTEED_NIL_TP,
                    P2_ANNOUNCED_DELEGATED_PUZZLE,
                )
                .get_tree_hash_precalc(NFT_OWNERSHIP_LAYER_HASH, Program.to(NFT_OWNERSHIP_LAYER_HASH).get_tree_hash()),
                COVENANT_LAYER_HASH,
                create_ownership_layer_covenant_morpher(
                    create_did_tp().get_tree_hash(),
                ).get_tree_hash(),
                create_did_tp().get_tree_hash(),
            ]
        ),
        authorized_providers,
        proofs_checker,
    )
    return first_curry.curry(first_curry.get_tree_hash(), inner_puzzle)


def match_cr_layer(uncurried_puzzle: UncurriedPuzzle) -> Optional[Tuple[List[bytes32], Program, Program]]:
    if uncurried_puzzle.mod == CREDENTIAL_RESTRICTION:
        return (
            [bytes32(provider.as_python()) for provider in uncurried_puzzle.args.at("rrf").as_iter()],
            uncurried_puzzle.args.at("rrrf"),
            uncurried_puzzle.args.at("rrrrf"),
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
                    [1, authorized_providers, proofs_checker],
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
            return False, "top most layer is not a CAT"
        layer_below_cat: UncurriedPuzzle = uncurry_puzzle(puzzle_reveal.args.at("rrf"))
        if layer_below_cat.mod != CREDENTIAL_RESTRICTION:
            return False, "CAT is not credential restricted"

        return True, ""

    @classmethod
    def get_next_from_coin_spend(cls: Type[_T_CRCAT], parent_spend: CoinSpend) -> List[CRCAT]:
        """
        Given a coin spend, this will return the next CR-CATs that were created as an output of that spend.

        This is the main method to use when syncing. It can also sync from a CAT spend that was not a CR-CAT so long
        as the spend output a remark condition that was (REMARK authorized_providers proofs_checker)
        """
        coin_name: bytes32 = parent_spend.coin.name()
        puzzle: Program = parent_spend.puzzle_reveal.to_program()
        solution: Program = parent_spend.solution.to_program()

        # Get info by uncurrying
        _, tail_hash_as_prog, potential_cr_layer = puzzle.uncurry()[1].as_iter()
        if puzzle.uncurry()[0] != CREDENTIAL_RESTRICTION:
            # If the previous spend is not a CR-CAT:
            # we look for a remark condition that tells us the authorized_providers and proofs_checker
            inner_solution: Program = solution.at("f")
            conditions: Program = potential_cr_layer.run(inner_solution)
            for condition in conditions.as_iter():
                if condition.at("f") == Program.to(1):
                    authorized_providers_as_prog: Program = condition.at("rf")
                    proofs_checker: Program = condition.at("rrf")
                    break
            else:
                raise ValueError("Previous spend was not a CR-CAT, nor did it properly remark the CR params")
            lineage_inner_puzhash: bytes32 = potential_cr_layer.get_tree_hash()
        else:
            # Otherwise the info we need will be in the puzzle reveal
            _, _, authorized_providers_as_prog, proofs_checker, inner_puzzle = potential_cr_layer.uncurry()[1].as_iter()
            inner_solution = solution.at("f").at("rrrrrrf")
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
                bytes32(condition.at("rf").atom),
            )
            for condition in conditions.as_iter()
            if condition.at("f").as_int() == 51
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
            conditions = inner_puzzle.run(inner_solution).as_iter()
        assert conditions is not None
        for condition in conditions:
            if condition.at("f").as_int() == 51:
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
                        self.inner_puzzle_hash,
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
            output_amount: int = sum(c.at("rrf").as_int() for c in conditions if c.at("f").as_int() == 51)
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
