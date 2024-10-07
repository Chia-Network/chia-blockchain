from __future__ import annotations

from dataclasses import dataclass, replace
from typing import List, Mapping, Protocol, Type, Union, cast

from typing_extensions import runtime_checkable

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32


# General (inner) puzzle driver spec
class Puzzle(Protocol):

    def memo(self, nonce: int) -> Program: ...

    def puzzle(self, nonce: int) -> Program: ...

    def puzzle_hash(self, nonce: int) -> bytes32: ...


@dataclass(frozen=True)
class PuzzleHint:
    puzhash: bytes32
    memo: Program

    def to_program(self) -> Program:
        return Program.to([self.puzhash, self.memo])

    @classmethod
    def from_program(cls, prog: Program) -> PuzzleHint:
        puzhash, memo = prog.as_iter()
        return PuzzleHint(
            bytes32(puzhash.as_atom()),
            memo,
        )


@dataclass(frozen=True)
class UnknownPuzzle:

    puzzle_hint: PuzzleHint

    def memo(self, nonce: int) -> Program:
        return self.puzzle_hint.memo

    def puzzle(self, nonce: int) -> Program:
        raise NotImplementedError("An unknown puzzle type cannot generate a puzzle reveal")

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.puzzle_hint.puzhash


# A spec for "restrictions" on specific inner puzzles
@runtime_checkable
class Restriction(Puzzle, Protocol):
    @property
    def _morpher_not_validator(self) -> bool: ...


def morpher(cls: Type[Puzzle]) -> Type[Restriction]:
    setattr(cls, "_morpher_not_validator", True)
    return cast(Type[Restriction], cls)


def validator(cls: Type[Puzzle]) -> Type[Restriction]:
    setattr(cls, "_morpher_not_validator", False)
    return cast(Type[Restriction], cls)


@dataclass(frozen=True)
class RestrictionHint:
    morpher_not_validator: bool
    puzhash: bytes32
    memo: Program

    def to_program(self) -> Program:
        return Program.to([self.morpher_not_validator, self.puzhash, self.memo])

    @classmethod
    def from_program(cls, prog: Program) -> RestrictionHint:
        morpher_not_validator, puzhash, memo = prog.as_iter()
        return RestrictionHint(
            morpher_not_validator != Program.to(None),
            bytes32(puzhash.as_atom()),
            memo,
        )


@dataclass(frozen=True)
class UnknownRestriction:
    restriction_hint: RestrictionHint

    @property
    def _morpher_not_validator(self) -> bool:
        return self.restriction_hint.morpher_not_validator

    def memo(self, nonce: int) -> Program:
        return self.restriction_hint.memo

    def puzzle(self, nonce: int) -> Program:
        raise NotImplementedError("An unknown restriction type cannot generate a puzzle reveal")

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.restriction_hint.puzhash


# MofN puzzle drivers which are a fundamental component of the architecture
@dataclass(frozen=True)
class MofNHint:
    m: int
    member_memos: List[Program]

    def to_program(self) -> Program:
        return Program.to([self.m, self.member_memos])

    @classmethod
    def from_program(cls, prog: Program) -> MofNHint:
        m, member_memos = prog.as_iter()
        return MofNHint(
            m.as_int(),
            list(member_memos.as_iter()),
        )


@dataclass(frozen=True)
class MofN:
    m: int
    members: List[PuzzleWithRestrictions]

    @property
    def n(self) -> int:
        return len(self.members)

    def memo(self, nonce: int) -> Program:
        raise NotImplementedError("PuzzleWithRestrictions handles MofN memos, this method should not be called")

    def puzzle(self, nonce: int) -> Program: ...  # type: ignore[empty-body]

    def puzzle_hash(self, nonce: int) -> bytes32: ...  # type: ignore[empty-body]


# The top-level object inside every "outer" puzzle
@dataclass(frozen=True)
class PuzzleWithRestrictions:
    nonce: int
    restrictions: List[Restriction]
    puzzle: Puzzle

    def memo(self) -> Program:
        restriction_hints: List[RestrictionHint] = [
            RestrictionHint(
                restriction._morpher_not_validator, restriction.puzzle_hash(self.nonce), restriction.memo(self.nonce)
            )
            for restriction in self.restrictions
        ]

        puzzle_hint: Union[MofNHint, PuzzleHint]
        if isinstance(self.puzzle, MofN):
            puzzle_hint = MofNHint(self.puzzle.m, [member.memo() for member in self.puzzle.members])
        else:
            puzzle_hint = PuzzleHint(
                self.puzzle.puzzle_hash(self.nonce),
                self.puzzle.memo(self.nonce),
            )

        return Program.to(
            [
                self.nonce,
                [hint.to_program() for hint in restriction_hints],
                1 if isinstance(self.puzzle, MofN) else 0,
                puzzle_hint.to_program(),
            ]
        )

    @classmethod
    def from_memo(cls, memo: Program) -> PuzzleWithRestrictions:
        nonce, restriction_hints_prog, further_branching_prog, puzzle_hint_prog = memo.as_iter()
        restriction_hints = [RestrictionHint.from_program(hint) for hint in restriction_hints_prog.as_iter()]
        further_branching = further_branching_prog != Program.to(None)
        if further_branching:
            m_of_n_hint = MofNHint.from_program(puzzle_hint_prog)
            puzzle: Puzzle = MofN(
                m_of_n_hint.m, [PuzzleWithRestrictions.from_memo(memo) for memo in m_of_n_hint.member_memos]
            )
        else:
            puzzle_hint = PuzzleHint.from_program(puzzle_hint_prog)
            puzzle = UnknownPuzzle(puzzle_hint)

        return PuzzleWithRestrictions(
            nonce.as_int(),
            [UnknownRestriction(hint) for hint in restriction_hints],
            puzzle,
        )

    @property
    def unknown_puzzles(self) -> Mapping[bytes32, Union[UnknownPuzzle, UnknownRestriction]]:
        unknown_restrictions = {
            ur.restriction_hint.puzhash: ur for ur in self.restrictions if isinstance(ur, UnknownRestriction)
        }

        unknown_puzzles: Mapping[bytes32, Union[UnknownPuzzle, UnknownRestriction]]
        if isinstance(self.puzzle, UnknownPuzzle):
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

    def fill_in_unknown_puzzles(self, puzzle_dict: Mapping[bytes32, Puzzle]) -> PuzzleWithRestrictions:
        new_restrictions: List[Restriction] = []
        for restriction in self.restrictions:
            if isinstance(restriction, UnknownRestriction) and restriction.restriction_hint.puzhash in puzzle_dict:
                new = puzzle_dict[restriction.restriction_hint.puzhash]
                assert isinstance(new, Restriction)
                new_restrictions.append(new)
            else:
                new_restrictions.append(restriction)

        new_puzzle: Puzzle
        if isinstance(self.puzzle, UnknownPuzzle) and self.puzzle.puzzle_hint.puzhash in puzzle_dict:
            new_puzzle = puzzle_dict[self.puzzle.puzzle_hint.puzhash]
        elif isinstance(self.puzzle, MofN):
            new_puzzle = replace(
                self.puzzle, members=[puz.fill_in_unknown_puzzles(puzzle_dict) for puz in self.puzzle.members]
            )
        else:
            new_puzzle = self.puzzle

        return PuzzleWithRestrictions(
            self.nonce,
            new_restrictions,
            new_puzzle,
        )

    def puzzle_reveal(self) -> Program: ...  # type: ignore[empty-body]

    def puzzle_hash(self) -> bytes32: ...  # type: ignore[empty-body]
