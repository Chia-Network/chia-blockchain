from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import ClassVar, Protocol, TypeVar

from chia_puzzles_py import programs as puzzle_mods
from chia_rs.sized_bytes import bytes32
from typing_extensions import runtime_checkable

from chia.types.blockchain_format.program import Program
from chia.wallet.util.merkle_tree import MerkleTree, hash_a_pair, hash_an_atom

MofN_MOD = Program.from_bytes(puzzle_mods.M_OF_N)
OneOfN_MOD = Program.from_bytes(puzzle_mods.ONE_OF_N)
OneOfN_MOD_HASH = bytes32(puzzle_mods.ONE_OF_N_HASH)
NofN_MOD = Program.from_bytes(puzzle_mods.N_OF_N)
RESTRICTION_MOD = Program.from_bytes(puzzle_mods.RESTRICTIONS)
RESTRICTION_MOD_HASH = bytes32(puzzle_mods.RESTRICTIONS_HASH)
DELEGATED_PUZZLE_FEEDER = Program.from_bytes(puzzle_mods.DELEGATED_PUZZLE_FEEDER)
DELEGATED_PUZZLE_FEEDER_HASH = bytes32(puzzle_mods.DELEGATED_PUZZLE_FEEDER_HASH)
# (mod (INDEX INNER_PUZZLE . inner_solution) (a INNER_PUZZLE inner_solution))
INDEX_WRAPPER = Program.to([2, 5, 7])
INDEX_WRAPPER_HASH = INDEX_WRAPPER.get_tree_hash()


# General (inner) puzzle driver spec
class MIPSComponent(Protocol):
    def memo(self, nonce: int) -> Program: ...

    def puzzle(self, nonce: int) -> Program: ...

    def puzzle_hash(self, nonce: int) -> bytes32: ...


@dataclass(kw_only=True, frozen=True)
class MemberHint:
    puzhash: bytes32
    memo: Program

    def to_program(self) -> Program:
        return Program.to([self.puzhash, self.memo])

    @classmethod
    def from_program(cls, prog: Program) -> MemberHint:
        puzhash, memo = prog.as_iter()
        return MemberHint(
            puzhash=bytes32(puzhash.as_atom()),
            memo=memo,
        )


@dataclass(frozen=True)
class UnknownMember:
    puzzle_hint: MemberHint

    def memo(self, nonce: int) -> Program:
        return self.puzzle_hint.memo

    def puzzle(self, nonce: int) -> Program:
        raise NotImplementedError("An unknown puzzle type cannot generate a puzzle reveal")  # pragma: no cover

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle_hint.puzhash


# A spec for "restrictions" on specific inner puzzles
MemberOrDPuz = bool

_T_MemberNotDPuz_co = TypeVar("_T_MemberNotDPuz_co", bound=MemberOrDPuz, covariant=True)


@runtime_checkable
class Restriction(MIPSComponent, Protocol[_T_MemberNotDPuz_co]):
    @property
    def member_not_dpuz(self) -> _T_MemberNotDPuz_co: ...


@dataclass(kw_only=True, frozen=True)
class RestrictionHint:
    member_not_dpuz: bool
    puzhash: bytes32
    memo: Program

    def to_program(self) -> Program:
        return Program.to([self.member_not_dpuz, self.puzhash, self.memo])

    @classmethod
    def from_program(cls, prog: Program) -> RestrictionHint:
        member_not_dpuz, puzhash, memo = prog.as_iter()
        return RestrictionHint(
            member_not_dpuz=member_not_dpuz != Program.to(None),
            puzhash=bytes32(puzhash.as_atom()),
            memo=memo,
        )


@dataclass(frozen=True)
class UnknownRestriction:
    restriction_hint: RestrictionHint

    @property
    def member_not_dpuz(self) -> bool:
        return self.restriction_hint.member_not_dpuz

    def memo(self, nonce: int) -> Program:
        return self.restriction_hint.memo

    def puzzle(self, nonce: int) -> Program:
        raise NotImplementedError("An unknown restriction type cannot generate a puzzle reveal")  # pragma: no cover

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.restriction_hint.puzhash


# MofN puzzle drivers which are a fundamental component of the architecture
@dataclass(kw_only=True, frozen=True)
class ProvenSpend:
    puzzle_reveal: Program
    solution: Program


