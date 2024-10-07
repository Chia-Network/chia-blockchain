from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, Type, Union, cast

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32


class Puzzle(Protocol):

    def memo(self, nonce: int) -> Program: ...

    def puzzle(self, nonce: int) -> Program: ...

    def puzzle_hash(self, nonce: int) -> bytes32: ...


@dataclass(frozen=True)
class UnknownPuzzle:

    custody_hint: CustodyHint

    def memo(self, nonce: int) -> Program:
        return self.custody_hint.memo

    def puzzle(self, nonce: int) -> Program:
        raise NotImplementedError("An unknown custody type cannot generate a puzzle reveal")

    def puzzle_hash(self, nonce: int) -> bytes32:
        return self.custody_hint.puzhash


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
class CustodyHint:
    puzhash: bytes32
    memo: Program

    def to_program(self) -> Program:
        return Program.to([self.puzhash, self.memo])

    @classmethod
    def from_program(cls, prog: Program) -> CustodyHint:
        puzhash, memo = prog.as_iter()
        return CustodyHint(
            bytes32(puzhash.as_atom()),
            memo,
        )


@dataclass(frozen=True)
class CustodyWithRestrictions:
    nonce: int
    restrictions: List[Restriction]
    custody: Puzzle

    def memo(self) -> Program:
        restriction_hints: List[RestrictionHint] = [
            RestrictionHint(
                restriction._morpher_not_validator, restriction.puzzle_hash(self.nonce), restriction.memo(self.nonce)
            )
            for restriction in self.restrictions
        ]

        custody_hint: Union[MofNHint, CustodyHint]
        if isinstance(self.custody, MofN):
            custody_hint = MofNHint(self.custody.m, [member.memo() for member in self.custody.members])
        else:
            custody_hint = CustodyHint(
                self.custody.puzzle_hash(self.nonce),
                self.custody.memo(self.nonce),
            )

        return Program.to(
            [
                self.nonce,
                [hint.to_program() for hint in restriction_hints],
                1 if isinstance(self.custody, MofN) else 0,
                custody_hint.to_program(),
            ]
        )

    @classmethod
    def from_memo(cls, memo: Program) -> CustodyWithRestrictions:
        nonce, restriction_hints_prog, further_branching_prog, custody_hint_prog = memo.as_iter()
        restriction_hints = [RestrictionHint.from_program(hint) for hint in restriction_hints_prog.as_iter()]
        further_branching = further_branching_prog != Program.to(None)
        if further_branching:
            m_of_n_hint = MofNHint.from_program(custody_hint_prog)
            custody: Puzzle = MofN(
                m_of_n_hint.m, [CustodyWithRestrictions.from_memo(memo) for memo in m_of_n_hint.member_memos]
            )
        else:
            custody_hint = CustodyHint.from_program(custody_hint_prog)
            custody = UnknownPuzzle(custody_hint)

        return CustodyWithRestrictions(
            nonce.as_int(),
            [UnknownRestriction(hint) for hint in restriction_hints],
            custody,
        )

    def puzzle(self) -> Program: ...  # type: ignore[empty-body]

    def puzzle_hash(self) -> bytes32: ...  # type: ignore[empty-body]


@dataclass(frozen=True)
class MofN:
    m: int
    members: List[CustodyWithRestrictions]

    @property
    def n(self) -> int:
        return len(self.members)

    def memo(self, nonce: int) -> Program:
        raise NotImplementedError("CustodyWithRestrictions handles MofN memos, this method should not be called")

    def puzzle(self, nonce: int) -> Program: ...  # type: ignore[empty-body]

    def puzzle_hash(self, nonce: int) -> bytes32: ...  # type: ignore[empty-body]
