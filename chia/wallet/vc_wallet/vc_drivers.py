from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Self, TypeVar, cast, final

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
from chia.types.coin_spend import make_spend
from chia.util.hash import std_hash
from chia.util.streamable import Streamable, streamable
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    Condition,
    CreateCoin,
    CreatePuzzleAnnouncement,
    Remark,
    ReserveFee,
    UnknownCondition,
)
from chia.wallet.lineage_proof import LineageProof, LineageProofField
from chia.wallet.puzzle_drivers import PuzzleInfo, Solver
from chia.wallet.puzzles.puzzle_drivers import (
    P2Conditions,
    Puzzle,
    PuzzleBase,
    Solution,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
    SINGLETON_LAUNCHER,
    SINGLETON_LAUNCHER_HASH,
    SINGLETON_MOD,
    SINGLETON_MOD_HASH,
    generate_launcher_coin,
    puzzle_for_singleton,
    solution_for_singleton,
)
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
class StandardBrickPuzzle(PuzzleBase):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("StandardBrickPuzzle", None)

    @property
    def program(self) -> Program:
        return STANDARD_VC_REVOCATION_PUZZLE.curry(
            SINGLETON_MOD_HASH,
            Program.to(SINGLETON_LAUNCHER_HASH).get_tree_hash(),
            EXTIGENT_METADATA_LAYER_HASH,
            REVOCATION_LAYER_HASH,
            ACS_TRANSFER_PROGRAM.get_tree_hash(),
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> StandardBrickPuzzle | None:
        if unknown_puzzle.known_program is None:
            if unknown_puzzle.known_tree_hash == STANDARD_BRICK_PUZZLE_HASH:
                return StandardBrickPuzzle()
            return None
        if unknown_puzzle.mod != STANDARD_VC_REVOCATION_PUZZLE:
            return None
        return StandardBrickPuzzle()


# Standard brick puzzle uses the mods above
STANDARD_BRICK_PUZZLE: Program = StandardBrickPuzzle().program
STANDARD_BRICK_PUZZLE_HASH: bytes32 = STANDARD_BRICK_PUZZLE.get_tree_hash()
STANDARD_BRICK_PUZZLE_HASH_HASH: bytes32 = Program.to(STANDARD_BRICK_PUZZLE_HASH).get_tree_hash()


##################
# Covenant Layer #
##################
_T_ParentMorpher = TypeVar("_T_ParentMorpher", bound=Puzzle)
_T_CovenantPuzzle = TypeVar("_T_CovenantPuzzle", bound=Puzzle)


@dataclass(frozen=True, kw_only=True)
class CovenantLayer(PuzzleBase, Generic[_T_ParentMorpher, _T_CovenantPuzzle]):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("CovenantLayer[_T_ParentMorpher, _T_CovenantPuzzle]", None)

    initial_puzzle_hash: bytes32
    parent_morpher: _T_ParentMorpher
    inner_puzzle: _T_CovenantPuzzle

    @property
    def program(self) -> Program:
        return COVENANT_LAYER.curry(
            self.initial_puzzle_hash,
            self.parent_morpher.program,
            self.inner_puzzle.program,
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> CovenantLayer[UnknownPuzzle, UnknownPuzzle] | None:
        if unknown_puzzle.mod != COVENANT_LAYER or unknown_puzzle.curried_args is None:
            return None

        (inner_puzzle_hash_prog, parent_morpher_prog, inner_puzzle_prog) = unknown_puzzle.curried_args
        return CovenantLayer(
            initial_puzzle_hash=bytes32(inner_puzzle_hash_prog.as_atom()),
            parent_morpher=UnknownPuzzle(known_program=parent_morpher_prog),
            inner_puzzle=UnknownPuzzle(known_program=inner_puzzle_prog),
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

    @property
    def program(self) -> Program:
        return Program.to(
            [
                self.lineage_proof.to_program(),
                self.morpher_solution.program,
                self.inner_solution.program,
            ]
        )

    @classmethod
    def match(
        cls, *, unknown_solution: UnknownSolution
    ) -> CovenantLayerSolution[UnknownSolution, UnknownSolution] | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
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
class StdParentMorpher(PuzzleBase):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("StdParentMorpher", None)

    initial_puzzle_hash: bytes32

    @property
    def program(self) -> Program:
        return STD_COVENANT_PARENT_MORPHER.curry(
            STD_COVENANT_PARENT_MORPHER_HASH,
            COVENANT_LAYER_HASH,
            self.initial_puzzle_hash,
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> StdParentMorpher | None:
        if unknown_puzzle.mod != STD_COVENANT_PARENT_MORPHER or unknown_puzzle.curried_args is None:
            return None
        (_mod_hash, _covenant_layer_hash, initial_puzzle_hash_prog) = unknown_puzzle.curried_args
        return StdParentMorpher(initial_puzzle_hash=bytes32(initial_puzzle_hash_prog.as_atom()))


####################
# Covenant Adapter #
####################


_T_CovenantLayer = TypeVar("_T_CovenantLayer", bound=Puzzle)


@dataclass(frozen=True, kw_only=True)
class TransferProgramCovenantAdapter(PuzzleBase, Generic[_T_CovenantLayer]):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("TransferProgramCovenantAdapter[_T_CovenantLayer]", None)

    inner_puzzle: _T_CovenantLayer

    @property
    def program(self) -> Program:
        return EML_TP_COVENANT_ADAPTER.curry(self.inner_puzzle.program)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> TransferProgramCovenantAdapter[UnknownPuzzle] | None:
        if unknown_puzzle.mod != EML_TP_COVENANT_ADAPTER or unknown_puzzle.curried_args is None:
            return None
        (covenant_layer_prog,) = unknown_puzzle.curried_args
        return TransferProgramCovenantAdapter(inner_puzzle=UnknownPuzzle(known_program=covenant_layer_prog))


##################################
# Update w/ DID Transfer Program #
##################################


@dataclass(frozen=True, kw_only=True)
class DidTransferProgram(PuzzleBase):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("DidTransferProgram", None)

    @property
    def program(self) -> Program:
        return EML_DID_TP.curry(SINGLETON_MOD_HASH, SINGLETON_LAUNCHER_HASH)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> DidTransferProgram | None:
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

    @property
    def program(self) -> Program:
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
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
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


def create_did_tp(
    singleton_mod_hash: bytes32 = SINGLETON_MOD_HASH,
    singleton_launcher_hash: bytes32 = SINGLETON_LAUNCHER_HASH,
) -> Program:
    if singleton_mod_hash == SINGLETON_MOD_HASH and singleton_launcher_hash == SINGLETON_LAUNCHER_HASH:
        return DidTransferProgram().program
    return EML_DID_TP.curry(
        singleton_mod_hash,
        singleton_launcher_hash,
    )


EML_DID_TP_FULL_HASH = create_did_tp().get_tree_hash()


##############################
# P2 Puzzle or Hidden Puzzle #
##############################


_T_RevocationPuzzle = TypeVar("_T_RevocationPuzzle", bound=Puzzle)
_T_RevocationHiddenPuzzle = TypeVar("_T_RevocationHiddenPuzzle", bound=Puzzle)


@dataclass(frozen=True, kw_only=True)
class RevocationLayer(PuzzleBase, Generic[_T_RevocationPuzzle, _T_RevocationHiddenPuzzle]):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast(
            "RevocationLayer[_T_RevocationPuzzle, _T_RevocationHiddenPuzzle]", None
        )

    inner_puzzle: _T_RevocationPuzzle
    hidden_puzzle: _T_RevocationHiddenPuzzle

    @property
    def program(self) -> Program:
        return REVOCATION_LAYER.curry(REVOCATION_LAYER_HASH, self.hidden_puzzle.tree_hash, self.inner_puzzle.tree_hash)

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> RevocationLayer[UnknownPuzzle, UnknownPuzzle] | None:
        if unknown_puzzle.mod != REVOCATION_LAYER or unknown_puzzle.curried_args is None:
            return None
        (_mod_hash, hidden_puzzle_hash_prog, inner_puzzle_hash_prog) = unknown_puzzle.curried_args
        return RevocationLayer(
            hidden_puzzle=UnknownPuzzle(known_tree_hash=bytes32(hidden_puzzle_hash_prog.as_atom())),
            inner_puzzle=UnknownPuzzle(known_tree_hash=bytes32(inner_puzzle_hash_prog.as_atom())),
        )


_T_RevocationPuzzleReveal = TypeVar("_T_RevocationPuzzleReveal", bound=Puzzle)


@dataclass(frozen=True, kw_only=True)
class RevocationLayerSolution(Generic[_T_RevocationPuzzleReveal, _T_InnerSolution]):
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast(
            "RevocationLayerSolution[_T_RevocationPuzzleReveal, _T_InnerSolution]", None
        )

    puzzle_reveal: _T_RevocationPuzzleReveal
    inner_solution: _T_InnerSolution
    hidden: bool = False

    @property
    def program(self) -> Program:
        return Program.to(
            [
                self.hidden,
                self.puzzle_reveal.program,
                self.inner_solution.program,
            ]
        )

    @classmethod
    def match(
        cls, *, unknown_solution: UnknownSolution
    ) -> RevocationLayerSolution[UnknownPuzzle, UnknownSolution] | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
        if len(list_of_values) != 3:
            return None
        return RevocationLayerSolution(
            hidden=list_of_values[0] != Program.NIL,
            puzzle_reveal=UnknownPuzzle(known_program=list_of_values[1]),
            inner_solution=UnknownSolution(list_of_values[2]),
        )


########
# MISC #
########


_T_EmlCovenantMorpherTp = TypeVar("_T_EmlCovenantMorpherTp", bound=Puzzle)


@dataclass(frozen=True, kw_only=True)
class EmlCovenantMorpher(PuzzleBase, Generic[_T_EmlCovenantMorpherTp]):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("EmlCovenantMorpher[_T_EmlCovenantMorpherTp]", None)

    transfer_program: _T_EmlCovenantMorpherTp

    @property
    def program(self) -> Program:
        first_curry: Program = EXTIGENT_METADATA_LAYER_COVENANT_MORPHER.curry(
            COVENANT_LAYER_HASH,
            EXTIGENT_METADATA_LAYER_HASH,
            EML_TP_COVENANT_ADAPTER_HASH,
            SINGLETON_MOD_HASH,
            Program.to(SINGLETON_LAUNCHER_HASH).get_tree_hash(),
            self.transfer_program.tree_hash,
        )
        return first_curry.curry(first_curry.get_tree_hash())

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> EmlCovenantMorpher[UnknownPuzzle] | None:
        if unknown_puzzle.mod is None or unknown_puzzle.curried_args is None:
            return None
        first_curry = UnknownPuzzle(known_program=unknown_puzzle.mod)
        if first_curry.mod != EXTIGENT_METADATA_LAYER_COVENANT_MORPHER or first_curry.curried_args is None:
            return None
        curried_args = list(first_curry.curried_args)
        if len(curried_args) != 6:
            return None
        return EmlCovenantMorpher(transfer_program=UnknownPuzzle(known_tree_hash=bytes32(curried_args[5].as_atom())))


@dataclass(frozen=True, kw_only=True)
class EmlCovenantMorpherSolution:
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast("EmlCovenantMorpherSolution", None)

    parent_proof_hash: bytes32 | None
    launcher_id: bytes32

    @property
    def program(self) -> Program:
        return Program.to([self.parent_proof_hash, self.launcher_id])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> EmlCovenantMorpherSolution | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
        if len(list_of_values) != 2:
            return None
        parent_proof_hash_prog = list_of_values[0]
        return cls(
            parent_proof_hash=None
            if parent_proof_hash_prog == Program.NIL
            else bytes32(parent_proof_hash_prog.as_atom()),
            launcher_id=bytes32(list_of_values[1].as_atom()),
        )


_T_TransferProgram = TypeVar("_T_TransferProgram", bound=Puzzle)
_T_EMLPuzzle = TypeVar("_T_EMLPuzzle", bound=Puzzle)


@dataclass(frozen=True, kw_only=True)
class ExigentMetadataLayer(PuzzleBase, Generic[_T_TransferProgram, _T_EMLPuzzle]):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("ExigentMetadataLayer[_T_TransferProgram, _T_EMLPuzzle]", None)

    metadata: Program | None
    transfer_program: _T_TransferProgram
    inner_puzzle: _T_EMLPuzzle

    @property
    def program(self) -> Program:
        return EXTIGENT_METADATA_LAYER.curry(
            EXTIGENT_METADATA_LAYER_HASH,
            self.metadata,
            self.transfer_program.program,
            self.transfer_program.tree_hash,
            self.inner_puzzle.program,
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> ExigentMetadataLayer[UnknownPuzzle, UnknownPuzzle] | None:
        if unknown_puzzle.mod != EXTIGENT_METADATA_LAYER or unknown_puzzle.curried_args is None:
            return None
        (_mod_hash, metadata_prog, transfer_program_prog, _tp_hash, inner_puzzle_prog) = unknown_puzzle.curried_args
        return ExigentMetadataLayer(
            metadata=None if metadata_prog == Program.NIL else metadata_prog,
            transfer_program=UnknownPuzzle(known_program=transfer_program_prog),
            inner_puzzle=UnknownPuzzle(known_program=inner_puzzle_prog),
        )


@dataclass(frozen=True, kw_only=True)
class ExigentMetadataLayerSolution(Generic[_T_InnerSolution]):
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast("ExigentMetadataLayerSolution[_T_InnerSolution]", None)

    inner_solution: _T_InnerSolution

    @property
    def program(self) -> Program:
        return Program.to([self.inner_solution.program])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> ExigentMetadataLayerSolution[UnknownSolution] | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
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

    @property
    def program(self) -> Program:
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
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
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
GUARANTEED_NIL_TP = UnknownPuzzle(known_program=Program.fromhex("ff04ffff04ff13ff8080ffff04ff2bffff01ff80808080"))
OWNERSHIP_LAYER_LAUNCHER = ExigentMetadataLayer(
    metadata=None,
    transfer_program=GUARANTEED_NIL_TP,
    inner_puzzle=UnknownPuzzle(known_program=P2_ANNOUNCED_DELEGATED_PUZZLE),
)
GUARANTEED_NIL_TP_HASH: bytes32 = GUARANTEED_NIL_TP.tree_hash
OWNERSHIP_LAYER_LAUNCHER_HASH = OWNERSHIP_LAYER_LAUNCHER.tree_hash


########################
# Verified Credentials #
########################


_T_VCPuzzle = TypeVar("_T_VCPuzzle", bound=Puzzle)


@dataclass(kw_only=True, frozen=True)
class VerifiedCredentialInnerPuzzle(PuzzleBase, Generic[_T_VCPuzzle]):
    """
    PuzzleBase driver for the VC inner puzzle stack (EML -> revocation -> custody).
    """

    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("VerifiedCredentialInnerPuzzle[_T_VCPuzzle]", None)

    eml_lineage_proof: VCLineageProof
    self_launcher_id: bytes32
    custody_puzzle: _T_VCPuzzle
    proof_provider: bytes32
    proof_hash: bytes32 | None

    @property
    def construction(
        self,
    ) -> ExigentMetadataLayer[
        TransferProgramCovenantAdapter[CovenantLayer[EmlCovenantMorpher[DidTransferProgram], DidTransferProgram]],
        RevocationLayer[_T_VCPuzzle, StandardBrickPuzzle],
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
                initial_puzzle_hash=puzzle_for_singleton(
                    self.self_launcher_id, OWNERSHIP_LAYER_LAUNCHER.program
                ).get_tree_hash(),
                parent_morpher=EmlCovenantMorpher(transfer_program=DidTransferProgram()),
                inner_puzzle=DidTransferProgram(),
            )
        )

    @property
    def revocation_layer(self) -> RevocationLayer[_T_VCPuzzle, StandardBrickPuzzle]:
        return RevocationLayer(inner_puzzle=self.custody_puzzle, hidden_puzzle=StandardBrickPuzzle())

    def wrap_inner_with_backdoor(self) -> Program:
        return self.revocation_layer.program

    @property
    def program(self) -> Program:
        return self.construction.program

    @property
    def tree_hash_optimized(self) -> bytes32:
        return self.construction.tree_hash

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> VerifiedCredentialInnerPuzzle[UnknownPuzzle] | None:
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
            and revocation.hidden_puzzle.tree_hash != STANDARD_BRICK_PUZZLE_HASH
        ):
            return None

        return VerifiedCredentialInnerPuzzle(
            eml_lineage_proof=VCLineageProof(),
            self_launcher_id=bytes32.zeros,
            custody_puzzle=revocation.inner_puzzle,
            proof_provider=proof_provider,
            proof_hash=proof_hash,
        )


@streamable
@dataclass(frozen=True)
class VerifiedCredential(Streamable):
    """
    This class serves as the main driver for the entire VC puzzle stack. Given the information below, it can sync and
    spend VerifiedCredentials in any specified manner. Trying to sync from a spend that this class did not create will
    likely result in an error.
    """

    coin: Coin
    singleton_lineage_proof: LineageProof
    eml_lineage_proof: VCLineageProof
    launcher_id: bytes32
    inner_puzzle_hash: bytes32
    proof_provider: bytes32
    proof_hash: bytes32 | None

    @property
    def as_inner_puzzle(self) -> VerifiedCredentialInnerPuzzle[UnknownPuzzle]:
        return VerifiedCredentialInnerPuzzle(
            eml_lineage_proof=self.eml_lineage_proof,
            self_launcher_id=self.launcher_id,
            custody_puzzle=UnknownPuzzle(known_tree_hash=self.inner_puzzle_hash),
            proof_provider=self.proof_provider,
            proof_hash=self.proof_hash,
        )

    @classmethod
    def launch(
        cls,
        origin_coins: list[Coin],
        provider_id: bytes32,
        new_inner_puzzle_hash: bytes32,
        memos: list[bytes],
        fee: uint64 = uint64(0),
        extra_conditions: tuple[Condition, ...] = tuple(),
    ) -> tuple[list[Program], list[CoinSpend], Self]:
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
        origin_coin = origin_coins[0]
        launcher_coin: Coin = generate_launcher_coin(origin_coin, uint64(1))

        # Create the second puzzle for the first launch
        curried_eve_singleton: Program = puzzle_for_singleton(
            launcher_coin.name(),
            OWNERSHIP_LAYER_LAUNCHER.program,
        )
        curried_eve_singleton_hash: bytes32 = curried_eve_singleton.get_tree_hash()
        launcher_solution = Program.to([curried_eve_singleton_hash, uint64(1), None])

        # Create the final puzzle for the second launch
        second_launcher_coin: Coin = Coin(
            launcher_coin.name(),
            curried_eve_singleton_hash,
            uint64(1),
        )
        target_vc_inner = VerifiedCredentialInnerPuzzle(
            eml_lineage_proof=VCLineageProof(parent_name=second_launcher_coin.parent_coin_info, amount=uint64(1)),
            self_launcher_id=launcher_coin.name(),
            custody_puzzle=UnknownPuzzle(known_tree_hash=new_inner_puzzle_hash),
            proof_provider=provider_id,
            proof_hash=None,
        )
        wrapped_inner_puzzle_hash: bytes32 = target_vc_inner.revocation_layer.tree_hash
        metadata_layer_hash: bytes32 = target_vc_inner.tree_hash
        transfer_program_hash: bytes32 = target_vc_inner.transfer_program.tree_hash
        curried_singleton_hash: bytes32 = puzzle_for_singleton(
            launcher_coin.name(),
            metadata_layer_hash,  # type: ignore[arg-type]
        ).get_tree_hash_precalc(metadata_layer_hash)
        launch_dpuz: Program = P2Conditions(
            conditions=[
                CreateCoin(wrapped_inner_puzzle_hash, uint64(1), memos),
                Remark(rest=Program.to([new_inner_puzzle_hash])),
                UnknownCondition(
                    opcode=Program.to(-10),
                    args=[Program.to(provider_id), Program.to(transfer_program_hash)],
                ),
            ],
        ).program
        second_launcher_solution = Program.to([launch_dpuz, None])
        create_launcher_conditions = [
            CreateCoin(SINGLETON_LAUNCHER_HASH, uint64(1)),
            CreateCoin(origin_coin.puzzle_hash, uint64(sum(c.amount for c in origin_coins) - fee - 1)),
            ReserveFee(fee),
            AssertCoinAnnouncement(asserted_msg=launcher_solution.get_tree_hash(), asserted_id=launcher_coin.name()),
            (
                second_launcher_announcement := AssertCoinAnnouncement(
                    asserted_msg=launch_dpuz.get_tree_hash(), asserted_id=second_launcher_coin.name()
                )
            ),
            *[cond for cond in extra_conditions],
        ]

        primary_dpuz: Program = P2Conditions(conditions=create_launcher_conditions).program
        additional_dpuzs: list[Program] = [P2Conditions(conditions=[second_launcher_announcement]).program]
        return (
            [primary_dpuz, *additional_dpuzs],
            [
                make_spend(
                    launcher_coin,
                    SINGLETON_LAUNCHER,
                    launcher_solution,
                ),
                make_spend(
                    second_launcher_coin,
                    curried_eve_singleton,
                    solution_for_singleton(
                        LineageProof(parent_name=launcher_coin.parent_coin_info, amount=uint64(1)),
                        uint64(1),
                        Program.to(
                            [
                                second_launcher_solution,
                            ]
                        ),
                    ),
                ),
            ],
            cls(
                Coin(second_launcher_coin.name(), curried_singleton_hash, uint64(1)),
                LineageProof(
                    parent_name=second_launcher_coin.parent_coin_info,
                    inner_puzzle_hash=OWNERSHIP_LAYER_LAUNCHER_HASH,
                    amount=uint64(1),
                ),
                VCLineageProof(parent_name=second_launcher_coin.parent_coin_info, amount=uint64(1)),
                launcher_coin.name(),
                new_inner_puzzle_hash,
                provider_id,
                None,
            ),
        )

    ####################################################################################################################
    # The methods in this section give insight into the structure of the puzzle stack that is considered a "VC"
    def construct_puzzle(self) -> Program:
        return puzzle_for_singleton(
            self.launcher_id,
            self.construct_exigent_metadata_layer(),
        )

    def construct_exigent_metadata_layer(self) -> Program:
        return self.as_inner_puzzle.program

    def wrap_inner_with_backdoor(self) -> Program:
        return self.as_inner_puzzle.wrap_inner_with_backdoor()

    def hidden_puzzle(self) -> Program:
        return STANDARD_BRICK_PUZZLE

    ####################################################################################################################

    @staticmethod
    def is_vc(puzzle_reveal: UnknownPuzzle) -> tuple[bool, str]:
        """
        This takes an (uncurried) puzzle reveal and returns a boolean for whether the puzzle is a VC and an error
        message for if the puzzle is a mismatch. Returns True for VC launcher spends.
        """
        if puzzle_reveal.mod != SINGLETON_MOD or puzzle_reveal.curried_args is None:
            return False, "top most layer is not a singleton"
        layer_below_singleton: UnknownPuzzle = UnknownPuzzle(known_program=puzzle_reveal.curried_args[1])
        if layer_below_singleton.mod != EXTIGENT_METADATA_LAYER or layer_below_singleton.curried_args is None:
            return False, "layer below singleton is not an exigent metadata layer"

        # Need to validate both transfer program...
        full_transfer_program_as_prog: Program = layer_below_singleton.curried_args[2]
        full_transfer_program: UnknownPuzzle = UnknownPuzzle(known_program=full_transfer_program_as_prog)
        if full_transfer_program.mod != EML_TP_COVENANT_ADAPTER:
            # This is the first spot we'll run into trouble if we're examining a VC being launched
            # Break off to that logic here
            if full_transfer_program_as_prog == GUARANTEED_NIL_TP.program:
                if layer_below_singleton.curried_args[4] != P2_ANNOUNCED_DELEGATED_PUZZLE:
                    return (
                        False,
                        "tp indicates VC is launching, but it does not have the correct inner puzzle",
                    )  # pragma: no cover
                else:
                    return True, ""
            else:
                return False, "top layer of transfer program is not a covenant layer adapter"  # pragma: no cover
        if VerifiedCredentialInnerPuzzle.match(unknown_puzzle=layer_below_singleton) is not None:
            return True, ""
        assert full_transfer_program.curried_args is not None
        adapted_transfer_program: UnknownPuzzle = UnknownPuzzle(known_program=full_transfer_program.curried_args[0])
        if adapted_transfer_program.mod != COVENANT_LAYER or adapted_transfer_program.curried_args is None:
            return (
                False,
                "transfer program is adapted to covenant layer, but covenant layer did not follow",
            )  # pragma: no cover
        morpher: UnknownPuzzle = UnknownPuzzle(known_program=adapted_transfer_program.curried_args[1])
        if (
            morpher.mod is None
            or UnknownPuzzle(known_program=morpher.mod).mod != EXTIGENT_METADATA_LAYER_COVENANT_MORPHER
        ):
            return (
                False,
                "covenant for exigent metadata layer does not match the one expected for VCs",
            )  # pragma: no cover
        if UnknownPuzzle(known_program=adapted_transfer_program.curried_args[2]).mod != EML_DID_TP:
            return (
                False,
                "transfer program for exigent metadata layer was not the standard VC transfer program",
            )  # pragma: no cover

        # ...and layer below EML
        layer_below_eml: UnknownPuzzle = UnknownPuzzle(known_program=layer_below_singleton.curried_args[4])
        if layer_below_eml.mod != REVOCATION_LAYER or layer_below_eml.curried_args is None:
            return False, "VC did not have a provider backdoor"  # pragma: no cover
        hidden_puzzle_hash = bytes32(layer_below_eml.curried_args[1].as_atom())
        if hidden_puzzle_hash != STANDARD_BRICK_PUZZLE_HASH:
            return (
                False,
                "VC did not have the standard method to brick in its backdoor hidden puzzle slot",
            )  # pragma: no cover

        return True, ""

    @classmethod
    def get_next_from_coin_spend(cls, parent_spend: CoinSpend) -> Self:
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

        singleton: UnknownPuzzle = UnknownPuzzle(known_program=parent_spend.puzzle_reveal)
        assert singleton.curried_args is not None
        launcher_id: bytes32 = bytes32(singleton.curried_args[0].at("rf").as_atom())
        layer_below_singleton: Program = singleton.curried_args[1]
        singleton_lineage_proof: LineageProof = LineageProof(
            parent_name=parent_coin.parent_coin_info,
            inner_puzzle_hash=layer_below_singleton.get_tree_hash(),
            amount=uint64(parent_coin.amount),
        )
        if layer_below_singleton == OWNERSHIP_LAYER_LAUNCHER.program:
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
            metadata_layer: UnknownPuzzle = UnknownPuzzle(known_program=layer_below_singleton)

            # Dig to find the inner puzzle / inner solution and extract next inner puzhash and proof hash
            inner_puzzle: Program = solution.at("rrf").at("f").at("rf")
            inner_solution: Program = solution.at("rrf").at("f").at("rrf")
            conditions = list(inner_puzzle.run(inner_solution).as_iter())
            new_singleton_condition: Program = next(
                c for c in conditions if c.at("f").as_int() == 51 and c.at("rrf").as_int() % 2 != 0
            )
            inner_puzzle_hash = bytes32(new_singleton_condition.at("rf").as_atom())
            magic_condition = next(c for c in conditions if c.at("f").as_int() == -10)
            assert metadata_layer.curried_args is not None
            if magic_condition.at("rrrf") == Program.NIL:
                proof_hash_as_prog: Program = metadata_layer.curried_args[1].at("r")
            elif magic_condition.at("rrrf").atom is not None:
                raise ValueError("Specified VC was cleared")
            else:
                proof_hash_as_prog = magic_condition.at("rrrfrrf")

            proof_hash = None if proof_hash_as_prog == Program.NIL else bytes32(proof_hash_as_prog.as_atom())

            proof_provider = bytes32(metadata_layer.curried_args[1].at("f").as_atom())

            parent_proof_hash: bytes32 = metadata_layer.curried_args[1].get_tree_hash()
            revocation_layer = UnknownPuzzle(known_program=metadata_layer.curried_args[4])
            assert revocation_layer.curried_args is not None
            eml_lineage_proof = VCLineageProof(
                parent_name=parent_coin.parent_coin_info,
                inner_puzzle_hash=RevocationLayer(
                    hidden_puzzle=UnknownPuzzle(known_tree_hash=STANDARD_BRICK_PUZZLE_HASH),
                    inner_puzzle=UnknownPuzzle(known_tree_hash=bytes32(revocation_layer.curried_args[2].as_atom())),
                ).tree_hash,
                amount=uint64(parent_coin.amount),
                parent_proof_hash=None if parent_proof_hash == Program.NIL else parent_proof_hash,
            )

        new_vc: Self = cls(
            coin,
            singleton_lineage_proof,
            eml_lineage_proof,
            launcher_id,
            inner_puzzle_hash,
            proof_provider,
            proof_hash,
        )
        if new_vc.construct_puzzle().get_tree_hash() != new_vc.coin.puzzle_hash:
            raise ValueError("Error getting new VC from coin spend, probably the child singleton is not a VC")

        return new_vc

    ####################################################################################################################
    # The methods in this section are useful for spending an existing VC
    def magic_condition_for_new_proofs(
        self,
        new_proof_hash: bytes32 | None,
        provider_innerpuzhash: bytes32,
        new_proof_provider: bytes32 | None = None,
    ) -> MagicTPCondition[UnknownSolution]:
        """
        Returns the 'magic' condition that can update the metadata with a new proof hash. Returning this condition from
        the inner puzzle will require a corresponding announcement from the provider DID authorizing that proof hash
        change.
        """
        return MagicTPCondition(
            eml_lineage_proof=self.eml_lineage_proof,
            launcher_id=self.launcher_id,
            tp_solution=UnknownSolution(
                program=DidTpSolution(
                    provider_innerpuzhash=provider_innerpuzhash,
                    my_coin_id=self.coin.name(),
                    new_metadata=Program.to(new_proof_hash),
                    new_transfer_program=None,  # TP update is not allowed because singleton will leave the VC protocol
                ).program
            ),
        )

    def standard_magic_condition(self) -> MagicTPCondition[UnknownSolution]:
        """
        Returns the standard magic condition that needs to be returned to the metadata layer. Returning this condition
        from the inner puzzle will leave the proof hash and transfer program the same.
        """
        return MagicTPCondition(
            eml_lineage_proof=self.eml_lineage_proof,
            launcher_id=self.launcher_id,
            tp_solution=None,
        )

    def magic_condition_for_self_revoke(self) -> MagicTPCondition[UnknownSolution]:
        return MagicTPCondition(
            eml_lineage_proof=self.eml_lineage_proof,
            launcher_id=self.launcher_id,
            tp_solution=UnknownSolution(program=Program.to(ACS_TRANSFER_PROGRAM.get_tree_hash())),
        )

    def do_spend(
        self,
        inner_puzzle: Program,
        inner_solution: Program,
        new_proof_hash: bytes32 | None = None,
    ) -> tuple[CreatePuzzleAnnouncement | None, CoinSpend, VerifiedCredential]:
        """
        Given an inner puzzle reveal and solution, spend the VC (potentially updating the proofs in the process).
        Note that the inner puzzle is already expected to output the 'magic' condition (which can be created above).

        Returns potentially the puzzle announcement the spend will expect from the provider DID, the spend of the VC,
        and the expected class representation of the new VC after the spend is pushed and confirmed.
        """
        vc_solution: Program = solution_for_singleton(
            self.singleton_lineage_proof,
            uint64(self.coin.amount),
            ExigentMetadataLayerSolution(
                inner_solution=RevocationLayerSolution(
                    puzzle_reveal=UnknownPuzzle(known_program=inner_puzzle),
                    inner_solution=UnknownSolution(program=inner_solution),
                )
            ).program,
        )

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

        new_singleton_condition: Program = next(
            c for c in inner_puzzle.run(inner_solution).as_iter() if c.at("f") == 51 and c.at("rrf").as_int() % 2 != 0
        )
        new_inner_puzzle_hash: bytes32 = bytes32(new_singleton_condition.at("rf").as_atom())

        return (
            expected_announcement,
            make_spend(
                self.coin,
                self.construct_puzzle(),
                vc_solution,
            ),
            self._next_vc(
                new_inner_puzzle_hash,
                self.as_inner_puzzle.proof_hash if new_proof_hash is None else new_proof_hash,
                uint64(new_singleton_condition.at("rrf").as_int()),
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
        vc_inner = self.as_inner_puzzle
        vc_solution: Program = solution_for_singleton(
            self.singleton_lineage_proof,
            uint64(self.coin.amount),
            ExigentMetadataLayerSolution(
                inner_solution=RevocationLayerSolution(
                    puzzle_reveal=StandardBrickPuzzle(),
                    inner_solution=StandardBrickPuzzleSolution(
                        launcher_id=self.launcher_id,
                        metadata_hash=Program.to((vc_inner.proof_provider, vc_inner.proof_hash)).get_tree_hash(),
                        tp_hash=vc_inner.transfer_program.tree_hash,
                        inner_puzzle_hash=vc_inner.custody_puzzle.tree_hash,
                        amount=uint64(self.coin.amount),
                        eml_lineage_proof=vc_inner.eml_lineage_proof,
                        provider_innerpuzhash=provider_innerpuzhash,
                        coin_id=self.coin.name(),
                        announcement_nonce=announcement_nonce,
                    ),
                    hidden=True,
                )
            ).program,
        )

        expected_announcement: CreatePuzzleAnnouncement = CreatePuzzleAnnouncement(
            std_hash(self.coin.name() + Program.NIL.get_tree_hash() + ACS_TRANSFER_PROGRAM.get_tree_hash())
        )

        return (
            expected_announcement,
            make_spend(self.coin, self.construct_puzzle(), vc_solution),
        )

    ####################################################################################################################

    def _next_vc(
        self, next_inner_puzzle_hash: bytes32, new_proof_hash: bytes32 | None, next_amount: uint64
    ) -> VerifiedCredential:
        """
        Private method that creates the next VC class instance.
        """
        slightly_incomplete_vc: VerifiedCredential = VerifiedCredential(
            Coin(self.coin.name(), bytes32.zeros, next_amount),
            LineageProof(
                self.coin.parent_coin_info,
                self.construct_exigent_metadata_layer().get_tree_hash(),
                uint64(self.coin.amount),
            ),
            VCLineageProof(
                self.coin.parent_coin_info,
                self.wrap_inner_with_backdoor().get_tree_hash(),
                uint64(self.coin.amount),
                Program.to((self.proof_provider, self.proof_hash)).get_tree_hash(),
            ),
            self.launcher_id,
            next_inner_puzzle_hash,
            self.proof_provider,
            new_proof_hash,
        )

        return replace(
            slightly_incomplete_vc,
            coin=Coin(
                slightly_incomplete_vc.coin.parent_coin_info,
                slightly_incomplete_vc.construct_puzzle().get_tree_hash(),
                slightly_incomplete_vc.coin.amount,
            ),
        )


# This class is sort of unparadigmatic as an outer puzzle.
# It lives somewhere between outer puzzle and inner puzzle, but the most convenient
# way to present it in this wallet is as an outer puzzle.
# This may lead to some peculiarities if use cases are to be expanded beyond simply using this
# inside of a CAT.
@dataclass(frozen=True)
class RevocationOuterPuzzle:
    def match(self, puzzle: UnknownPuzzle) -> PuzzleInfo | None:
        revocation_layer_match = RevocationLayer.match(unknown_puzzle=puzzle)
        if revocation_layer_match is None:
            return None
        constructor_dict: dict[str, Any] = {
            "type": "revocation layer",
            "hidden_puzzle_hash": "0x" + revocation_layer_match.hidden_puzzle.tree_hash.hex(),
        }
        return PuzzleInfo(constructor_dict)

    def get_inner_puzzle(
        self, constructor: PuzzleInfo, puzzle_reveal: UnknownPuzzle, solution: Program | None = None
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
            hidden_puzzle=UnknownPuzzle(known_tree_hash=constructor["hidden_puzzle_hash"]),
            inner_puzzle=UnknownPuzzle(known_program=inner_puzzle),
        ).program

    def solve(self, constructor: PuzzleInfo, solver: Solver, inner_puzzle: Program, inner_solution: Program) -> Program:
        return RevocationLayerSolution(  # deliberately no support for hidden puzzle spends
            puzzle_reveal=UnknownPuzzle(known_program=inner_puzzle),
            inner_solution=UnknownSolution(program=inner_solution),
        ).program


_T_Solution = TypeVar("_T_Solution", bound=Solution)


@final
@dataclass(kw_only=True, frozen=True)
class MagicTPCondition(Condition, Generic[_T_Solution]):
    eml_lineage_proof: VCLineageProof
    launcher_id: bytes32
    tp_solution: _T_Solution | None

    def __post_init__(self) -> None:
        # Driver-only condition; fields are not streamable-serializable.
        return None

    def to_program(self) -> Program:
        return Program.to(
            [
                -10,
                self.eml_lineage_proof.to_program(),
                [self.eml_lineage_proof.parent_proof_hash, self.launcher_id],
                self.tp_solution.program if self.tp_solution is not None else None,
            ]
        )

    @classmethod
    def from_program(cls, program: Program) -> MagicTPCondition[UnknownSolution]:  # type: ignore[override]
        _, eml_lineage_proof, proof_hash_and_launcher_id, tp_solution = program.as_iter()
        proof_hash, launcher_id = proof_hash_and_launcher_id.as_iter()
        num_values = eml_lineage_proof.list_len()
        inner_puzzle_hash = None
        if num_values == 2:
            parent_id, amount = eml_lineage_proof.as_iter()
        else:
            parent_id, inner_puzzle_hash, amount = eml_lineage_proof.as_iter()
        return MagicTPCondition(
            eml_lineage_proof=VCLineageProof(
                parent_proof_hash=bytes32(proof_hash.as_atom()) if proof_hash != Program.NIL else None,
                inner_puzzle_hash=bytes32(inner_puzzle_hash.as_atom()) if inner_puzzle_hash is not None else None,
                amount=uint64(amount.as_int()),
                parent_name=bytes32(parent_id.as_atom()),
            ),
            launcher_id=bytes32(launcher_id.as_atom()),
            tp_solution=None if tp_solution == Program.NIL else UnknownSolution(program=tp_solution),
        )