class MofNMerkleTree(MerkleTree):  # Special subclass that can generate proofs for m of n puzzles in the tree
    def _m_of_n_proof(self, puzzle_hashes: list[bytes32], spends_to_prove: dict[bytes32, ProvenSpend]) -> Program:
        if len(puzzle_hashes) == 1:  # we've reached a leaf node
            if puzzle_hashes[0] in spends_to_prove:
                spend_to_prove = spends_to_prove[puzzle_hashes[0]]
                # If it's one that we've been requested to prove, the format is (() puzzle_reveal . solution)
                return Program.to((None, (spend_to_prove.puzzle_reveal, spend_to_prove.solution)))
            else:
                return Program.to(hash_an_atom(puzzle_hashes[0]))
        else:
            first, rest = self.split_list(puzzle_hashes)
            first_proof = self._m_of_n_proof(first, spends_to_prove)
            rest_proof = self._m_of_n_proof(rest, spends_to_prove)
            if first_proof.atom is None or rest_proof.atom is None:
                # If either side has returned as a cons, part of the subtree needs to be revealed
                # so we just return the branch as is
                return Program.to((first_proof, rest_proof))
            else:
                return Program.to(hash_a_pair(bytes32(first_proof.as_atom()), bytes32(rest_proof.as_atom())))

    def generate_m_of_n_proof(self, spends_to_prove: dict[bytes32, ProvenSpend]) -> Program:
        return self._m_of_n_proof(self.nodes, spends_to_prove)


@dataclass(kw_only=True, frozen=True)
class MofNHint:
    m: int
    member_memos: list[Program]

    def to_program(self) -> Program:
        return Program.to([self.m, self.member_memos])

    @classmethod
    def from_program(cls, prog: Program) -> MofNHint:
        m, member_memos = prog.as_iter()
        return MofNHint(
            m=m.as_int(),
            member_memos=list(member_memos.as_iter()),
        )


@dataclass(kw_only=True, frozen=True)
class MofN:  # Technically matches Puzzle protocol but is a bespoke part of the architecture
    m: int
    members: list[PuzzleWithRestrictions]

    def __post_init__(self) -> None:
        if self.m > self.n:
            raise ValueError("M cannot be greater than N")
        if self.m < 1:
            raise ValueError("M must be greater than 0")
        if len(list(set(self._merkle_tree.nodes))) != len(self._merkle_tree.nodes):
            raise ValueError("Duplicate nodes not currently supported by MofN drivers")

    @property
    def n(self) -> int:
        return len(self.members)

    @property
    def _merkle_tree(self) -> MerkleTree:
        nodes = [member.puzzle_hash(_top_level=False) for member in self.members]
        if self.m > 1:
            return MofNMerkleTree(nodes)
        else:
            return MerkleTree(nodes)

    def solve(self, spends_to_prove: dict[bytes32, ProvenSpend]) -> Program:
        assert len(spends_to_prove) == self.m, "Must prove as many spends as the M value"
        if self.m == self.n:
            return Program.to([[spends_to_prove[node].solution for node in self._merkle_tree.nodes]])
        elif self.m > 1:
            return Program.to([self._merkle_tree.generate_m_of_n_proof(spends_to_prove)])  # type: ignore[attr-defined]
        else:
            only_key = next(iter(spends_to_prove.keys()))
            proven_spend = spends_to_prove[only_key]
            proof = self._merkle_tree.generate_proof(only_key)
            return Program.to([(proof[0], proof[1][0]), proven_spend.puzzle_reveal, proven_spend.solution])

    def memo(self, nonce: int) -> Program:  # pragma: no cover
        raise NotImplementedError("PuzzleWithRestrictions handles MofN memos, this method should not be called")

    def puzzle(self, nonce: int) -> Program:
        if self.m == self.n:
            return NofN_MOD.curry([member.puzzle_reveal(_top_level=False) for member in self.members])
        elif self.m > 1:
            return MofN_MOD.curry(self.m, self._merkle_tree.calculate_root())
        else:
            return OneOfN_MOD.curry(self._merkle_tree.calculate_root())

    def puzzle_hash(self, nonce: int) -> bytes32:
        if self.m == self.n:
            member_hashes = [member.puzzle_hash(_top_level=False) for member in self.members]
            return NofN_MOD.curry(member_hashes).get_tree_hash_precalc(*member_hashes)
        else:
            return self.puzzle(nonce).get_tree_hash()


