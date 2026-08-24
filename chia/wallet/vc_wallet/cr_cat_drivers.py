from __future__ import annotations

import functools
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import IntEnum
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar, cast

from chia_puzzles_py.programs import (
    CONDITIONS_W_FEE_ANNOUNCE,
    FLAG_PROOFS_CHECKER,
)
from chia_puzzles_py.programs import (
    CREDENTIAL_RESTRICTION as CREDENTIAL_RESTRICTION_BYTES,
)
from chia_puzzles_py.programs import (
    CREDENTIAL_RESTRICTION_HASH as CREDENTIAL_RESTRICTION_HASH_BYTES,
)
from chia_rs import CoinSpend
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint64
from typing_extensions import Self

from chia.types.blockchain_format.coin import Coin, coin_as_list
from chia.types.blockchain_format.program import Program
from chia.types.coin_spend import make_spend
from chia.util.casts import int_to_bytes
from chia.util.hash import std_hash
from chia.util.streamable import Streamable, streamable
from chia.wallet.cat_wallet.cat_utils import CATCorePuzzles, CATPuzzle, TAILCondition
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    Condition,
    CreateCoin,
    CreateCoinAnnouncement,
    Remark,
    parse_conditions_non_consensus,
)
from chia.wallet.lineage_proof import LineageProof, LineageProofField
from chia.wallet.puzzles.puzzle_drivers import (
    ACSSolution,
    InnerPuzzle,
    OuterPuzzle,
    P2Conditions,
    PuzzleWithPuzzleHash,
    Solution,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD_HASH,
)
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle
from chia.wallet.util.curry_and_treehash import curry_and_treehash
from chia.wallet.vc_wallet.vc_drivers import (
    COVENANT_LAYER_HASH,
    EML_TP_COVENANT_ADAPTER_HASH,
    EXTIGENT_METADATA_LAYER_HASH,
    GUARANTEED_NIL_TP_HASH,
    P2_ANNOUNCED_DELEGATED_PUZZLE_HASH,
    create_did_tp,
    create_eml_covenant_morpher,
)

# Mods

