from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Literal, Self, TypeVar, cast

from chia_puzzles_py.programs import (
    NFT_INTERMEDIATE_LAUNCHER,
    NFT_METADATA_UPDATER_DEFAULT,
    NFT_METADATA_UPDATER_DEFAULT_HASH,
    NFT_OWNERSHIP_TRANSFER_PROGRAM_ONE_WAY_CLAIM_WITH_ROYALTIES,
    NFT_STATE_LAYER,
    NFT_STATE_LAYER_HASH,
)
from chia_puzzles_py.programs import (
    NFT_OWNERSHIP_LAYER as NFT_OWNERSHIP_LAYER_BYTES,
)
from chia_puzzles_py.programs import (
    NFT_OWNERSHIP_LAYER_HASH as NFT_OWNERSHIP_LAYER_HASH_BYTES,
)
from chia_rs import Coin
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64
from clvm_tools.binutils import disassemble

from chia.types.blockchain_format.program import Program, run
from chia.util.bech32m import encode_puzzle_hash
from chia.wallet.conditions import Condition, CreateCoin, parse_conditions_non_consensus
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo, NFTInfo
from chia.wallet.puzzles.puzzle_drivers import (
    InnerPuzzle,
    OuterPuzzle,
    PuzzleWithPuzzleHash,
    SmartCoin,
    Solution,
    UnknownPuzzle,
    UnknownSolution,
)
from chia.wallet.puzzles.singleton_drivers import (
    Singleton,
    SingletonPuzzle,
    SingletonSolution,
    SingletonStruct,
)
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash, curry_and_treehash

NFT_STATE_LAYER_MOD = Program.from_bytes(NFT_STATE_LAYER)
NFT_STATE_LAYER_MOD_HASH = bytes32(NFT_STATE_LAYER_HASH)
NFT_STATE_LAYER_MOD_HASH_HASH = Program.to(NFT_STATE_LAYER_MOD_HASH).get_tree_hash()
HASH_OF_STATE_LAYER_QUOTED_MOD_HASH = calculate_hash_of_quoted_mod_hash(NFT_STATE_LAYER_MOD_HASH)
NFT_METADATA_UPDATER = Program.from_bytes(NFT_METADATA_UPDATER_DEFAULT)
NFT_METADATA_UPDATER_HASH = bytes32(NFT_METADATA_UPDATER_DEFAULT_HASH)
NFT_OWNERSHIP_LAYER = Program.from_bytes(NFT_OWNERSHIP_LAYER_BYTES)
NFT_OWNERSHIP_LAYER_HASH = bytes32(NFT_OWNERSHIP_LAYER_HASH_BYTES)
NFT_OWNERSHIP_LAYER_HASH_HASH = Program.to(NFT_OWNERSHIP_LAYER_HASH).get_tree_hash()
HASH_OF_OWNERSHIP_LAYER_QUOTED_MOD_HASH = calculate_hash_of_quoted_mod_hash(NFT_OWNERSHIP_LAYER_HASH)
NFT_TRANSFER_PROGRAM_DEFAULT = Program.from_bytes(NFT_OWNERSHIP_TRANSFER_PROGRAM_ONE_WAY_CLAIM_WITH_ROYALTIES)
HASH_OF_TRANSFER_PROGRAM_QUOTED_MOD_HASH = calculate_hash_of_quoted_mod_hash(
    NFT_TRANSFER_PROGRAM_DEFAULT.get_tree_hash()
)
INTERMEDIATE_LAUNCHER_MOD = Program.from_bytes(NFT_INTERMEDIATE_LAUNCHER)


