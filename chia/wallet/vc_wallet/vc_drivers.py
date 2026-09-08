from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, cast, final

from chia_puzzles_py.programs import ACS_TRANSFER_PROGRAM as ACS_TRANSFER_PROGRAM_BYTES
from chia_puzzles_py.programs import COVENANT_LAYER as COVENANT_LAYER_BYTES
from chia_puzzles_py.programs import COVENANT_LAYER_HASH as COVENANT_LAYER_HASH_BYTES
from chia_puzzles_py.programs import EML_COVENANT_MORPHER as EML_COVENANT_MORPHER_BYTES
from chia_puzzles_py.programs import EML_COVENANT_MORPHER_HASH as EML_COVENANT_MORPHER_HASH_BYTES
from chia_puzzles_py.programs import EML_TRANSFER_PROGRAM_COVENANT_ADAPTER as EML_TP_COVENANT_ADAPTER_BYTES
from chia_puzzles_py.programs import EML_TRANSFER_PROGRAM_COVENANT_ADAPTER_HASH as EML_TP_COVENANT_ADAPTER_HASH_BYTES
from chia_puzzles_py.programs import EML_UPDATE_METADATA_WITH_DID as EML_DID_TP_BYTES
from chia_puzzles_py.programs import EXIGENT_METADATA_LAYER as EXIGENT_METADATA_LAYER_BYTES
from chia_puzzles_py.programs import EXIGENT_METADATA_LAYER_HASH as EXIGENT_METADATA_LAYER_HASH_BYTES
from chia_puzzles_py.programs import P2_ANNOUNCED_DELEGATED_PUZZLE as P2_ANNOUNCED_DELEGATED_PUZZLE_BYTES
from chia_puzzles_py.programs import P2_ANNOUNCED_DELEGATED_PUZZLE_HASH as P2_ANNOUNCED_DELEGATED_PUZZLE_HASH_BYTES
from chia_puzzles_py.programs import REVOCATION_LAYER as REVOCATION_LAYER_BYTES
from chia_puzzles_py.programs import REVOCATION_LAYER_HASH as REVOCATION_LAYER_HASH_BYTES
from chia_puzzles_py.programs import STANDARD_VC_REVOCATION_PUZZLE as STANDARD_VC_REVOCATION_PUZZLE_BYTES
from chia_puzzles_py.programs import STD_PARENT_MORPHER as STD_PARENT_MORPHER_BYTES
from chia_puzzles_py.programs import STD_PARENT_MORPHER_HASH as STD_PARENT_MORPHER_HASH_BYTES
from chia_rs import CoinSpend
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.util.hash import std_hash
from chia.util.streamable import Streamable, streamable
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    Condition,
    CreateCoin,
    CreatePuzzleAnnouncement,
    ReserveFee,
    UnknownCondition,
)
from chia.wallet.lineage_proof import LineageProof, LineageProofField
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.puzzle_drivers import (
    InnerPuzzle,
    OuterPuzzle,
    P2Conditions,
    PuzzleWithPuzzleHash,
    Solution,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.puzzles.singleton_drivers import (
    Singleton,
    SingletonCorePuzzles,
    SingletonLaunchInfo,
    SingletonLaunchResult,
    SingletonPuzzle,
    new_create_coin_from_inner_puzzle_and_solution,
)
from chia.wallet.uncurried_puzzle import UncurriedPuzzle, uncurry_puzzle
from chia.wallet.util.compute_additions import compute_additions

# Mods
EXTIGENT_METADATA_LAYER = Program.from_bytes(EXIGENT_METADATA_LAYER_BYTES)
P2_ANNOUNCED_DELEGATED_PUZZLE: Program = Program.from_bytes(P2_ANNOUNCED_DELEGATED_PUZZLE_BYTES)
COVENANT_LAYER: Program = Program.from_bytes(COVENANT_LAYER_BYTES)
STD_COVENANT_PARENT_MORPHER: Program = Program.from_bytes(STD_PARENT_MORPHER_BYTES)
EML_TP_COVENANT_ADAPTER: Program = Program.from_bytes(EML_TP_COVENANT_ADAPTER_BYTES)
EML_DID_TP: Program = Program.from_bytes(EML_DID_TP_BYTES)
EXTIGENT_METADATA_LAYER_COVENANT_MORPHER: Program = Program.from_bytes(EML_COVENANT_MORPHER_BYTES)
REVOCATION_LAYER: Program = Program.from_bytes(REVOCATION_LAYER_BYTES)
ACS_TRANSFER_PROGRAM: Program = Program.from_bytes(ACS_TRANSFER_PROGRAM_BYTES)
STANDARD_VC_REVOCATION_PUZZLE: Program = Program.from_bytes(STANDARD_VC_REVOCATION_PUZZLE_BYTES)

# Hashes
EXTIGENT_METADATA_LAYER_HASH = bytes32(EXIGENT_METADATA_LAYER_HASH_BYTES)
P2_ANNOUNCED_DELEGATED_PUZZLE_HASH: bytes32 = bytes32(P2_ANNOUNCED_DELEGATED_PUZZLE_HASH_BYTES)
COVENANT_LAYER_HASH: bytes32 = bytes32(COVENANT_LAYER_HASH_BYTES)
STD_COVENANT_PARENT_MORPHER_HASH: bytes32 = bytes32(STD_PARENT_MORPHER_HASH_BYTES)
EML_TP_COVENANT_ADAPTER_HASH: bytes32 = bytes32(EML_TP_COVENANT_ADAPTER_HASH_BYTES)
EXTIGENT_METADATA_LAYER_COVENANT_MORPHER_HASH: bytes32 = bytes32(EML_COVENANT_MORPHER_HASH_BYTES)
REVOCATION_LAYER_HASH: bytes32 = bytes32(REVOCATION_LAYER_HASH_BYTES)


##########################
# Standard Brick Puzzle #
##########################


@dataclass(frozen=True, kw_only=True)
class StandardBrickPuzzle(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[InnerPuzzle] = cast("StandardBrickPuzzle", None)

    singleton_puzzles: ClassVar[SingletonCorePuzzles] = SingletonCorePuzzles()

    @property
    def puzzle(self) -> Program:
        return STANDARD_VC_REVOCATION_PUZZLE.curry(
            self.singleton_puzzles.singleton_mod_hash,
            Program.to(self.singleton_puzzles.singleton_launcher_hash).get_tree_hash(),
            EXTIGENT_METADATA_LAYER_HASH,
            REVOCATION_LAYER_HASH,
            ACS_TRANSFER_PROGRAM.get_tree_hash(),
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> StandardBrickPuzzle | None:
        if unknown_puzzle.known_puzzle is None:
            if unknown_puzzle.known_puzzle_hash == STANDARD_BRICK_PUZZLE_HASH:
                return StandardBrickPuzzle()
            return None
        if unknown_puzzle.mod != STANDARD_VC_REVOCATION_PUZZLE:
            return None
        return StandardBrickPuzzle()


# Standard brick puzzle uses the mods above
STANDARD_BRICK_PUZZLE: Program = StandardBrickPuzzle().puzzle
STANDARD_BRICK_PUZZLE_HASH: bytes32 = STANDARD_BRICK_PUZZLE.get_tree_hash()
STANDARD_BRICK_PUZZLE_HASH_HASH: bytes32 = Program.to(STANDARD_BRICK_PUZZLE_HASH).get_tree_hash()


##################
# Covenant Layer #
##################
_T_ParentMorpher = TypeVar("_T_ParentMorpher", bound=InnerPuzzle)
_T_CovenantInnerPuzzle = TypeVar("_T_CovenantInnerPuzzle", bound=InnerPuzzle)


@dataclass(frozen=True, kw_only=True)
class CovenantLayer(PuzzleWithPuzzleHash, Generic[_T_ParentMorpher, _T_CovenantInnerPuzzle]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast(
            "CovenantLayer[_T_ParentMorpher, _T_CovenantInnerPuzzle]", None
        )
    initial_puzzle_hash: bytes32
    parent_morpher: _T_ParentMorpher
    inner_puzzle: _T_CovenantInnerPuzzle

    @property
    def puzzle(self) -> Program:
        return COVENANT_LAYER.curry(
            self.initial_puzzle_hash,
            self.parent_morpher.puzzle,
            self.inner_puzzle.puzzle,
        )

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> CovenantLayer[UnknownPuzzle, UnknownPuzzle] | None:
        if unknown_puzzle.mod != COVENANT_LAYER or unknown_puzzle.curried_args is None:
            return None

        (inner_puzzle_hash_prog, parent_morpher_prog, inner_puzzle_prog) = unknown_puzzle.curried_args
        return CovenantLayer(
            initial_puzzle_hash=bytes32(inner_puzzle_hash_prog.as_atom()),
            parent_morpher=UnknownPuzzle(known_puzzle=parent_morpher_prog),
            inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle_prog),
        )


_T_MorpherSolution = TypeVar("_T_MorpherSolution", bound=Solution)
_T_InnerSolution = TypeVar("_T_InnerSolution", bound=Solution)


@dataclass(frozen=True, kw_only=True)
class CovenantLayerSolution(Generic[_T_MorpherSolution, _T_InnerSolution]):
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast(
            "CovenantLayerSolution[_T_MorpherSolution, _T_InnerSolution]", None
        )

    lineage_proof: LineageProof
    morpher_solution: _T_MorpherSolution
    inner_solution: _T_InnerSolution

    def as_program(self) -> Program:
        return Program.to(
            [
                self.lineage_proof.to_program(),
                self.morpher_solution.as_program(),
                self.inner_solution.as_program(),
            ]
        )

    @classmethod
    def match(
        cls, *, unknown_solution: UnknownSolution
    ) -> CovenantLayerSolution[UnknownSolution, UnknownSolution] | None:
        if unknown_solution.as_program().atom is not None:
            return None
        list_of_values = list(unknown_solution.as_program().as_iter())
        if len(list_of_values) != 3:
            return None
        num_lineage_proof_fields = len(list(list_of_values[0].as_iter()))
        return CovenantLayerSolution(
            lineage_proof=LineageProof.from_program(
                list_of_values[0],
                [LineageProofField.PARENT_NAME, LineageProofField.AMOUNT]
                if num_lineage_proof_fields == 2
                else [LineageProofField.PARENT_NAME, LineageProofField.INNER_PUZZLE_HASH, LineageProofField.AMOUNT],
            ),
            morpher_solution=UnknownSolution(list_of_values[1]),
            inner_solution=UnknownSolution(list_of_values[2]),
        )


@dataclass(frozen=True, kw_only=True)
class StdParentMorpher(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[InnerPuzzle] = cast("StdParentMorpher", None)

    initial_puzzle_hash: bytes32

    @property
    def puzzle(self) -> Program:
        return STD_COVENANT_PARENT_MORPHER.curry(
            STD_COVENANT_PARENT_MORPHER_HASH,
            COVENANT_LAYER_HASH,
            self.initial_puzzle_hash,
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> StdParentMorpher | None:
        if unknown_puzzle.mod != STD_COVENANT_PARENT_MORPHER or unknown_puzzle.curried_args is None:
            return None
        (_mod_hash, _covenant_layer_hash, initial_puzzle_hash_prog) = unknown_puzzle.curried_args
        return StdParentMorpher(initial_puzzle_hash=bytes32(initial_puzzle_hash_prog.as_atom()))


####################
# Covenant Adapter #
####################


_T_CovenantLayer = TypeVar("_T_CovenantLayer", bound=InnerPuzzle)


@dataclass(frozen=True, kw_only=True)
class TransferProgramCovenantAdapter(PuzzleWithPuzzleHash, Generic[_T_CovenantLayer]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast(
            "TransferProgramCovenantAdapter[_T_CovenantLayer]", None
        )

    inner_puzzle: _T_CovenantLayer

    @property
    def puzzle(self) -> Program:
        return EML_TP_COVENANT_ADAPTER.curry(self.inner_puzzle.puzzle)

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> TransferProgramCovenantAdapter[UnknownPuzzle] | None:
        if unknown_puzzle.mod != EML_TP_COVENANT_ADAPTER or unknown_puzzle.curried_args is None:
            return None
        (covenant_layer_prog,) = unknown_puzzle.curried_args
        return TransferProgramCovenantAdapter(inner_puzzle=UnknownPuzzle(known_puzzle=covenant_layer_prog))


##################################
# Update w/ DID Transfer Program #
##################################


@dataclass(frozen=True, kw_only=True)
class DidTransferProgram(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[InnerPuzzle] = cast("DidTransferProgram", None)

    singleton_puzzles: ClassVar[SingletonCorePuzzles] = SingletonCorePuzzles()

    @property
    def puzzle(self) -> Program:
        return EML_DID_TP.curry(
            self.singleton_puzzles.singleton_mod_hash, self.singleton_puzzles.singleton_launcher_hash
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> DidTransferProgram | None:
        if unknown_puzzle.mod == EML_DID_TP:
            return DidTransferProgram()
        return None


@dataclass(frozen=True, kw_only=True)
class DidTpSolution:
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast("DidTpSolution", None)

    provider_innerpuzhash: bytes32
    my_coin_id: bytes32
    new_metadata: Program
    new_transfer_program: bytes32 | None

    def as_program(self) -> Program:
        return Program.to(
            [
                self.provider_innerpuzhash,
                self.my_coin_id,
                self.new_metadata,
                self.new_transfer_program,
            ]
        )

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> DidTpSolution | None:
        if unknown_solution.as_program().atom is not None:
            return None
        list_of_values = list(unknown_solution.as_program().as_iter())
        if len(list_of_values) != 4:
            return None
        new_transfer_program_prog = list_of_values[3]
        return cls(
            provider_innerpuzhash=bytes32(list_of_values[0].as_atom()),
            my_coin_id=bytes32(list_of_values[1].as_atom()),
            new_metadata=list_of_values[2],
            new_transfer_program=None
            if new_transfer_program_prog == Program.NIL
            else bytes32(new_transfer_program_prog.as_atom()),
        )


##############################
# P2 Puzzle or Hidden Puzzle #
##############################


_T_RevocationInnerPuzzle = TypeVar("_T_RevocationInnerPuzzle", bound=InnerPuzzle)
_T_RevocationHiddenPuzzle = TypeVar("_T_RevocationHiddenPuzzle", bound=InnerPuzzle)


@dataclass(frozen=True, kw_only=True)
class RevocationLayer(PuzzleWithPuzzleHash, Generic[_T_RevocationInnerPuzzle, _T_RevocationHiddenPuzzle]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast(
            "RevocationLayer[_T_RevocationInnerPuzzle, _T_RevocationHiddenPuzzle]", None
        )

    inner_puzzle: _T_RevocationInnerPuzzle
    hidden_puzzle: _T_RevocationHiddenPuzzle

    @property
    def puzzle(self) -> Program:
        return REVOCATION_LAYER.curry(
            REVOCATION_LAYER_HASH, self.hidden_puzzle.puzzle_hash, self.inner_puzzle.puzzle_hash
        )

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> RevocationLayer[UnknownPuzzle, UnknownPuzzle] | None:
        if unknown_puzzle.mod != REVOCATION_LAYER or unknown_puzzle.curried_args is None:
            return None
        (_mod_hash, hidden_puzzle_hash_prog, inner_puzzle_hash_prog) = unknown_puzzle.curried_args
        return RevocationLayer(
            hidden_puzzle=UnknownPuzzle(known_puzzle_hash=bytes32(hidden_puzzle_hash_prog.as_atom())),
            inner_puzzle=UnknownPuzzle(known_puzzle_hash=bytes32(inner_puzzle_hash_prog.as_atom())),
        )


_T_RevocationPuzzleReveal = TypeVar("_T_RevocationPuzzleReveal", bound=InnerPuzzle)


@dataclass(frozen=True, kw_only=True)
class RevocationLayerSolution(Generic[_T_RevocationPuzzleReveal, _T_InnerSolution]):
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast(
            "RevocationLayerSolution[_T_RevocationPuzzleReveal, _T_InnerSolution]", None
        )

    puzzle_reveal: _T_RevocationPuzzleReveal
    inner_solution: _T_InnerSolution
    hidden: bool = False

    def as_program(self) -> Program:
        return Program.to(
            [
                self.hidden,
                self.puzzle_reveal.puzzle,
                self.inner_solution.as_program(),
            ]
        )

    @classmethod
    def match(
        cls, *, unknown_solution: UnknownSolution
    ) -> RevocationLayerSolution[UnknownPuzzle, UnknownSolution] | None:
        if unknown_solution.as_program().atom is not None:
            return None
        list_of_values = list(unknown_solution.as_program().as_iter())
        if len(list_of_values) != 3:
            return None
        return RevocationLayerSolution(
            hidden=list_of_values[0] != Program.NIL,
            puzzle_reveal=UnknownPuzzle(known_puzzle=list_of_values[1]),
            inner_solution=UnknownSolution(list_of_values[2]),
        )


########
# MISC #
########


_T_EmlCovenantMorpherTp = TypeVar("_T_EmlCovenantMorpherTp", bound=InnerPuzzle)


@dataclass(frozen=True, kw_only=True)
class EmlCovenantMorpher(PuzzleWithPuzzleHash, Generic[_T_EmlCovenantMorpherTp]):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[InnerPuzzle] = cast("EmlCovenantMorpher[_T_EmlCovenantMorpherTp]", None)

    transfer_program: _T_EmlCovenantMorpherTp
    singleton_puzzles: ClassVar[SingletonCorePuzzles] = SingletonCorePuzzles()

    @property
    def puzzle(self) -> Program:
        first_curry: Program = EXTIGENT_METADATA_LAYER_COVENANT_MORPHER.curry(
            COVENANT_LAYER_HASH,
            EXTIGENT_METADATA_LAYER_HASH,
            EML_TP_COVENANT_ADAPTER_HASH,
            self.singleton_puzzles.singleton_mod_hash,
            Program.to(self.singleton_puzzles.singleton_launcher_hash).get_tree_hash(),
            self.transfer_program.puzzle_hash,
        )
        return first_curry.curry(first_curry.get_tree_hash())

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> EmlCovenantMorpher[UnknownPuzzle] | None:
        if unknown_puzzle.mod is None or unknown_puzzle.curried_args is None:
            return None
        first_curry = UnknownPuzzle(known_puzzle=unknown_puzzle.mod)
        if first_curry.mod != EXTIGENT_METADATA_LAYER_COVENANT_MORPHER or first_curry.curried_args is None:
            return None
        curried_args = list(first_curry.curried_args)
        if len(curried_args) != 6:
            return None
        return EmlCovenantMorpher(transfer_program=UnknownPuzzle(known_puzzle_hash=bytes32(curried_args[5].as_atom())))


@dataclass(frozen=True, kw_only=True)
class EmlCovenantMorpherSolution:
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast("EmlCovenantMorpherSolution", None)

    parent_proof_hash: bytes32 | None
    launcher_id: bytes32

    def as_program(self) -> Program:
        return Program.to([self.parent_proof_hash, self.launcher_id])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> EmlCovenantMorpherSolution | None:
        if unknown_solution.as_program().atom is not None:
            return None
        list_of_values = list(unknown_solution.as_program().as_iter())
        if len(list_of_values) != 2:
            return None
        parent_proof_hash_prog = list_of_values[0]
        return cls(
            parent_proof_hash=None
            if parent_proof_hash_prog == Program.NIL
            else bytes32(parent_proof_hash_prog.as_atom()),
            launcher_id=bytes32(list_of_values[1].as_atom()),
        )


_T_TransferProgram = TypeVar("_T_TransferProgram", bound=InnerPuzzle)
_T_EMLInnerPuzzle = TypeVar("_T_EMLInnerPuzzle", bound=InnerPuzzle)


@dataclass(frozen=True, kw_only=True)
class ExigentMetadataLayer(PuzzleWithPuzzleHash, Generic[_T_TransferProgram, _T_EMLInnerPuzzle]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast(
            "ExigentMetadataLayer[_T_TransferProgram, _T_EMLInnerPuzzle]", None
        )

    metadata: Program | None
    transfer_program: _T_TransferProgram
    inner_puzzle: _T_EMLInnerPuzzle

    @property
    def puzzle(self) -> Program:
        return EXTIGENT_METADATA_LAYER.curry(
            EXTIGENT_METADATA_LAYER_HASH,
            self.metadata,
            self.transfer_program.puzzle,
            self.transfer_program.puzzle_hash,
            self.inner_puzzle.puzzle,
        )

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> ExigentMetadataLayer[UnknownPuzzle, UnknownPuzzle] | None:
        if unknown_puzzle.mod != EXTIGENT_METADATA_LAYER or unknown_puzzle.curried_args is None:
            return None
        (_mod_hash, metadata_prog, transfer_program_prog, _tp_hash, inner_puzzle_prog) = unknown_puzzle.curried_args
        return ExigentMetadataLayer(
            metadata=None if metadata_prog == Program.NIL else metadata_prog,
            transfer_program=UnknownPuzzle(known_puzzle=transfer_program_prog),
            inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle_prog),
        )


@dataclass(frozen=True, kw_only=True)
class ExigentMetadataLayerSolution(Generic[_T_InnerSolution]):
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast("ExigentMetadataLayerSolution[_T_InnerSolution]", None)

    inner_solution: _T_InnerSolution

    def as_program(self) -> Program:
        return Program.to([self.inner_solution.as_program()])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> ExigentMetadataLayerSolution[UnknownSolution] | None:
        if unknown_solution.as_program().atom is not None:
            return None
        list_of_values = list(unknown_solution.as_program().as_iter())
        if len(list_of_values) != 1:
            return None
        return ExigentMetadataLayerSolution(inner_solution=UnknownSolution(list_of_values[0]))


@streamable
@dataclass(frozen=True)
class VCLineageProof(LineageProof, Streamable):
    """
    The covenant layer for exigent metadata layers requires to be passed the previous parent's metadata too
    """

    parent_proof_hash: bytes32 | None = None


@dataclass(frozen=True, kw_only=True)
class StandardBrickPuzzleSolution:
    """
    Solution to StandardBrickPuzzle. Requires proof info about pretty much the whole puzzle stack.
    """

    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast("StandardBrickPuzzleSolution", None)

    launcher_id: bytes32
    metadata_hash: bytes32
    tp_hash: bytes32
    inner_puzzle_hash: bytes32
    amount: uint64
    eml_lineage_proof: VCLineageProof
    provider_innerpuzhash: bytes32
    coin_id: bytes32
    announcement_nonce: bytes32 | None = None

    def as_program(self) -> Program:
        return Program.to(
            [
                self.launcher_id,
                self.metadata_hash,
                self.tp_hash,
                STANDARD_BRICK_PUZZLE_HASH_HASH,
                self.inner_puzzle_hash,
                self.amount,
                self.eml_lineage_proof.to_program(),
                Program.to(self.eml_lineage_proof.parent_proof_hash),
                self.announcement_nonce,
                Program.to(
                    [
                        self.provider_innerpuzhash,
                        self.coin_id,
                    ]
                ),
            ]
        )

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> StandardBrickPuzzleSolution | None:
        if unknown_solution.as_program().atom is not None:
            return None
        list_of_values = list(unknown_solution.as_program().as_iter())
        if len(list_of_values) != 10:
            return None
        announcement_nonce_prog = list_of_values[8]
        provider_and_coin = list(list_of_values[9].as_iter())
        if len(provider_and_coin) != 2:
            return None
        lineage_proof = LineageProof.from_program(
            list_of_values[6],
            [LineageProofField.PARENT_NAME, LineageProofField.INNER_PUZZLE_HASH, LineageProofField.AMOUNT],
        )
        parent_proof_hash_prog = list_of_values[7]
        return cls(
            launcher_id=bytes32(list_of_values[0].as_atom()),
            metadata_hash=bytes32(list_of_values[1].as_atom()),
            tp_hash=bytes32(list_of_values[2].as_atom()),
            inner_puzzle_hash=bytes32(list_of_values[4].as_atom()),
            amount=uint64(list_of_values[5].as_int()),
            eml_lineage_proof=VCLineageProof(
                parent_name=lineage_proof.parent_name,
                inner_puzzle_hash=lineage_proof.inner_puzzle_hash,
                amount=lineage_proof.amount,
                parent_proof_hash=None
                if parent_proof_hash_prog == Program.NIL
                else bytes32(parent_proof_hash_prog.as_atom()),
            ),
            provider_innerpuzhash=bytes32(provider_and_coin[0].as_atom()),
            coin_id=bytes32(provider_and_coin[1].as_atom()),
            announcement_nonce=None
            if announcement_nonce_prog == Program.NIL
            else bytes32(announcement_nonce_prog.as_atom()),
        )


# Launching to a VC requires a OL with a transfer program that guarantees a () metadata on the next iteration
# (mod (_ _ (provider tp)) (list (c provider ()) tp ()))
# (c (c 19 ()) (c 43 (q ())))
GUARANTEED_NIL_TP = UnknownPuzzle(known_puzzle=Program.fromhex("ff04ffff04ff13ff8080ffff04ff2bffff01ff80808080"))
OWNERSHIP_LAYER_LAUNCHER = ExigentMetadataLayer(
    metadata=None,
    transfer_program=GUARANTEED_NIL_TP,
    inner_puzzle=UnknownPuzzle(known_puzzle=P2_ANNOUNCED_DELEGATED_PUZZLE),
)
GUARANTEED_NIL_TP_HASH: bytes32 = GUARANTEED_NIL_TP.puzzle_hash
OWNERSHIP_LAYER_LAUNCHER_HASH = OWNERSHIP_LAYER_LAUNCHER.puzzle_hash


########################
# Verified Credentials #
########################


@final
@streamable
@dataclass(kw_only=True, frozen=True)
class MagicTPCondition(Condition):
    eml_lineage_proof: VCLineageProof
    launcher_id: bytes32
    tp_solution: Program | None

    def to_program(self) -> Program:
        return Program.to(
            [
                -10,
                self.eml_lineage_proof.to_program(),
                [self.eml_lineage_proof.parent_proof_hash, self.launcher_id],
                self.tp_solution,
            ]
        )

    @classmethod
    def from_program(cls, program: Program) -> MagicTPCondition:
        raise NotImplementedError


@streamable
@dataclass(frozen=True)
class StreamableVerifiedCredential(Streamable):
    coin: Coin
    singleton_lineage_proof: LineageProof
    eml_lineage_proof: VCLineageProof
    launcher_id: bytes32
    inner_puzzle_hash: bytes32
    proof_provider: bytes32
    proof_hash: bytes32 | None


_T_VCInnerPuzzle = TypeVar("_T_VCInnerPuzzle", bound=InnerPuzzle)


@dataclass(kw_only=True, frozen=True)
class VerifiedCredentialInnerPuzzle(PuzzleWithPuzzleHash, Generic[_T_VCInnerPuzzle]):
    """
    This class serves as the main driver for the entire VC puzzle stack. Given the information below, it can sync and
    spend VerifiedCredentials in any specified manner. Trying to sync from a spend that this class did not create will
    likely result in an error.
    """

    eml_lineage_proof: VCLineageProof
    self_launcher_id: bytes32
    custody_puzzle: _T_VCInnerPuzzle
    proof_provider: bytes32
    proof_hash: bytes32 | None

    @property
    def construction(
        self,
    ) -> ExigentMetadataLayer[
        TransferProgramCovenantAdapter[CovenantLayer[EmlCovenantMorpher[DidTransferProgram], DidTransferProgram]],
        RevocationLayer[_T_VCInnerPuzzle, StandardBrickPuzzle],
    ]:
        return ExigentMetadataLayer(
            metadata=Program.to((self.proof_provider, self.proof_hash)),
            transfer_program=self.transfer_program,
            inner_puzzle=self.revocation_layer,
        )

    @property
    def transfer_program(
        self,
    ) -> TransferProgramCovenantAdapter[CovenantLayer[EmlCovenantMorpher[DidTransferProgram], DidTransferProgram]]:
        return TransferProgramCovenantAdapter(
            inner_puzzle=CovenantLayer(
                initial_puzzle_hash=SingletonPuzzle(
                    launcher_id=self.self_launcher_id, inner_puzzle=OWNERSHIP_LAYER_LAUNCHER
                ).puzzle_hash,
                parent_morpher=EmlCovenantMorpher(transfer_program=DidTransferProgram()),
                inner_puzzle=DidTransferProgram(),
            )
        )

    @property
    def revocation_layer(self) -> RevocationLayer[_T_VCInnerPuzzle, StandardBrickPuzzle]:
        return RevocationLayer(inner_puzzle=self.custody_puzzle, hidden_puzzle=StandardBrickPuzzle())

    def wrap_inner_with_backdoor(self) -> Program:
        return self.revocation_layer.puzzle

    @property
    def puzzle(self) -> Program:
        return self.construction.puzzle

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return self.construction.puzzle_hash

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> VerifiedCredentialInnerPuzzle[UnknownPuzzle] | None:
        eml_match = ExigentMetadataLayer.match(unknown_puzzle=unknown_puzzle)
        if eml_match is None or eml_match.metadata is None:
            return None

        try:
            proof_provider = bytes32(eml_match.metadata.at("f").as_atom())
            proof_hash_prog = eml_match.metadata.at("r")
            proof_hash = None if proof_hash_prog == Program.NIL else bytes32(proof_hash_prog.as_atom())
        except Exception:
            return None

        assert isinstance(eml_match.transfer_program, UnknownPuzzle)
        tp_adapter = TransferProgramCovenantAdapter.match(unknown_puzzle=eml_match.transfer_program)
        if tp_adapter is None:
            return None

        assert isinstance(tp_adapter.inner_puzzle, UnknownPuzzle)
        covenant = CovenantLayer.match(unknown_puzzle=tp_adapter.inner_puzzle)
        if covenant is None:
            return None

        assert isinstance(covenant.parent_morpher, UnknownPuzzle)
        if EmlCovenantMorpher.match(unknown_puzzle=covenant.parent_morpher) is None:
            return None

        assert isinstance(covenant.inner_puzzle, UnknownPuzzle)
        if DidTransferProgram.match(unknown_puzzle=covenant.inner_puzzle) is None:
            return None

        assert isinstance(eml_match.inner_puzzle, UnknownPuzzle)
        revocation = RevocationLayer.match(unknown_puzzle=eml_match.inner_puzzle)
        if revocation is None:
            return None

        if (
            StandardBrickPuzzle.match(unknown_puzzle=revocation.hidden_puzzle) is None
            and revocation.hidden_puzzle.puzzle_hash != STANDARD_BRICK_PUZZLE_HASH
        ):
            return None

        assert isinstance(solution, bytes32)  # TODO: this is a hack, we need to flesh out the match protocol
        return VerifiedCredentialInnerPuzzle(
            eml_lineage_proof=VCLineageProof(),
            self_launcher_id=solution,
            custody_puzzle=revocation.inner_puzzle,
            proof_provider=proof_provider,
            proof_hash=proof_hash,
        )


_T_LaunchInnerPuzzle = TypeVar("_T_LaunchInnerPuzzle", bound=InnerPuzzle)


@dataclass(kw_only=True, frozen=True)
class VCLaunchResult(
    SingletonLaunchResult[VerifiedCredentialInnerPuzzle[_T_VCInnerPuzzle]],
    Generic[_T_VCInnerPuzzle],
):
    launched_singleton: VerifiedCredential[_T_VCInnerPuzzle]


@dataclass(kw_only=True, frozen=True)
class VerifiedCredential(Singleton[VerifiedCredentialInnerPuzzle[_T_VCInnerPuzzle]], Generic[_T_VCInnerPuzzle]):
    """
    This class serves as the main driver for the entire VC puzzle stack. Given the information below, it can sync and
    spend VerifiedCredentials in any specified manner. Trying to sync from a spend that this class did not create will
    likely result in an error.
    """

    @classmethod
    def is_vc(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> bool:
        """
        Stricter than SingletonPuzzle.match: only matches VC eve launchers and fully formed VC singleton puzzles.
        """
        singleton_match = SingletonPuzzle.match(unknown_puzzle=unknown_puzzle)
        if singleton_match is None:
            return False

        assert isinstance(singleton_match.inner_puzzle, UnknownPuzzle)

        vc_inner = VerifiedCredentialInnerPuzzle.match(
            unknown_puzzle=singleton_match.inner_puzzle, solution=singleton_match.launcher_id
        )
        if vc_inner is None:
            return False

        return True

    @classmethod
    def launch_vc(
        cls,
        origin_coins: list[Coin],
        provider_id: bytes32,
        new_inner_puzzle: _T_LaunchInnerPuzzle,
        memos: list[bytes],
        fee: uint64 = uint64(0),
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> VCLaunchResult[_T_LaunchInnerPuzzle]:
        """
        Launch a VC.

        origin_coins: A set of XCH coins that will be used to fund the spend. Coins of any amount > 1 can be used and
        change will automatically go back to the first coin's puzzle hash.
        provider_id: The DID of the proof provider (the entity who is responsible for adding/removing proofs to the vc)
        new_inner_puzzle_hash: the innermost puzzle hash once the VC is created
        memos: The memos to use on the payment to the singleton

        Returns a delegated puzzle to run (with any solution), a list of spends to push with the origin transaction,
        and an instance of this class representing the expected state after all relevant spends have been pushed and
        confirmed.
        """
        launch_result = cls.launch(
            origin_coin=origin_coins[0],
            launch_info=SingletonLaunchInfo(desired_inner_puzzle=OWNERSHIP_LAYER_LAUNCHER, key_value_hints={}),
        )
        eml_lineage_proof = VCLineageProof(
            parent_name=launch_result.launched_singleton.coin.parent_coin_info, amount=uint64(1)
        )
        target_vc_puzzle = SingletonPuzzle(
            launcher_id=launch_result.launched_singleton.launcher_id,
            inner_puzzle=VerifiedCredentialInnerPuzzle(
                eml_lineage_proof=eml_lineage_proof,
                self_launcher_id=launch_result.launched_singleton.launcher_id,
                custody_puzzle=new_inner_puzzle,
                proof_provider=provider_id,
                proof_hash=None,
            ),
        )

        # Create the final puzzle for the second launch
        launch_dpuz = P2Conditions(
            conditions=[
                CreateCoin(
                    puzzle_hash=target_vc_puzzle.inner_puzzle.revocation_layer.puzzle_hash,
                    amount=uint64(1),
                    memos=memos,
                ),
                UnknownCondition(
                    opcode=Program.to(1),
                    args=[Program.to(target_vc_puzzle.inner_puzzle.custody_puzzle.puzzle_hash)],
                ),
                UnknownCondition(
                    opcode=Program.to(-10),
                    args=[
                        Program.to(provider_id),
                        Program.to(target_vc_puzzle.inner_puzzle.transfer_program.puzzle_hash),
                    ],
                ),
            ]
        )
        second_launcher_solution = ExigentMetadataLayerSolution(
            inner_solution=UnknownSolution(solution=Program.to([launch_dpuz.puzzle, None]))
        )
        create_launcher_conditions = [
            CreateCoin(
                puzzle_hash=origin_coins[0].puzzle_hash,
                amount=uint64(sum(c.amount for c in origin_coins) - fee - 1),
            ),
            ReserveFee(amount=fee),
            AssertCoinAnnouncement(
                asserted_id=launch_result.launched_singleton.coin.name(), asserted_msg=launch_dpuz.puzzle_hash
            ),
            *extra_conditions,
        ]

        return VCLaunchResult(
            necessary_conditions=[*launch_result.necessary_conditions, *create_launcher_conditions],
            necessary_spends=[
                *launch_result.necessary_spends,
                launch_result.launched_singleton.spend(inner_solution=second_launcher_solution),
            ],
            launched_singleton=VerifiedCredential(
                coin=Coin(launch_result.launched_singleton.coin.name(), target_vc_puzzle.puzzle_hash, uint64(1)),
                launcher_id=launch_result.launched_singleton.launcher_id,
                lineage_proof=LineageProof(
                    parent_name=launch_result.launched_singleton.coin.parent_coin_info,
                    inner_puzzle_hash=OWNERSHIP_LAYER_LAUNCHER_HASH,
                    amount=uint64(1),
                ),
                inner_puzzle=target_vc_puzzle.inner_puzzle,
            ),
        )

    @classmethod
    def get_next_from_coin_spend(cls, parent_spend: CoinSpend) -> VerifiedCredential[UnknownPuzzle]:
        """
        Given a coin spend, this will return the next VC that was create as an output of that spend. This is the main
        method to use when syncing. If a spend has been identified as having a VC puzzle reveal, running this method
        on that spend should succeed unless the spend in question was the result of a provider using the backdoor to
        revoke the credential.
        """
        coin: Coin = next(c for c in compute_additions(parent_spend) if c.amount % 2 == 1)

        # BEGIN CODE
        parent_coin: Coin = parent_spend.coin
        solution = Program.from_serialized(parent_spend.solution)

        singleton: UncurriedPuzzle = uncurry_puzzle(parent_spend.puzzle_reveal)
        launcher_id: bytes32 = bytes32(singleton.args.at("frf").as_atom())
        layer_below_singleton: Program = singleton.args.at("rf")
        singleton_lineage_proof: LineageProof = LineageProof(
            parent_name=parent_coin.parent_coin_info,
            inner_puzzle_hash=layer_below_singleton.get_tree_hash(),
            amount=uint64(parent_coin.amount),
        )
        if layer_below_singleton == OWNERSHIP_LAYER_LAUNCHER.puzzle:
            proof_hash: bytes32 | None = None
            eml_lineage_proof: VCLineageProof = VCLineageProof(
                parent_name=parent_coin.parent_coin_info, amount=uint64(parent_coin.amount)
            )
            # See what conditions were output by the launcher dpuz and dsol
            dpuz: Program = solution.at("rrf").at("f").at("f")
            dsol: Program = solution.at("rrf").at("f").at("rf")

            conditions: list[Program] = list(dpuz.run(dsol).as_iter())
            remark_condition: Program = next(c for c in conditions if c.at("f").as_int() == 1)
            inner_puzzle_hash = bytes32(remark_condition.at("rf").as_atom())
            magic_condition: Program = next(c for c in conditions if c.at("f").as_int() == -10)
            proof_provider = bytes32(magic_condition.at("rf").as_atom())
        else:
            metadata_layer: UncurriedPuzzle = uncurry_puzzle(layer_below_singleton)

            # Dig to find the inner puzzle / inner solution and extract next inner puzhash and proof hash
            inner_puzzle: Program = solution.at("rrf").at("f").at("rf")
            inner_solution: Program = solution.at("rrf").at("f").at("rrf")
            conditions = list(inner_puzzle.run(inner_solution).as_iter())
            new_singleton_condition: Program = next(
                c for c in conditions if c.at("f").as_int() == 51 and c.at("rrf").as_int() % 2 != 0
            )
            inner_puzzle_hash = bytes32(new_singleton_condition.at("rf").as_atom())
            magic_condition = next(c for c in conditions if c.at("f").as_int() == -10)
            if magic_condition.at("rrrf") == Program.NIL:
                proof_hash_as_prog: Program = metadata_layer.args.at("rfr")
            elif magic_condition.at("rrrf").atom is not None:
                raise ValueError("Specified VC was cleared")
            else:
                proof_hash_as_prog = magic_condition.at("rrrfrrf")

            proof_hash = None if proof_hash_as_prog == Program.NIL else bytes32(proof_hash_as_prog.as_atom())

            proof_provider = bytes32(metadata_layer.args.at("rff").as_atom())

            parent_proof_hash: bytes32 = metadata_layer.args.at("rf").get_tree_hash()
            eml_lineage_proof = VCLineageProof(
                parent_name=parent_coin.parent_coin_info,
                inner_puzzle_hash=RevocationLayer(
                    hidden_puzzle=UnknownPuzzle(known_puzzle_hash=STANDARD_BRICK_PUZZLE_HASH),
                    inner_puzzle=UnknownPuzzle(
                        known_puzzle_hash=bytes32(
                            uncurry_puzzle(metadata_layer.args.at("rrrrf")).args.at("rrf").as_atom()
                        )
                    ),
                ).puzzle_hash,
                amount=uint64(parent_coin.amount),
                parent_proof_hash=None if parent_proof_hash == Program.NIL else parent_proof_hash,
            )

        new_vc = VerifiedCredential(
            coin=coin,
            lineage_proof=singleton_lineage_proof,
            launcher_id=launcher_id,
            inner_puzzle=VerifiedCredentialInnerPuzzle(
                eml_lineage_proof=eml_lineage_proof,
                self_launcher_id=launcher_id,
                custody_puzzle=UnknownPuzzle(known_puzzle_hash=inner_puzzle_hash),
                proof_provider=proof_provider,
                proof_hash=proof_hash,
            ),
        )
        if new_vc.puzzle_hash != new_vc.coin.puzzle_hash:
            raise ValueError("Error getting new VC from coin spend, probably the child singleton is not a VC")

        return new_vc

    ####################################################################################################################
    # The methods in this section are useful for spending an existing VC
    def magic_condition_for_new_proofs(
        self,
        new_proof_hash: bytes32 | None,
        provider_innerpuzhash: bytes32,
    ) -> MagicTPCondition:
        """
        Returns the 'magic' condition that can update the metadata with a new proof hash. Returning this condition from
        the inner puzzle will require a corresponding announcement from the provider DID authorizing that proof hash
        change.
        """
        return MagicTPCondition(
            eml_lineage_proof=self.inner_puzzle.eml_lineage_proof,
            launcher_id=self.launcher_id,
            tp_solution=DidTpSolution(
                provider_innerpuzhash=provider_innerpuzhash,
                my_coin_id=self.coin.name(),
                new_metadata=Program.to(new_proof_hash),
                # TP update is not allowed because then the singleton will leave the VC protocol
                new_transfer_program=None,
            ).as_program(),
        )

    def standard_magic_condition(self) -> MagicTPCondition:
        """
        Returns the standard magic condition that needs to be returned to the metadata layer. Returning this condition
        from the inner puzzle will leave the proof hash and transfer program the same.
        """
        return MagicTPCondition(
            eml_lineage_proof=self.inner_puzzle.eml_lineage_proof,
            launcher_id=self.launcher_id,
            tp_solution=None,
        )

    def magic_condition_for_self_revoke(self) -> MagicTPCondition:
        return MagicTPCondition(
            eml_lineage_proof=self.inner_puzzle.eml_lineage_proof,
            launcher_id=self.launcher_id,
            tp_solution=Program.to(ACS_TRANSFER_PROGRAM.get_tree_hash()),
        )

    def wrap_inner_with_backdoor(self) -> Program:
        return self.inner_puzzle.revocation_layer.puzzle

    def do_spend(
        self,
        inner_solution: Solution,
        new_proof_hash: bytes32 | None = None,
    ) -> tuple[CreatePuzzleAnnouncement | None, CoinSpend, VerifiedCredential[UnknownPuzzle]]:
        """
        Given an inner puzzle reveal and solution, spend the VC (potentially updating the proofs in the process).
        Note that the inner puzzle is already expected to output the 'magic' condition (which can be created above).

        Returns potentially the puzzle announcement the spend will expect from the provider DID, the spend of the VC,
        and the expected class representation of the new VC after the spend is pushed and confirmed.
        """

        if new_proof_hash is not None:
            expected_announcement: CreatePuzzleAnnouncement | None = CreatePuzzleAnnouncement(
                std_hash(
                    self.coin.name()
                    + Program.to(new_proof_hash).get_tree_hash()
                    + b""  # TP update is banned because singleton will leave the VC protocol
                )
            )
        else:
            expected_announcement = None

        spend, next_singleton = self.action_spend(
            inner_solution=ExigentMetadataLayerSolution(
                inner_solution=RevocationLayerSolution(
                    puzzle_reveal=self.inner_puzzle.custody_puzzle,
                    inner_solution=inner_solution,
                )
            )
        )

        new_singleton_create_coin = new_create_coin_from_inner_puzzle_and_solution(
            self.inner_puzzle.custody_puzzle, inner_solution
        )

        return (
            expected_announcement,
            spend,
            VerifiedCredential(
                coin=next_singleton.coin,
                launcher_id=next_singleton.launcher_id,
                lineage_proof=next_singleton.lineage_proof,
                inner_puzzle=VerifiedCredentialInnerPuzzle(
                    eml_lineage_proof=VCLineageProof(
                        self.coin.parent_coin_info,
                        self.inner_puzzle.revocation_layer.puzzle_hash,
                        self.coin.amount,
                        Program.to((self.inner_puzzle.proof_provider, self.inner_puzzle.proof_hash)).get_tree_hash(),
                    ),
                    self_launcher_id=self.launcher_id,
                    proof_provider=self.inner_puzzle.proof_provider,
                    proof_hash=self.inner_puzzle.proof_hash if new_proof_hash is None else new_proof_hash,
                    custody_puzzle=UnknownPuzzle(known_puzzle_hash=new_singleton_create_coin.puzzle_hash),
                ),
            ),
        )

    def activate_backdoor(
        self, provider_innerpuzhash: bytes32, announcement_nonce: bytes32 | None = None
    ) -> tuple[CreatePuzzleAnnouncement, CoinSpend]:
        """
        Activates the backdoor in the VC to revoke the credentials and remove the provider's DID.

        Returns the announcement we expect from the provider's DID authorizing this, and the spend of the VC.
        Sync attempts by this class on spends generated by this method are expected to fail. This could be improved in
        the future with a separate type/state of VC that is revoked, but perfectly useful as a singleton.
        """

        expected_announcement: CreatePuzzleAnnouncement = CreatePuzzleAnnouncement(
            std_hash(self.coin.name() + Program.NIL.get_tree_hash() + ACS_TRANSFER_PROGRAM.get_tree_hash())
        )

        spend = self.spend(
            inner_solution=ExigentMetadataLayerSolution(
                inner_solution=RevocationLayerSolution(
                    puzzle_reveal=StandardBrickPuzzle(),
                    inner_solution=StandardBrickPuzzleSolution(
                        launcher_id=self.launcher_id,
                        metadata_hash=Program.to(
                            (self.inner_puzzle.proof_provider, self.inner_puzzle.proof_hash)
                        ).get_tree_hash(),
                        tp_hash=self.inner_puzzle.transfer_program.puzzle_hash,
                        inner_puzzle_hash=self.inner_puzzle.custody_puzzle.puzzle_hash,
                        amount=uint64(self.coin.amount),
                        eml_lineage_proof=self.inner_puzzle.eml_lineage_proof,
                        provider_innerpuzhash=provider_innerpuzhash,
                        coin_id=self.coin.name(),
                        announcement_nonce=announcement_nonce,
                    ),
                    hidden=True,
                )
            )
        )

        return (
            expected_announcement,
            spend,
        )

    def as_streamable(self) -> StreamableVerifiedCredential:
        return StreamableVerifiedCredential(
            coin=self.coin,
            singleton_lineage_proof=self.lineage_proof,
            eml_lineage_proof=self.inner_puzzle.eml_lineage_proof,
            launcher_id=self.launcher_id,
            inner_puzzle_hash=self.inner_puzzle.custody_puzzle.puzzle_hash,
            proof_provider=self.inner_puzzle.proof_provider,
            proof_hash=self.inner_puzzle.proof_hash,
        )

    @classmethod
    def from_streamable(cls, streamable_object: StreamableVerifiedCredential) -> VerifiedCredential[UnknownPuzzle]:
        return VerifiedCredential(
            coin=streamable_object.coin,
            launcher_id=streamable_object.launcher_id,
            lineage_proof=streamable_object.singleton_lineage_proof,
            inner_puzzle=VerifiedCredentialInnerPuzzle(
                eml_lineage_proof=streamable_object.eml_lineage_proof,
                self_launcher_id=streamable_object.launcher_id,
                custody_puzzle=UnknownPuzzle(known_puzzle_hash=streamable_object.inner_puzzle_hash),
                proof_provider=streamable_object.proof_provider,
                proof_hash=streamable_object.proof_hash,
            ),
        )


# This class is sort of unparadigmatic as an outer puzzle.
# It lives somewhere between outer puzzle and inner puzzle, but the most convenient
# way to present it in this wallet is as an outer puzzle.
# This may lead to some peculiarities if use cases are to be expanded beyond simply using this
# inside of a CAT.
@dataclass(frozen=True)
class RevocationOuterPuzzle:
    def match(self, puzzle: UncurriedPuzzle) -> PuzzleInfo | None:
        revocation_layer_match = RevocationLayer.match(
            unknown_puzzle=UnknownPuzzle(known_puzzle=puzzle.mod.curry(*puzzle.args.as_iter()))
        )
        if revocation_layer_match is None:
            return None
        constructor_dict: dict[str, Any] = {
            "type": "revocation layer",
            "hidden_puzzle_hash": "0x" + revocation_layer_match.hidden_puzzle.puzzle_hash.hex(),
        }
        return PuzzleInfo(constructor_dict)

    def get_inner_puzzle(
        self, constructor: PuzzleInfo, puzzle_reveal: UncurriedPuzzle, solution: Program | None = None
    ) -> Program | None:
        if solution is None:
            raise ValueError("Cannot get_inner_puzzle of revocation layer without solution")

        return solution.at("rf")

    def get_inner_solution(self, constructor: PuzzleInfo, solution: Program) -> Program | None:
        return solution.at("rrf")

    def asset_id(self, constructor: PuzzleInfo) -> bytes32 | None:
        return bytes32(constructor["hidden_puzzle_hash"])

    def construct(self, constructor: PuzzleInfo, inner_puzzle: Program) -> Program:
        return RevocationLayer(
            hidden_puzzle=UnknownPuzzle(known_puzzle_hash=constructor["hidden_puzzle_hash"]),
            inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle),
        ).puzzle

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        return RevocationLayerSolution(  # deliberately no support for hidden puzzle spends
            puzzle_reveal=UnknownPuzzle(known_puzzle=inner_puzzle),
            inner_solution=UnknownSolution(solution=inner_solution),
        ).as_program()


################################
# Backward-compatible helpers  #
################################


def create_did_tp(
    singleton_mod_hash: bytes32 | None = None,
    singleton_launcher_hash: bytes32 | None = None,
) -> Program:
    if singleton_mod_hash is None and singleton_launcher_hash is None:
        return DidTransferProgram().puzzle
    assert singleton_mod_hash is not None and singleton_launcher_hash is not None
    return EML_DID_TP.curry(singleton_mod_hash, singleton_launcher_hash)


def create_eml_covenant_morpher(transfer_program_hash: bytes32) -> Program:
    return EmlCovenantMorpher(transfer_program=UnknownPuzzle(known_puzzle_hash=transfer_program_hash)).puzzle


def create_revocation_layer(hidden_puzzle_hash: bytes32, inner_puzzle_hash: bytes32) -> Program:
    return RevocationLayer(
        hidden_puzzle=UnknownPuzzle(known_puzzle_hash=hidden_puzzle_hash),
        inner_puzzle=UnknownPuzzle(known_puzzle_hash=inner_puzzle_hash),
    ).puzzle


def match_revocation_layer(uncurried_puzzle: UncurriedPuzzle) -> tuple[bytes32, bytes32] | None:
    if uncurried_puzzle.mod != REVOCATION_LAYER:
        return None
    return bytes32(uncurried_puzzle.args.at("rf").as_atom()), bytes32(uncurried_puzzle.args.at("rrf").as_atom())


def solve_revocation_layer(puzzle_reveal: Program, inner_solution: Program, hidden: bool = False) -> Program:
    return RevocationLayerSolution(
        puzzle_reveal=UnknownPuzzle(known_puzzle=puzzle_reveal),
        inner_solution=UnknownSolution(solution=inner_solution),
        hidden=hidden,
    ).as_program()


def construct_exigent_metadata_layer(
    metadata: Program | None, transfer_program: Program, inner_puzzle: Program
) -> Program:
    return ExigentMetadataLayer(
        metadata=metadata,
        transfer_program=UnknownPuzzle(known_puzzle=transfer_program),
        inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle),
    ).puzzle