# A convenience object for hinting the two solution values that must always exist
@dataclass(kw_only=True, frozen=True)
class DelegatedPuzzleAndSolution:
    puzzle: Program
    solution: Program


# The top-level object inside every "outer" puzzle
@dataclass(kw_only=True, frozen=True)
class PuzzleWithRestrictions:
    nonce: int  # Arbitrary nonce to make otherwise identical custody arrangements have different puzzle hashes
    restrictions: list[Restriction[MemberOrDPuz]]
    puzzle: MIPSComponent
    spec_namespace: ClassVar[str] = "inner_puzzle_chip?"

    def memo(self) -> Program:
        restriction_hints: list[RestrictionHint] = [
            RestrictionHint(
                member_not_dpuz=restriction.member_not_dpuz,
                puzhash=restriction.puzzle_hash(self.nonce),
                memo=restriction.memo(self.nonce),
            )
            for restriction in self.restrictions
        ]

        puzzle_hint: MofNHint | MemberHint
        if isinstance(self.puzzle, MofN):
            puzzle_hint = MofNHint(
                m=self.puzzle.m,
                member_memos=[member.memo() for member in self.puzzle.members],
            )
        else:
            puzzle_hint = MemberHint(
                puzhash=self.puzzle.puzzle_hash(self.nonce),
                memo=self.puzzle.memo(self.nonce),
            )

        return Program.to(
            (
                self.spec_namespace,
                [
                    self.nonce,
                    [hint.to_program() for hint in restriction_hints],
                    1 if isinstance(self.puzzle, MofN) else 0,
                    puzzle_hint.to_program(),
                ],
            )
        )

    @classmethod
    def from_memo(cls, memo: Program) -> PuzzleWithRestrictions:
        if memo.atom is not None or memo.first() != Program.to(cls.spec_namespace):
            raise ValueError("Attempting to parse a memo that does not belong to this spec")
        nonce, restriction_hints_prog, further_branching_prog, puzzle_hint_prog = memo.rest().as_iter()
        restriction_hints = [RestrictionHint.from_program(hint) for hint in restriction_hints_prog.as_iter()]
        further_branching = further_branching_prog != Program.to(None)
        if further_branching:
            m_of_n_hint = MofNHint.from_program(puzzle_hint_prog)
            puzzle: MIPSComponent = MofN(
                m=m_of_n_hint.m, members=[PuzzleWithRestrictions.from_memo(memo) for memo in m_of_n_hint.member_memos]
            )
        else:
            puzzle_hint = MemberHint.from_program(puzzle_hint_prog)
            puzzle = UnknownMember(puzzle_hint)

        return PuzzleWithRestrictions(
            nonce=nonce.as_int(),
            restrictions=[UnknownRestriction(hint) for hint in restriction_hints],
            puzzle=puzzle,
        )

    @property
    def unknown_puzzles(self) -> Mapping[bytes32, UnknownMember | UnknownRestriction]:
        unknown_restrictions = {
            ur.restriction_hint.puzhash: ur for ur in self.restrictions if isinstance(ur, UnknownRestriction)
        }

        unknown_puzzles: Mapping[bytes32, UnknownMember | UnknownRestriction]
        if isinstance(self.puzzle, UnknownMember):
            unknown_puzzles = {self.puzzle.puzzle_hint.puzhash: self.puzzle}
        elif isinstance(self.puzzle, MofN):
            unknown_puzzles = {
                uph: up
                for puz_w_restriction in self.puzzle.members
                for uph, up in puz_w_restriction.unknown_puzzles.items()
            }
        else:
            unknown_puzzles = {}
        return {
            **unknown_puzzles,
            **unknown_restrictions,
        }

    def fill_in_unknown_puzzles(self, puzzle_dict: Mapping[bytes32, MIPSComponent]) -> PuzzleWithRestrictions:
        new_restrictions: list[Restriction[MemberOrDPuz]] = []
        for restriction in self.restrictions:
            if isinstance(restriction, UnknownRestriction) and restriction.restriction_hint.puzhash in puzzle_dict:
                new = puzzle_dict[restriction.restriction_hint.puzhash]
                # using runtime_checkable here to assert isinstance(new, Restriction) results in an error in the test
                # where PlaceholderPuzzle() is used. Not sure why, so we'll ignore since it's for mypy's sake anyways
                new_restrictions.append(new)  # type: ignore[arg-type]
            else:
                new_restrictions.append(restriction)

        new_puzzle: MIPSComponent
        if (
            isinstance(self.puzzle, UnknownMember) and self.puzzle.puzzle_hint.puzhash in puzzle_dict  # pylint: disable=no-member
        ):
            new_puzzle = puzzle_dict[self.puzzle.puzzle_hint.puzhash]  # pylint: disable=no-member
        elif isinstance(self.puzzle, MofN):
            new_puzzle = replace(
                self.puzzle,
                members=[
                    puz.fill_in_unknown_puzzles(puzzle_dict)
                    for puz in self.puzzle.members  # pylint: disable=no-member
                ],
            )
        else:
            new_puzzle = self.puzzle

        return PuzzleWithRestrictions(
            nonce=self.nonce,
            restrictions=new_restrictions,
            puzzle=new_puzzle,
        )

    def puzzle_reveal(self, _top_level: bool = True) -> Program:
        inner_puzzle = self.puzzle.puzzle(self.nonce)  # pylint: disable=assignment-from-no-return

        if len(self.restrictions) > 0:  # We optimize away the restriction layer when no restrictions are present
            restricted_inner_puzzle = RESTRICTION_MOD.curry(
                [restriction.puzzle(self.nonce) for restriction in self.restrictions if restriction.member_not_dpuz],
                [
                    restriction.puzzle(self.nonce)
                    for restriction in self.restrictions
                    if not restriction.member_not_dpuz
                ],
                inner_puzzle,
            )
        else:
            restricted_inner_puzzle = inner_puzzle

        if _top_level:
            fed_inner_puzzle = DELEGATED_PUZZLE_FEEDER.curry(restricted_inner_puzzle)
        else:
            fed_inner_puzzle = restricted_inner_puzzle

        return INDEX_WRAPPER.curry(self.nonce, fed_inner_puzzle)

    def puzzle_hash(self, _top_level: bool = True) -> bytes32:
        inner_puzzle_hash = self.puzzle.puzzle_hash(self.nonce)  # pylint: disable=assignment-from-no-return

        if len(self.restrictions) > 0:  # We optimize away the restriction layer when no restrictions are present
            member_validator_hashes = [
                restriction.puzzle_hash(self.nonce) for restriction in self.restrictions if restriction.member_not_dpuz
            ]
            dpuz_validator_hashes = [
                restriction.puzzle_hash(self.nonce)
                for restriction in self.restrictions
                if not restriction.member_not_dpuz
            ]
            restricted_inner_puzzle_hash = (
                Program.to(RESTRICTION_MOD_HASH)
                .curry(
                    member_validator_hashes,
                    dpuz_validator_hashes,
                    inner_puzzle_hash,
                )
                .get_tree_hash_precalc(
                    *member_validator_hashes, *dpuz_validator_hashes, RESTRICTION_MOD_HASH, inner_puzzle_hash
                )
            )
        else:
            restricted_inner_puzzle_hash = inner_puzzle_hash

        if _top_level:
            fed_inner_puzzle_hash = (
                Program.to(DELEGATED_PUZZLE_FEEDER_HASH)
                .curry(restricted_inner_puzzle_hash)
                .get_tree_hash_precalc(DELEGATED_PUZZLE_FEEDER_HASH, restricted_inner_puzzle_hash)
            )
        else:
            fed_inner_puzzle_hash = restricted_inner_puzzle_hash

        return INDEX_WRAPPER.curry(self.nonce, fed_inner_puzzle_hash).get_tree_hash_precalc(fed_inner_puzzle_hash)

    def solve(
        self,
        member_validator_solutions: list[Program],  # solution for the restriction puzzle
        dpuz_validator_solutions: list[Program],
        member_solution: Program,
        delegated_puzzle_and_solution: DelegatedPuzzleAndSolution | None = None,
    ) -> Program:
        if len(self.restrictions) > 0:  # We optimize away the restriction layer when no restrictions are present
            solution = Program.to([member_validator_solutions, dpuz_validator_solutions, member_solution])
        else:
            solution = member_solution

        if delegated_puzzle_and_solution is not None:
            solution = Program.to(
                [delegated_puzzle_and_solution.puzzle, delegated_puzzle_and_solution.solution, *solution.as_iter()]
            )

        return solution