@dataclass(frozen=True, kw_only=True)
class DefaultMetadataUpdater(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _inner_puzzle_protocol_check: ClassVar[InnerPuzzle] = cast("DefaultMetadataUpdater", None)

    @property
    def puzzle(self) -> Program:
        return NFT_METADATA_UPDATER

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return NFT_METADATA_UPDATER_HASH

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> DefaultMetadataUpdater | None:
        if unknown_puzzle.puzzle_hash != DefaultMetadataUpdater().puzzle_hash:
            return None
        return DefaultMetadataUpdater()


@dataclass(frozen=True, kw_only=True)
class UpdateMetadataCondition(Condition):
    data_uri: str | None = None
    meta_uri: str | None = None
    license_uri: str | None = None
    other_update: tuple[str, str] | None = None
    metadata_updater: InnerPuzzle = DefaultMetadataUpdater()

    data_key: ClassVar[Literal[b"u"]] = b"u"
    meta_key: ClassVar[Literal[b"mu"]] = b"mu"
    license_key: ClassVar[Literal[b"lu"]] = b"lu"

    def __post_init__(self) -> None:
        args_list = [self.data_uri, self.meta_uri, self.license_uri, self.other_update]
        non_none_args = [_ for _ in args_list if _ is not None]
        if len(non_none_args) != 1:
            raise ValueError("Only one of data_uri, meta_uri, license_uri, or other_update can be provided")

    def to_program(self) -> Program:
        key: bytes
        uri: str
        if self.data_uri is not None:
            key = self.data_key
            uri = self.data_uri
        elif self.meta_uri is not None:
            key = self.meta_key
            uri = self.meta_uri
        elif self.license_uri is not None:
            key = self.license_key
            uri = self.license_uri
        elif self.other_update is not None:
            other_key, uri = self.other_update
            key = other_key.encode("utf8")
        else:
            raise ValueError("One of data_uri, meta_uri, or license_uri must be provided")

        return Program.to([-24, self.metadata_updater.puzzle, (key, uri)])

    @classmethod
    def from_program(cls, program: Program) -> Self:
        key = program.at("rrff")
        uri = program.at("rrfr")
        if key == cls.data_key:
            return cls(data_uri=str(uri.as_atom(), "utf8"))
        elif key == cls.meta_key:
            return cls(meta_uri=str(uri.as_atom(), "utf8"))
        elif key == cls.license_key:
            return cls(license_uri=str(uri.as_atom(), "utf8"))
        else:
            raise ValueError("Invalid key")


@dataclass(frozen=True, kw_only=True)
class NFTMetadata:
    data_uris: list[str] | None
    data_hash: bytes | None
    meta_uris: list[str] | None = None
    meta_hash: bytes | None = None
    license_uris: list[str] | None = None
    license_hash: bytes | None = None
    edition_number: int | None = None
    edition_total: int | None = None
    other_metadata: dict[bytes, Any] = field(default_factory=dict)

    data_key: ClassVar[Literal[b"u"]] = b"u"
    data_hash_key: ClassVar[Literal[b"h"]] = b"h"
    meta_key: ClassVar[Literal[b"mu"]] = b"mu"
    meta_hash_key: ClassVar[Literal[b"mh"]] = b"mh"
    license_key: ClassVar[Literal[b"lu"]] = b"lu"
    license_hash_key: ClassVar[Literal[b"lh"]] = b"lh"
    edition_number_key: ClassVar[Literal[b"sn"]] = b"sn"
    edition_total_key: ClassVar[Literal[b"st"]] = b"st"

    def prepend_value(self, *, key: Literal[b"u", b"mu", b"lu"], value: str) -> Self:
        if key == self.data_key:
            return replace(self, data_uris=[value, *(self.data_uris or [])])
        elif key == self.meta_key:
            return replace(self, meta_uris=[value, *(self.meta_uris or [])])
        elif key == self.license_key:
            return replace(self, license_uris=[value, *(self.license_uris or [])])
        raise ValueError(f"Unsupported metadata key: {key!r}")

    def update_from_condition(self, *, condition: UpdateMetadataCondition) -> Self:
        if condition.data_uri is not None:
            return self.prepend_value(key=self.data_key, value=condition.data_uri)
        if condition.meta_uri is not None:
            return self.prepend_value(key=self.meta_key, value=condition.meta_uri)
        if condition.license_uri is not None:
            return self.prepend_value(key=self.license_key, value=condition.license_uri)
        raise NotImplementedError("Impossible to reach")  # pragma: no cover

    def as_program(self) -> Program:
        return Program.to(
            [
                *([(self.data_key, Program.to(self.data_uris))] if self.data_uris is not None else []),
                *([(self.data_hash_key, self.data_hash)] if self.data_hash is not None else []),
                *([(self.meta_key, Program.to(self.meta_uris))] if self.meta_uris is not None else []),
                *([(self.meta_hash_key, self.meta_hash)] if self.meta_hash is not None else []),
                *([(self.license_key, Program.to(self.license_uris))] if self.license_uris is not None else []),
                *([(self.license_hash_key, self.license_hash)] if self.license_hash is not None else []),
                *([(self.edition_number_key, self.edition_number)] if self.edition_number is not None else []),
                *([(self.edition_total_key, self.edition_total)] if self.edition_total is not None else []),
                *((k, v) for k, v in self.other_metadata.items()),
            ]
        )

    @classmethod
    def from_program(cls, program: Program) -> Self:
        data_uris: list[str] | None = None
        data_hash: bytes | None = None
        meta_uris: list[str] | None = None
        meta_hash: bytes | None = None
        license_uris: list[str] | None = None
        license_hash: bytes | None = None
        edition_number: int | None = None
        edition_total: int | None = None
        other_metadata: dict[bytes, Any] = {}

        for kv_pair in program.as_iter():
            key = kv_pair.first().as_atom()
            rest = kv_pair.rest()
            if rest.atom is not None and rest != Program.NIL:
                value = rest.as_atom()
                if key == cls.data_hash_key:
                    data_hash = value
                elif key == cls.meta_hash_key:
                    meta_hash = value
                elif key == cls.license_hash_key:
                    license_hash = value
                elif key == cls.edition_number_key:
                    edition_number = int.from_bytes(value, "big")
                elif key == cls.edition_total_key:
                    edition_total = int.from_bytes(value, "big")
                else:
                    other_metadata[key] = value
            else:
                value_list = [str(uri.as_atom(), "utf8") for uri in rest.as_iter()]
                if key == cls.data_key:
                    data_uris = value_list
                elif key == cls.meta_key:
                    meta_uris = value_list
                elif key == cls.license_key:
                    license_uris = value_list
                else:
                    other_metadata[key] = value_list

        return cls(
            data_uris=data_uris,
            data_hash=data_hash,
            meta_uris=meta_uris,
            meta_hash=meta_hash,
            license_uris=license_uris,
            license_hash=license_hash,
            edition_number=edition_number,
            edition_total=edition_total,
            other_metadata=other_metadata,
        )


_T_InnerPuzzle = TypeVar("_T_InnerPuzzle", bound=InnerPuzzle)
_T_MetadataUpdater = TypeVar("_T_MetadataUpdater", bound=InnerPuzzle)


@dataclass(frozen=True, kw_only=True)
class MetadataLayer(PuzzleWithPuzzleHash, Generic[_T_InnerPuzzle, _T_MetadataUpdater]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast(
            "MetadataLayer[_T_InnerPuzzle, _T_MetadataUpdater]", None
        )

    inner_puzzle: _T_InnerPuzzle
    metadata: Program
    metadata_updater: _T_MetadataUpdater

    @cached_property
    def metadata_hash(self) -> bytes32:
        return self.metadata.get_tree_hash()

    @property
    def puzzle(self) -> Program:
        return NFT_STATE_LAYER_MOD.curry(
            NFT_STATE_LAYER_MOD_HASH, self.metadata, self.metadata_updater.puzzle_hash, self.inner_puzzle.puzzle
        )

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return curry_and_treehash(
            HASH_OF_STATE_LAYER_QUOTED_MOD_HASH,
            NFT_STATE_LAYER_MOD_HASH_HASH,
            self.metadata_hash,
            Program.to(self.metadata_updater.puzzle_hash).get_tree_hash(),
            self.inner_puzzle.puzzle_hash,
        )

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> MetadataLayer[UnknownPuzzle, UnknownPuzzle] | None:
        if unknown_puzzle.mod != NFT_STATE_LAYER_MOD or unknown_puzzle.curried_args is None:
            return None

        (_, metadata, metadata_updater_puzhash, inner_puzzle) = unknown_puzzle.curried_args

        return MetadataLayer(
            inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle),
            metadata=metadata,
            metadata_updater=UnknownPuzzle(known_puzzle_hash=bytes32(metadata_updater_puzhash.as_atom())),
        )


_T_InnerSolution = TypeVar("_T_InnerSolution", bound=Solution)


@dataclass(frozen=True)
class MetadataLayerSolution(Generic[_T_InnerSolution]):
    inner_solution: _T_InnerSolution

    def as_program(self) -> Program:
        return Program.to([self.inner_solution.as_program()])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> MetadataLayerSolution[UnknownSolution] | None:
        if (  # check it's a one item list
            unknown_solution.as_program().cons is None or unknown_solution.as_program().at("r") != Program.NIL
        ):
            return None
        return MetadataLayerSolution(inner_solution=UnknownSolution(solution=unknown_solution.as_program().at("f")))


@dataclass(frozen=True, kw_only=True)
class TransferProgramCondition(Condition):
    trade_prices_list: dict[bytes32, int]  # OuterPuzzle[OfferMod] hint here?
    new_owner: SingletonPuzzle[Any] | None = None

    def __post_init__(self) -> None:
        # Ignoring streamable post init
        return None

    def to_program(self) -> Program:
        return Program.to(
            [
                -10,
                self.new_owner.launcher_id if self.new_owner is not None else None,
                [[v, k] for k, v in self.trade_prices_list.items()],
                self.new_owner.inner_puzzle.puzzle_hash if self.new_owner is not None else None,
            ]
        )

    @classmethod
    def from_program(cls, program: Program) -> TransferProgramCondition:
        _, launcher_id, trade_prices_list, inner_puzzle_hash = program.as_iter()
        return TransferProgramCondition(
            trade_prices_list={
                bytes32(tp_tuple.at("f").as_atom()): tp_tuple.at("r").as_int()
                for tp_tuple in trade_prices_list.as_iter()
            },
            new_owner=SingletonPuzzle(
                launcher_id=bytes32(launcher_id.as_atom()),
                inner_puzzle=UnknownPuzzle(known_puzzle_hash=bytes32(inner_puzzle_hash.as_atom())),
            )
            if launcher_id != Program.NIL
            else None,
        )


@dataclass(frozen=True, kw_only=True)
class DefaultTransferProgram(PuzzleWithPuzzleHash):
    if TYPE_CHECKING:
        _inner_puzzle_protocol_check: ClassVar[InnerPuzzle] = cast("DefaultTransferProgram", None)

    self_launcher_id: bytes32
    royalty_address: bytes32 | None
    royalty_basis_points: int
    struct_driver: ClassVar[type[SingletonStruct]] = SingletonStruct

    @property
    def puzzle(self) -> Program:
        return NFT_TRANSFER_PROGRAM_DEFAULT.curry(
            SingletonStruct(launcher_id=self.self_launcher_id).program, self.royalty_address, self.royalty_basis_points
        )

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return curry_and_treehash(
            HASH_OF_TRANSFER_PROGRAM_QUOTED_MOD_HASH,
            self.struct_driver(launcher_id=self.self_launcher_id).struct_hash,
            Program.to(self.royalty_address).get_tree_hash(),
            Program.to(self.royalty_basis_points).get_tree_hash(),
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None) -> DefaultTransferProgram | None:
        if unknown_puzzle.mod != NFT_TRANSFER_PROGRAM_DEFAULT or unknown_puzzle.curried_args is None:
            return None

        (singleton_struct, royalty_address, royalty_basis_points) = unknown_puzzle.curried_args

        return DefaultTransferProgram(
            self_launcher_id=cls.struct_driver.from_program(singleton_struct).launcher_id,
            royalty_address=bytes32(royalty_address.as_atom()) if royalty_address != Program.NIL else None,
            royalty_basis_points=royalty_basis_points.as_int(),
        )


_T_TransferProgram = TypeVar("_T_TransferProgram", bound=InnerPuzzle)


@dataclass(frozen=True, kw_only=True)
class OwnershipLayer(PuzzleWithPuzzleHash, Generic[_T_InnerPuzzle, _T_TransferProgram]):
    if TYPE_CHECKING:
        _outer_puzzle_protocol_check: ClassVar[OuterPuzzle[InnerPuzzle]] = cast(
            "OwnershipLayer[_T_InnerPuzzle, _T_TransferProgram]", None
        )

    current_owner: bytes32 | None
    inner_puzzle: _T_InnerPuzzle
    transfer_program: _T_TransferProgram

    @property
    def puzzle(self) -> Program:
        return NFT_OWNERSHIP_LAYER.curry(
            NFT_OWNERSHIP_LAYER_HASH, self.current_owner, self.transfer_program.puzzle, self.inner_puzzle.puzzle
        )

    @property
    def puzzle_hash_optimized(self) -> bytes32:
        return curry_and_treehash(
            HASH_OF_OWNERSHIP_LAYER_QUOTED_MOD_HASH,
            NFT_OWNERSHIP_LAYER_HASH_HASH,
            Program.to(self.current_owner).get_tree_hash(),
            self.transfer_program.puzzle_hash,
            self.inner_puzzle.puzzle_hash,
        )

    @classmethod
    def match(
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> OwnershipLayer[UnknownPuzzle, UnknownPuzzle] | None:
        if unknown_puzzle.mod != NFT_OWNERSHIP_LAYER or unknown_puzzle.curried_args is None:
            return None

        (_, current_owner, transfer_program, inner_puzzle) = unknown_puzzle.curried_args

        return OwnershipLayer(
            inner_puzzle=UnknownPuzzle(known_puzzle=inner_puzzle),
            current_owner=bytes32(current_owner.as_atom()) if current_owner != Program.NIL else None,
            transfer_program=UnknownPuzzle(known_puzzle=transfer_program),
        )


@dataclass(frozen=True)
class OwnershipLayerSolution(Generic[_T_InnerSolution]):
    inner_solution: _T_InnerSolution

    def as_program(self) -> Program:
        return Program.to([self.inner_solution.as_program()])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> OwnershipLayerSolution[UnknownSolution] | None:
        if (  # check it's a one item list
            unknown_solution.as_program().cons is None or unknown_solution.as_program().at("r") != Program.NIL
        ):
            return None
        return OwnershipLayerSolution(inner_solution=UnknownSolution(solution=unknown_solution.as_program().at("f")))


class NFTSolution(
    SingletonSolution[MetadataLayerSolution[_T_InnerSolution | OwnershipLayerSolution[_T_InnerSolution]]],
    Generic[_T_InnerSolution],
):
    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> NFTSolution[UnknownSolution] | None:  # type: ignore[override]
        singleton_match = SingletonSolution.match(unknown_solution=unknown_solution)
        if singleton_match is None:
            return None
        metadata_match = MetadataLayerSolution.match(unknown_solution=singleton_match.inner_solution)
        if metadata_match is None:
            return None
        ownership_match = OwnershipLayerSolution.match(unknown_solution=metadata_match.inner_solution)

        return NFTSolution(
            lineage_proof=singleton_match.lineage_proof,
            coin_amount=singleton_match.coin_amount,
            inner_solution=MetadataLayerSolution(
                inner_solution=ownership_match if ownership_match is not None else metadata_match.inner_solution
            ),
        )


class NFT(
    Singleton[
        MetadataLayer[_T_InnerPuzzle | OwnershipLayer[_T_InnerPuzzle, DefaultTransferProgram], DefaultMetadataUpdater]
    ],
    Generic[_T_InnerPuzzle],
):
    if TYPE_CHECKING:
        _smart_coin_protocol_check: ClassVar[SmartCoin] = cast("NFT[UnknownPuzzle]", None)

    @property
    def is_nft1(self) -> bool:
        return isinstance(self.inner_puzzle.inner_puzzle, OwnershipLayer)

    @property
    def innermost_puzzle(self) -> _T_InnerPuzzle:
        if self.is_nft1:
            assert isinstance(self.inner_puzzle.inner_puzzle, OwnershipLayer)
            return self.inner_puzzle.inner_puzzle.inner_puzzle
        else:
            assert not isinstance(self.inner_puzzle.inner_puzzle, OwnershipLayer)
            return self.inner_puzzle.inner_puzzle

    @classmethod
    def match(  # type: ignore[override]
        cls, *, unknown_puzzle: UnknownPuzzle, solution: object | None = None
    ) -> (
        SingletonPuzzle[
            MetadataLayer[UnknownPuzzle | OwnershipLayer[UnknownPuzzle, DefaultTransferProgram], DefaultMetadataUpdater]
        ]
        | None
    ):
        singleton_match = SingletonPuzzle.match(unknown_puzzle=unknown_puzzle, solution=solution)
        if singleton_match is None:
            return None

        metadata_match = MetadataLayer.match(unknown_puzzle=singleton_match.inner_puzzle, solution=solution)
        if metadata_match is None:
            return None
        metadata_updater_match = DefaultMetadataUpdater.match(unknown_puzzle=metadata_match.metadata_updater)
        if metadata_updater_match is None:
            return None
        ownership_match = OwnershipLayer.match(unknown_puzzle=metadata_match.inner_puzzle, solution=solution)
        default_tp_match = None
        if ownership_match is not None:
            default_tp_match = DefaultTransferProgram.match(unknown_puzzle=ownership_match.transfer_program)
            if default_tp_match is None:
                return None

        return SingletonPuzzle(
            launcher_id=singleton_match.launcher_id,
            inner_puzzle=MetadataLayer(
                metadata=metadata_match.metadata,
                metadata_updater=metadata_updater_match,
                inner_puzzle=OwnershipLayer(
                    current_owner=ownership_match.current_owner,
                    inner_puzzle=ownership_match.inner_puzzle,
                    transfer_program=default_tp_match,
                )
                if ownership_match is not None and default_tp_match is not None
                else metadata_match.inner_puzzle,
            ),
        )

    def replace_inner_most_puzzle(self, new_inner_puzzle: InnerPuzzle) -> Self:
        if isinstance(self.inner_puzzle.inner_puzzle, OwnershipLayer):
            updated_ownership = replace(self.inner_puzzle.inner_puzzle, inner_puzzle=new_inner_puzzle)  # type: ignore[arg-type]
            updated_metadata = replace(self.inner_puzzle, inner_puzzle=updated_ownership)
            return replace(self, inner_puzzle=updated_metadata)  # type: ignore[arg-type]
        updated_metadata = replace(self.inner_puzzle, inner_puzzle=new_inner_puzzle)  # type: ignore[arg-type]
        return replace(self, inner_puzzle=updated_metadata)  # type: ignore[arg-type]

    @classmethod
    def get_next_from_previous(
        cls,
        previous_coin: Coin,
        previous_nft_puzzle: UnknownPuzzle,
        previous_solution: UnknownSolution,
    ) -> NFT[UnknownPuzzle]:
        nft_puzzle_match = cls.match(unknown_puzzle=previous_nft_puzzle)
        if nft_puzzle_match is None:
            raise ValueError("Invalid puzzle for NFT")
        nft_solution_match = NFTSolution.match(unknown_solution=previous_solution)
        if nft_solution_match is None:
            raise ValueError("Invalid solution for NFT")
        inner_solution = nft_solution_match.inner_solution.inner_solution
        previous_nft = NFT(
            coin=previous_coin,
            launcher_id=nft_puzzle_match.launcher_id,
            lineage_proof=nft_solution_match.lineage_proof,
            inner_puzzle=nft_puzzle_match.inner_puzzle,
        )
        if isinstance(inner_solution, OwnershipLayerSolution) and previous_nft.is_nft1:
            inner_solution = inner_solution.inner_solution

        conditions_prog = run(previous_nft.innermost_puzzle.puzzle, inner_solution.as_program())
        conditions = parse_conditions_non_consensus(
            conditions_prog.as_iter(),
            additional_conditions={
                Program.to(-10).as_atom(): TransferProgramCondition,
                Program.to(-24).as_atom(): UpdateMetadataCondition,
            },
        )
        next_singleton_coin = next(c for c in conditions if isinstance(c, CreateCoin) and c.amount % 2 == 1)
        update_metadata_condition = (
            umc[0] if (umc := [c for c in conditions if isinstance(c, UpdateMetadataCondition)]) != [] else None
        )
        tp_condition = (
            tpc[0] if (tpc := [c for c in conditions if isinstance(c, TransferProgramCondition)]) != [] else None
        )
        previous_metadata = NFTMetadata.from_program(previous_nft.inner_puzzle.metadata)
        nft_puzzle = SingletonPuzzle(
            launcher_id=previous_nft.launcher_id,
            inner_puzzle=MetadataLayer(
                metadata=previous_metadata.update_from_condition(condition=update_metadata_condition).as_program()
                if update_metadata_condition is not None
                else previous_metadata.as_program(),
                metadata_updater=DefaultMetadataUpdater(),
                inner_puzzle=OwnershipLayer(
                    current_owner=(tp_condition.new_owner.launcher_id if tp_condition.new_owner is not None else None)
                    if tp_condition is not None
                    else previous_nft.inner_puzzle.inner_puzzle.current_owner,
                    transfer_program=previous_nft.inner_puzzle.inner_puzzle.transfer_program,
                    inner_puzzle=UnknownPuzzle(known_puzzle_hash=next_singleton_coin.puzzle_hash),
                )
                if isinstance(previous_nft.inner_puzzle.inner_puzzle, OwnershipLayer)
                else UnknownPuzzle(known_puzzle_hash=next_singleton_coin.puzzle_hash),
            ),
        )
        return NFT(
            coin=Coin(
                previous_nft.coin.name(),
                nft_puzzle.puzzle_hash,
                next_singleton_coin.amount,
            ),
            launcher_id=previous_nft.launcher_id,
            lineage_proof=LineageProof(
                previous_nft.coin.parent_coin_info, previous_nft.inner_puzzle.puzzle_hash, previous_nft.coin.amount
            ),
            inner_puzzle=nft_puzzle.inner_puzzle,
        )

    @classmethod
    def from_db_object(cls, nft: NFTCoinInfo) -> NFT[UnknownPuzzle]:
        puzzle_match = NFT.match(unknown_puzzle=UnknownPuzzle(known_puzzle=nft.full_puzzle))
        if puzzle_match is None:
            raise RuntimeError("Unexpected DB object for NFT parsing")
        return NFT(
            launcher_id=nft.nft_id,
            coin=nft.coin,
            lineage_proof=nft.lineage_proof,
            inner_puzzle=puzzle_match.inner_puzzle,
        )

    def to_db_object(
        self,
        *,
        mint_height: uint32,
        minter_did: bytes32 | None,
        latest_height: uint32,
        pending_transaction: bool,
    ) -> NFTCoinInfo:
        return NFTCoinInfo(
            nft_id=self.launcher_id,
            coin=self.coin,
            lineage_proof=self.lineage_proof,
            full_puzzle=self.puzzle,
            mint_height=mint_height,
            minter_did=minter_did,
            latest_height=latest_height,
            pending_transaction=pending_transaction,
        )

    def to_ux_object(self, db_object: NFTCoinInfo, config: dict[str, Any]) -> NFTInfo:
        parsed_metadata = NFTMetadata.from_program(self.inner_puzzle.metadata)
        return NFTInfo(
            encode_puzzle_hash(self.launcher_id, prefix=AddressType.NFT.hrp(config=config)),
            self.launcher_id,
            self.coin.name(),
            db_object.latest_height,
            self.inner_puzzle.inner_puzzle.current_owner
            if isinstance(self.inner_puzzle.inner_puzzle, OwnershipLayer)
            else None,
            uint16(self.inner_puzzle.inner_puzzle.transfer_program.royalty_basis_points)
            if isinstance(self.inner_puzzle.inner_puzzle, OwnershipLayer)
            else None,
            self.inner_puzzle.inner_puzzle.transfer_program.royalty_address
            if isinstance(self.inner_puzzle.inner_puzzle, OwnershipLayer)
            else None,
            parsed_metadata.data_uris or [],
            parsed_metadata.data_hash or b"",
            [] if parsed_metadata.meta_uris is None else parsed_metadata.meta_uris,
            b"" if parsed_metadata.meta_hash is None else parsed_metadata.meta_hash,
            [] if parsed_metadata.license_uris is None else parsed_metadata.license_uris,
            b"" if parsed_metadata.license_hash is None else parsed_metadata.license_hash,
            uint64(0) if parsed_metadata.edition_total is None else uint64(parsed_metadata.edition_total),
            uint64(0) if parsed_metadata.edition_number is None else uint64(parsed_metadata.edition_number),
            self.inner_puzzle.metadata_updater.puzzle_hash,
            disassemble(self.inner_puzzle.metadata),
            db_object.mint_height,
            self.is_nft1,
            self.innermost_puzzle.puzzle_hash,
            db_object.pending_transaction,
            db_object.minter_did,
            off_chain_metadata=None,
        )