CREDENTIAL_RESTRICTION: Program = Program.from_bytes(CREDENTIAL_RESTRICTION_BYTES)
CREDENTIAL_RESTRICTION_HASH: bytes32 = bytes32(CREDENTIAL_RESTRICTION_HASH_BYTES)
HASH_OF_QUOTED_MOD_HASH = Program.to((1, CREDENTIAL_RESTRICTION_HASH)).get_tree_hash_precalc(
    CREDENTIAL_RESTRICTION_HASH
)
PROOF_FLAGS_CHECKER: Program = Program.from_bytes(FLAG_PROOFS_CHECKER)
PENDING_VC_ANNOUNCEMENT: Program = Program.from_bytes(CONDITIONS_W_FEE_ANNOUNCE)
CREDENTIAL_STRUCT: Program = Program.to(
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
            curry_and_treehash(
                Program.to((1, EXTIGENT_METADATA_LAYER_HASH)).get_tree_hash_precalc(EXTIGENT_METADATA_LAYER_HASH),
                Program.to(EXTIGENT_METADATA_LAYER_HASH).get_tree_hash(),
                Program.NIL.get_tree_hash(),
                GUARANTEED_NIL_TP_HASH,
                Program.to(GUARANTEED_NIL_TP_HASH).get_tree_hash(),
                P2_ANNOUNCED_DELEGATED_PUZZLE_HASH,
            ),
            (
                Program.to(
                    int_to_bytes(2) + Program.to((1, COVENANT_LAYER_HASH)).get_tree_hash_precalc(COVENANT_LAYER_HASH)
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
)
CREDENTIAL_STRUCT_HASH: bytes32 = CREDENTIAL_STRUCT.get_tree_hash()


@streamable
@dataclass(frozen=True)
class ProofsChecker(PuzzleWithPuzzleHash, Streamable):
    if TYPE_CHECKING:
        _inner_puzzle_protocol_check: ClassVar[InnerPuzzle] = cast("ProofsChecker", None)

    flags: list[str]

    @property
    def puzzle(self) -> Program:
        def byte_sort_flags(f1: str, f2: str) -> int:
            return 1 if Program.to([10, (1, f1), (1, f2)]).run([]) == Program.NIL else -1

        return PROOF_FLAGS_CHECKER.curry(
            [
                Program.to((flag, "1"))
                for flag in sorted(
                    self.flags,
                    key=functools.cmp_to_key(byte_sort_flags),
                )
            ]
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> ProofsChecker | None:
        if unknown_puzzle.mod != PROOF_FLAGS_CHECKER or unknown_puzzle.curried_args is None:
            return None

        (flags,) = unknown_puzzle.curried_args

        return ProofsChecker([flag.at("f").as_atom().decode("utf8") for flag in flags.as_iter()])


_T_InnerPuzzle = TypeVar("_T_InnerPuzzle", bound=InnerPuzzle)


@dataclass(frozen=True, kw_only=True)
class CredentialRestrictionLayer(PuzzleWithPuzzleHash, Generic[_T_InnerPuzzle]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast(
            "CredentialRestrictionLayer[_T_InnerPuzzle]", None
        )

    authorized_providers: list[bytes32]
    proofs_checker: ProofsChecker
    inner_puzzle: _T_InnerPuzzle

    @property
    def puzzle(self) -> Program:
        first_curry = CREDENTIAL_RESTRICTION.curry(
            CREDENTIAL_STRUCT,
            self.authorized_providers,
            self.proofs_checker.puzzle,
        )
        return first_curry.curry(first_curry.get_tree_hash(), self.inner_puzzle.puzzle)

    @functools.cached_property
    def authorized_providers_hash(self) -> bytes32:
        return Program.to(self.authorized_providers).get_tree_hash()

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        first_curry_hash = curry_and_treehash(
            HASH_OF_QUOTED_MOD_HASH,
            CREDENTIAL_STRUCT_HASH,
            self.authorized_providers_hash,
            self.proofs_checker.puzzle_hash,
        )
        first_curry_hash_hash = Program.to(first_curry_hash).get_tree_hash()
        final_hash = curry_and_treehash(
            Program.to((1, first_curry_hash)).get_tree_hash_precalc(first_curry_hash),
            first_curry_hash_hash,
            self.inner_puzzle.puzzle_hash,
        )
        return final_hash

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> CredentialRestrictionLayer[UnknownPuzzle] | None:
        extra_uncurried_puzzle = UnknownPuzzle(known_puzzle=unknown_puzzle.mod)
        if (
            extra_uncurried_puzzle.mod != CREDENTIAL_RESTRICTION
            or extra_uncurried_puzzle.curried_args is None
            or unknown_puzzle.curried_args is None
        ):
            return None

        (_, authorized_providers_prog, proofs_checker_prog) = extra_uncurried_puzzle.curried_args
        (_, inner_puzzle_prog) = unknown_puzzle.curried_args

        matched_proofs_checker = ProofsChecker.match(unknown_puzzle=UnknownPuzzle(known_puzzle=proofs_checker_prog))
        if matched_proofs_checker is None:
            return None

        return CredentialRestrictionLayer(
            authorized_providers=[bytes32(provider.as_atom()) for provider in authorized_providers_prog.as_iter()],
            proofs_checker=matched_proofs_checker,
            inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle_prog),
        )


_T_InnerSolution = TypeVar("_T_InnerSolution", bound=Solution)
_T_ProofCheckerSolution = TypeVar("_T_ProofCheckerSolution", bound=Solution)


@dataclass(frozen=True, kw_only=True)
class CredentialRestrictionLayerSolution(Generic[_T_InnerSolution, _T_ProofCheckerSolution]):
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast(
            "CredentialRestrictionLayerSolution[_T_InnerSolution, _T_ProofCheckerSolution]", None
        )

    proof_of_inclusions: Program
    proof_checker_solution: _T_ProofCheckerSolution
    provider_id: bytes32 | None
    vc_launcher_id: bytes32 | None
    vc_inner_puzhash: bytes32 | None
    my_coin_id: bytes32 | None
    inner_solution: _T_InnerSolution

    def as_program(self) -> Program:
        return Program.to(
            [
                self.proof_of_inclusions,
                self.proof_checker_solution.as_program(),
                self.provider_id,
                self.vc_launcher_id,
                self.vc_inner_puzhash,
                self.my_coin_id,
                self.inner_solution.as_program(),
            ]
        )

    @classmethod
    def match(
        cls, unknown_solution: UnknownSolution
    ) -> CredentialRestrictionLayerSolution[UnknownSolution, UnknownSolution] | None:
        list_of_args = list(unknown_solution.as_program().as_iter())
        if len(list_of_args) != 7:
            return None
        (
            proof_of_inclusions,
            proof_checker_solution,
            provider_id,
            vc_launcher_id,
            vc_inner_puzhash,
            my_coin_id,
            inner_solution,
        ) = list_of_args
        return CredentialRestrictionLayerSolution(
            proof_of_inclusions=proof_of_inclusions,
            proof_checker_solution=UnknownSolution(solution=proof_checker_solution),
            provider_id=bytes32(provider_id.as_atom()),
            vc_launcher_id=bytes32(vc_launcher_id.as_atom()) if vc_launcher_id != Program.NIL else None,
            vc_inner_puzhash=bytes32(vc_inner_puzhash.as_atom()) if vc_inner_puzhash != Program.NIL else None,
            my_coin_id=bytes32(my_coin_id.as_atom()) if my_coin_id != Program.NIL else None,
            inner_solution=UnknownSolution(solution=inner_solution),
        )


@dataclass(frozen=True)
class PendingApprovalPuzzle(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _inner_puzzle_protocol_check: ClassVar[InnerPuzzle] = cast("PendingApprovalPuzzle", None)

    target_puzzle_hash: bytes32
    amount: uint64

    @property
    def puzzle(self) -> Program:
        return PENDING_VC_ANNOUNCEMENT.curry(
            ACSSolution(
                conditions=[
                    CreateCoin(amount=self.amount, puzzle_hash=self.target_puzzle_hash, memos=[self.target_puzzle_hash])
                ]
            ).as_program()
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> PendingApprovalPuzzle | None:
        if unknown_puzzle.mod != PENDING_VC_ANNOUNCEMENT or unknown_puzzle.curried_args is None:
            return None

        (acs_soltution_prog,) = unknown_puzzle.curried_args
        acs_solution_match = ACSSolution.match(unknown_solution=UnknownSolution(solution=acs_soltution_prog))
        if acs_solution_match is None or len(acs_solution_match.conditions) != 1:
            return None

        (create_coin,) = acs_solution_match.conditions
        if not isinstance(create_coin, CreateCoin):
            return None
        return PendingApprovalPuzzle(target_puzzle_hash=create_coin.puzzle_hash, amount=create_coin.amount)


@dataclass(frozen=True, kw_only=True)
class CRCAT(
    CATPuzzle[CredentialRestrictionLayer[_T_InnerPuzzle]],
    Generic[_T_InnerPuzzle],
):
    coin: Coin
    lineage_proof: LineageProof

    @classmethod
    def launch(
        cls,
        # General CAT launching info
        origin_coin: Coin,
        payment: CreateCoin,
        tail: InnerPuzzle,
        tail_solution: Solution,
        # CR Layer params
        authorized_providers: list[bytes32],
        proofs_checker: ProofsChecker,
        # Probably never need this but some tail might
        optional_lineage_proof: LineageProof | None = None,
    ) -> tuple[list[Condition], CoinSpend, CRCAT[UnknownPuzzle]]:
        """
        Launch a new CR-CAT from XCH.

        Returns a delegated puzzle to run that creates the eve CAT, an eve coin spend of the CAT, and the expected class
        representation after all relevant coin spends have been confirmed on chain.
        """
        new_cr_layer = CredentialRestrictionLayer(
            authorized_providers=authorized_providers,
            proofs_checker=proofs_checker,
            inner_puzzle=UnknownPuzzle(known_puzzle_hash=payment.puzzle_hash),
        )

        new_cat_puzzle = CATPuzzle(
            tail_hash=tail.puzzle_hash,
            inner_puzzle=new_cr_layer,
        )
        eve_innerpuz = P2Conditions(
            conditions=[
                replace(payment, puzzle_hash=new_cr_layer.puzzle_hash),
                TAILCondition(puzzle=tail, solution=tail_solution),
                CreateCoinAnnouncement(msg=b""),
                Remark(rest=Program.to([payment.puzzle_hash, authorized_providers, proofs_checker.puzzle])),
            ]
        )
        eve_cat_puzzle = CATPuzzle(
            tail_hash=tail.puzzle_hash,
            inner_puzzle=eve_innerpuz,
        )

        eve_coin: Coin = Coin(origin_coin.name(), eve_cat_puzzle.puzzle_hash, payment.amount)
        necessary_conditions = [
            CreateCoin(puzzle_hash=eve_cat_puzzle.puzzle_hash, amount=payment.amount),
            AssertCoinAnnouncement(asserted_msg=b"", asserted_id=eve_coin.name()),
        ]

        eve_proof: LineageProof = LineageProof(
            eve_coin.parent_coin_info,
            eve_innerpuz.puzzle_hash,
            uint64(eve_coin.amount),
        )

        return (
            necessary_conditions,
            make_spend(
                eve_coin,
                eve_cat_puzzle.puzzle,
                # TODO: implement a CATSolution type
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
                coin=Coin(eve_coin.name(), new_cat_puzzle.puzzle_hash, payment.amount),
                tail_hash=tail.puzzle_hash,
                lineage_proof=eve_proof,
                inner_puzzle=new_cr_layer,
            ),
        )

    @staticmethod
    def is_cr_cat(puzzle_reveal: UncurriedPuzzle) -> tuple[bool, str]:
        """
        This takes an (uncurried) puzzle reveal and returns a boolean for whether the puzzle is a CR-CAT and an error
        message for if the puzzle is a mismatch.
        """
        if puzzle_reveal.mod != CATCorePuzzles().cat_mod:
            return False, "top most layer is not a CAT"
        layer_below_cat: UncurriedPuzzle = uncurry_puzzle(uncurry_puzzle(puzzle_reveal.args.at("rrf")).mod)
        if layer_below_cat.mod != CREDENTIAL_RESTRICTION:
            return False, "CAT is not credential restricted"

        return True, ""

    @classmethod
    def get_current_from_coin_spend(cls, spend: CoinSpend) -> CRCAT[UnknownPuzzle]:
        cat_puzzle = CATPuzzle.match(
            unknown_puzzle=UnknownPuzzle(known_puzzle=Program.from_serialized(spend.puzzle_reveal))
        )
        if cat_puzzle is None:
            raise ValueError("Spend did not contain a CAT puzzle")
        cr_layer = CredentialRestrictionLayer.match(unknown_puzzle=cat_puzzle.inner_puzzle)
        if cr_layer is None:
            raise ValueError("CAT puzzle did not contain a credential restriction layer")
        lineage_proof = LineageProof.from_program(
            Program.from_serialized(spend.solution).at("rf"),
            [LineageProofField.PARENT_NAME, LineageProofField.INNER_PUZZLE_HASH, LineageProofField.AMOUNT],
        )
        return CRCAT(
            coin=spend.coin, tail_hash=cat_puzzle.tail_hash, lineage_proof=lineage_proof, inner_puzzle=cr_layer
        )

    @classmethod
    def get_next_from_coin_spend(
        cls,
        parent_spend: CoinSpend,
        conditions: Program | None = None,  # For optimization purposes, the conditions may already have been run
    ) -> list[CRCAT[UnknownPuzzle]]:
        """
        Given a coin spend, this will return the next CR-CATs that were created as an output of that spend.
        Inner puzzle output conditions may also be supplied as an optimization.

        This is the main method to use when syncing. It can also sync from a CAT spend that was not a CR-CAT so long
        as the spend output a remark condition that was (REMARK authorized_providers proofs_checker)
        """
        coin_name: bytes32 = parent_spend.coin.name()
        puzzle = Program.from_serialized(parent_spend.puzzle_reveal)
        solution = Program.from_serialized(parent_spend.solution)

        # Get info by uncurrying
        _, tail_hash_as_prog, potential_cr_layer = puzzle.uncurry()[1].as_iter()
        new_inner_puzzle = None
        if potential_cr_layer.uncurry()[0].uncurry()[0] != CREDENTIAL_RESTRICTION:
            # If the previous spend is not a CR-CAT:
            # we look for a remark condition that tells us the authorized_providers and proofs_checker
            inner_solution: Program = solution.at("f")
            if conditions is None:
                conditions = potential_cr_layer.run(inner_solution)
            for condition in conditions.as_iter():
                if condition.at("f") == Program.to(1):
                    new_inner_puzzle = UnknownPuzzle(known_puzzle_hash=bytes32(condition.at("rf").as_atom()))
                    authorized_providers_as_prog: Program = condition.at("rrf")
                    proofs_checker_match = ProofsChecker.match(
                        unknown_puzzle=UnknownPuzzle(known_puzzle=condition.at("rrrf"))
                    )
                    if proofs_checker_match is None:
                        raise ValueError("Unknown proofs checker in next CRCAT")
                    break
            else:
                raise ValueError(
                    "Previous spend was not a CR-CAT, nor did it properly remark the CR params"
                )  # pragma: no cover
            authorized_providers = [bytes32(p.as_atom()) for p in authorized_providers_as_prog.as_iter()]
            lineage_inner_puzhash: bytes32 = potential_cr_layer.get_tree_hash()
        else:
            # Otherwise the info we need will be in the puzzle reveal
            cr_first_curry, self_hash_and_innerpuz = potential_cr_layer.uncurry()
            _, authorized_providers_as_prog, proofs_checker = cr_first_curry.uncurry()[1].as_iter()
            _, inner_puzzle = self_hash_and_innerpuz.as_iter()
            inner_solution = solution.at("f").at("rrrrrrf")
            if conditions is None:
                conditions = inner_puzzle.run(inner_solution)
            authorized_providers = [bytes32(p.as_atom()) for p in authorized_providers_as_prog.as_iter()]
            proofs_checker_match = ProofsChecker.match(unknown_puzzle=UnknownPuzzle(known_puzzle=proofs_checker))
            if proofs_checker_match is None:
                raise ValueError("Unknown proofs checker in next CRCAT")
            lineage_inner_puzzle = UnknownPuzzle(known_puzzle=inner_puzzle)
            lineage_inner_puzhash = CredentialRestrictionLayer(
                authorized_providers=authorized_providers,
                proofs_checker=proofs_checker_match,
                inner_puzzle=lineage_inner_puzzle,
            ).puzzle_hash

        # Convert all of the old stuff into python
        new_lineage_proof: LineageProof = LineageProof(
            parent_spend.coin.parent_coin_info,
            lineage_inner_puzhash,
            uint64(parent_spend.coin.amount),
        )

        all_conditions: list[Condition] = parse_conditions_non_consensus(conditions.as_iter())
        if len(all_conditions) > 1000:
            raise RuntimeError("More than 1000 conditions not currently supported by CRCAT drivers")  # pragma: no cover

        next_cr_cats: list[CRCAT[UnknownPuzzle]] = []
        for cond in all_conditions:
            if not isinstance(cond, CreateCoin):
                continue

            cr_layer = CredentialRestrictionLayer(
                authorized_providers=authorized_providers,
                proofs_checker=proofs_checker_match,
                inner_puzzle=new_inner_puzzle
                if new_inner_puzzle is not None
                else UnknownPuzzle(known_puzzle_hash=cond.puzzle_hash),
            )
            cat_puzzle = CATPuzzle(
                tail_hash=bytes32(tail_hash_as_prog.as_atom()),
                inner_puzzle=cr_layer,
            )
            next_cr_cats.append(
                CRCAT(
                    coin=Coin(coin_name, cat_puzzle.puzzle_hash, cond.amount),
                    lineage_proof=new_lineage_proof,
                    tail_hash=cat_puzzle.tail_hash,
                    inner_puzzle=cr_layer,
                )
            )

        return next_cr_cats

    def do_spend(
        self,
        # CAT solving info
        previous_coin_id: bytes32,
        next_coin_proof: LineageProof,
        previous_subtotal: int,
        extra_delta: int,
        # CR layer solving info
        proof_of_inclusions: Program,
        proof_checker_solution: Solution,
        provider_id: bytes32,
        vc_launcher_id: bytes32,
        vc_inner_puzhash: bytes32 | None,  # Optional for incomplete spends
        # Inner puzzle and solution
        inner_solution: Solution,
        # For optimization purposes the conditions may already have been run
        conditions: Iterable[Program] | None = None,
    ) -> tuple[list[AssertCoinAnnouncement], CoinSpend, list[CRCAT[UnknownPuzzle]]]:
        """
        Spend a CR-CAT.

        Must give the CAT accounting information, the valid VC proof, and the inner puzzle and solution.  The function
        will return the announcement IDs for the VC to optionally assert, the spend of this CAT, and the class
        representations of any CR-CAT outputs.

        Likely, spend_many is more useful.
        """
        # Gather the output information
        announcements: list[AssertCoinAnnouncement] = []
        new_inner_puzzle_hashes_and_amounts: list[tuple[bytes32, uint64]] = []
        if conditions is None:
            conditions = self.inner_puzzle.inner_puzzle.puzzle.run(
                inner_solution.as_program()
            ).as_iter()  # pragma: no cover
        assert conditions is not None
        for condition in conditions:
            if condition.at("f").as_int() == 51 and condition.at("rrf").as_int() != -113:
                new_inner_puzzle_hash: bytes32 = bytes32(condition.at("rf").as_atom())
                new_amount: uint64 = uint64(condition.at("rrf").as_int())
                announcements.append(
                    AssertCoinAnnouncement(
                        asserted_id=self.coin.name(),
                        asserted_msg=b"\xcd" + std_hash(new_inner_puzzle_hash + int_to_bytes(new_amount)),
                    )
                )
                new_inner_puzzle_hashes_and_amounts.append((new_inner_puzzle_hash, new_amount))

        return (
            announcements,
            make_spend(
                self.coin,
                self.puzzle,
                Program.to(  # solve_cat
                    [
                        CredentialRestrictionLayerSolution(
                            proof_of_inclusions=proof_of_inclusions,
                            proof_checker_solution=proof_checker_solution,
                            provider_id=provider_id,
                            vc_launcher_id=vc_launcher_id,
                            vc_inner_puzhash=vc_inner_puzhash,
                            my_coin_id=self.coin.name(),
                            inner_solution=inner_solution,
                        ).as_program(),
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
                    coin=Coin(
                        self.coin.name(),
                        replace(
                            self,
                            inner_puzzle=(
                                new_cr_layer := replace(
                                    self.inner_puzzle,
                                    inner_puzzle=cast(
                                        _T_InnerPuzzle, UnknownPuzzle(known_puzzle_hash=new_inner_puzzle_hash)
                                    ),
                                )
                            ),
                        ).puzzle_hash,
                        new_amount,
                    ),
                    tail_hash=self.tail_hash,
                    lineage_proof=LineageProof(
                        self.coin.parent_coin_info,
                        self.inner_puzzle.puzzle_hash,
                        uint64(self.coin.amount),
                    ),
                    inner_puzzle=cast(CredentialRestrictionLayer[UnknownPuzzle], new_cr_layer),
                )
                for new_inner_puzzle_hash, new_amount in new_inner_puzzle_hashes_and_amounts
            ],
        )

    @classmethod
    def spend_many(
        cls,
        inner_spends: list[tuple[Self, int, Solution]],  # CRCAT, extra_delta, inner solution
        # CR layer solving info
        proof_of_inclusions: Program,
        proof_checker_solution: Solution,
        provider_id: bytes32,
        vc_launcher_id: bytes32,
        vc_inner_puzhash: bytes32 | None,  # Optional for incomplete spends
    ) -> tuple[list[AssertCoinAnnouncement], list[CoinSpend], list[CRCAT[UnknownPuzzle]]]:
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

        sorted_inner_spends: list[tuple[Self, int, Solution]] = sorted(
            inner_spends,
            key=lambda spend: spend[0].coin.name(),
        )

        all_expected_announcements: list[AssertCoinAnnouncement] = []
        all_coin_spends: list[CoinSpend] = []
        all_new_crcats: list[CRCAT[UnknownPuzzle]] = []

        subtotal: int = 0
        for i, inner_spend in enumerate(sorted_inner_spends):
            crcat, extra_delta, inner_solution = inner_spend
            conditions: list[Program] = list(
                crcat.inner_puzzle.inner_puzzle.puzzle.run(inner_solution.as_program()).as_iter()
            )
            output_amount: int = (
                sum(
                    c.at("rrf").as_int()
                    for c in conditions
                    if c.at("f").as_int() == 51 and c.at("rrf").as_int() != -113
                )
                - extra_delta
            )
            next_crcat, _, _ = sorted_inner_spends[next_index(i)]
            prev_crcat, _, _ = sorted_inner_spends[prev_index(i)]
            expected_announcements, coin_spend, new_crcats = crcat.do_spend(
                prev_crcat.coin.name(),
                LineageProof(
                    next_crcat.coin.parent_coin_info,
                    next_crcat.inner_puzzle.puzzle_hash,
                    uint64(next_crcat.coin.amount),
                ),
                subtotal,
                extra_delta,
                proof_of_inclusions,
                proof_checker_solution,
                provider_id,
                vc_launcher_id,
                vc_inner_puzhash,
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
class CRCATSpend(Generic[_T_InnerPuzzle, _T_InnerSolution]):
    crcat: CRCAT[_T_InnerPuzzle]
    inner_puzzle: _T_InnerPuzzle
    inner_solution: _T_InnerSolution
    children: list[CRCAT[UnknownPuzzle]]
    incomplete: bool
    inner_conditions: list[Program]
    proof_of_inclusions: Program

    @classmethod
    def from_coin_spend(cls, spend: CoinSpend) -> CRCATSpend[UnknownPuzzle, UnknownSolution]:
        cat_match = CATPuzzle.match(
            unknown_puzzle=UnknownPuzzle(known_puzzle=Program.from_serialized(spend.puzzle_reveal))
        )
        if cat_match is None:
            CATPuzzle.match(unknown_puzzle=UnknownPuzzle(known_puzzle=Program.from_serialized(spend.puzzle_reveal)))
            raise ValueError("Spend was not a CRCAT spend")
        cr_layer_match = CredentialRestrictionLayer.match(unknown_puzzle=cat_match.inner_puzzle)
        if cr_layer_match is None:
            raise ValueError("Spend was not a CRCAT spend")

        # TODO: implement a CATSolution type
        cr_layer_solution = Program.from_serialized(spend.solution).at("f")
        cr_solution_match = CredentialRestrictionLayerSolution.match(
            unknown_solution=UnknownSolution(solution=cr_layer_solution)
        )
        if cr_solution_match is None:
            raise ValueError("Spend was not a CRCAT spend")

        inner_conditions: Program = cr_layer_match.inner_puzzle.puzzle.run(
            cr_solution_match.inner_solution.as_program()
        )
        return CRCATSpend(
            CRCAT.get_current_from_coin_spend(spend),
            cr_layer_match.inner_puzzle,
            cr_solution_match.inner_solution,
            CRCAT.get_next_from_coin_spend(spend, conditions=inner_conditions),
            Program.from_serialized(spend.solution).at("f").at("rrrrf") == Program.NIL,
            list(inner_conditions.as_iter()),
            Program.from_serialized(spend.solution).at("f").at("f"),
        )


class CRCATVersion(IntEnum):
    V1 = uint16(1)


@streamable
@dataclass(frozen=True)
class CRCATMetadata(Streamable):
    lineage_proof: LineageProof
    inner_puzzle_hash: bytes32
