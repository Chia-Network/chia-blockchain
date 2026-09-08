from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar, cast

from chia_puzzles_py.programs import DID_INNERPUZ, DID_INNERPUZ_HASH
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.puzzle_drivers import InnerPuzzle, OuterPuzzle, PuzzleWithPuzzleHash, UnknownPuzzle
from chia.wallet.puzzles.singleton_drivers import SingletonStruct
from chia.wallet.util.curry_and_treehash import (
    calculate_hash_of_quoted_mod_hash,
    curry_and_treehash,
)

DID_INNERPUZ_MOD = Program.from_bytes(DID_INNERPUZ)
DID_INNERPUZ_MOD_HASH = bytes32(DID_INNERPUZ_HASH)
DID_INNERPUZ_MOD_HASH_QUOTED = calculate_hash_of_quoted_mod_hash(DID_INNERPUZ_MOD_HASH)


class DIDMetadata(dict[str, str]):
    def as_program(self) -> Program:
        return Program.to([(k, v) for k, v in self.items()])

    @classmethod
    def from_program(cls, program: Program) -> DIDMetadata:
        return cls(
            {str(item.first().as_atom(), "utf-8"): str(item.rest().as_atom(), "utf-8") for item in program.as_iter()}
        )

    @cached_property
    def tree_hash(self) -> bytes32:
        return self.as_program().get_tree_hash()


_T_InnerPuzzle = TypeVar("_T_InnerPuzzle", bound=InnerPuzzle)


@dataclass(frozen=True, kw_only=True)
class RecoveryList:
    ids: list[bytes32] | None = None
    tree_hash: bytes32 | None = None

    @cached_property
    def ids_hash(self) -> bytes32 | None:
        if self.tree_hash is None:
            if self.ids is None or self.ids == []:
                return None
            return Program.to(self.ids).get_tree_hash()
        return self.tree_hash

    @cached_property
    def pre_hashed(self) -> bytes32:
        return Program.to(self.ids_hash).get_tree_hash()


@dataclass(frozen=True, kw_only=True)
class DIDRecoveryPuzzle(PuzzleWithPuzzleHash, Generic[_T_InnerPuzzle]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast(
            "DIDRecoveryPuzzle[_T_InnerPuzzle]", None
        )

    inner_puzzle: _T_InnerPuzzle
    self_launcher_id: bytes32
    metadata: DIDMetadata
    recovery_list: RecoveryList
    num_of_backup_ids_needed: uint64
    struct_driver: ClassVar[type[SingletonStruct]] = SingletonStruct

    @property
    def puzzle(self) -> Program:
        return DID_INNERPUZ_MOD.curry(
            self.inner_puzzle.puzzle,
            self.recovery_list.tree_hash,
            self.num_of_backup_ids_needed,
            self.struct_driver(launcher_id=self.self_launcher_id).program,
            self.metadata.as_program(),
        )

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return curry_and_treehash(
            DID_INNERPUZ_MOD_HASH_QUOTED,
            self.inner_puzzle.puzzle_hash,
            self.recovery_list.pre_hashed,
            Program.to(self.num_of_backup_ids_needed).get_tree_hash(),
            self.struct_driver(launcher_id=self.self_launcher_id).struct_hash,
            self.metadata.tree_hash,
        )

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> DIDRecoveryPuzzle[UnknownPuzzle] | None:
        if unknown_puzzle.mod != DID_INNERPUZ_MOD or unknown_puzzle.curried_args is None:
            return None

        (inner_puzzle, recovery_list_hash, num_of_backup_ids_needed, singleton_struct, metadata) = (
            unknown_puzzle.curried_args
        )
        return DIDRecoveryPuzzle(
            inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle),
            self_launcher_id=cls.struct_driver.from_program(singleton_struct).launcher_id,
            metadata=DIDMetadata.from_program(metadata),
            recovery_list=RecoveryList(
                tree_hash=bytes32(recovery_list_hash.as_atom()) if recovery_list_hash != Program.NIL else None
            ),
            num_of_backup_ids_needed=uint64(num_of_backup_ids_needed.as_int()),
        )
