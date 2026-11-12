from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Literal, Self, TypeVar, cast

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint64
from clvm_tools.binutils import disassemble

from chia.pools.plotnft_drivers import SingletonStruct
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.util.bech32m import encode_puzzle_hash
from chia.wallet.conditions import Condition
from chia.wallet.nft_wallet.nft_info import NFTCoinInfo, NFTInfo
from chia.wallet.nft_wallet.nft_puzzles import (
    NFT_METADATA_UPDATER,
    NFT_METADATA_UPDATER_HASH,
    NFT_OWNERSHIP_LAYER,
    NFT_OWNERSHIP_LAYER_HASH,
    NFT_STATE_LAYER_MOD,
    NFT_STATE_LAYER_MOD_HASH,
    NFT_TRANSFER_PROGRAM_DEFAULT,
)
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT
from chia.wallet.puzzles.puzzle_drivers import Puzzle, PuzzleBase, Solution, UnknownPuzzle, UnknownSolution
from chia.wallet.singleton import (
    SINGLETON_LAUNCHER_PUZZLE_HASH,
    SINGLETON_TOP_LAYER_MOD,
    SINGLETON_TOP_LAYER_MOD_HASH,
)
from chia.wallet.util.address_type import AddressType
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash, curry_and_treehash

log = logging.getLogger(__name__)

NFT_STATE_LAYER_MOD_HASH_HASH = Program.to(NFT_STATE_LAYER_MOD_HASH).get_tree_hash()
HASH_OF_STATE_LAYER_QUOTED_MOD_HASH = calculate_hash_of_quoted_mod_hash(NFT_STATE_LAYER_MOD_HASH)
NFT_OWNERSHIP_LAYER_HASH_HASH = Program.to(NFT_OWNERSHIP_LAYER_HASH).get_tree_hash()
HASH_OF_OWNERSHIP_LAYER_QUOTED_MOD_HASH = calculate_hash_of_quoted_mod_hash(NFT_OWNERSHIP_LAYER_HASH)
HASH_OF_TRANSFER_PROGRAM_QUOTED_MOD_HASH = calculate_hash_of_quoted_mod_hash(
    NFT_TRANSFER_PROGRAM_DEFAULT.get_tree_hash()
)


@dataclass(frozen=True, kw_only=True)
class DefaultMetadataUpdater(PuzzleBase):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("DefaultMetadataUpdater", None)

    @property
    def program(self) -> Program:
        return NFT_METADATA_UPDATER

    @property
    def tree_hash_optimized(self) -> bytes32:
        return NFT_METADATA_UPDATER_HASH

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> DefaultMetadataUpdater | None:
        if unknown_puzzle.tree_hash != DefaultMetadataUpdater().tree_hash:
            return None
        return DefaultMetadataUpdater()


@dataclass(frozen=True, kw_only=True)
class UpdateMetadataCondition(Condition):
    data_uri: str | None = None
    meta_uri: str | None = None
    license_uri: str | None = None
    other_update: tuple[str, str] | None = None
    metadata_updater: Puzzle = field(default_factory=DefaultMetadataUpdater)

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

        return Program.to([-24, self.metadata_updater.program, (key, uri)])

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

    @property
    def program(self) -> Program:
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


_T_Puzzle = TypeVar("_T_Puzzle", bound=Puzzle)
_T_MetadataUpdater = TypeVar("_T_MetadataUpdater", bound=Puzzle)


@dataclass(frozen=True, kw_only=True)
class MetadataLayer(PuzzleBase, Generic[_T_Puzzle, _T_MetadataUpdater]):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("MetadataLayer[_T_Puzzle, _T_MetadataUpdater]", None)

    inner_puzzle: _T_Puzzle
    metadata: Program
    metadata_updater: _T_MetadataUpdater

    @cached_property
    def metadata_hash(self) -> bytes32:
        return self.metadata.get_tree_hash()

    @property
    def program(self) -> Program:
        return NFT_STATE_LAYER_MOD.curry(
            NFT_STATE_LAYER_MOD_HASH, self.metadata, self.metadata_updater.tree_hash, self.inner_puzzle.program
        )

    @property
    def tree_hash_optimized(self) -> bytes32:
        return curry_and_treehash(
            HASH_OF_STATE_LAYER_QUOTED_MOD_HASH,
            NFT_STATE_LAYER_MOD_HASH_HASH,
            self.metadata_hash,
            Program.to(self.metadata_updater.tree_hash).get_tree_hash(),
            self.inner_puzzle.tree_hash,
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> MetadataLayer[UnknownPuzzle, UnknownPuzzle] | None:
        if unknown_puzzle.mod != NFT_STATE_LAYER_MOD or unknown_puzzle.curried_args is None:
            return None

        (_, metadata, metadata_updater_puzhash, inner_puzzle) = unknown_puzzle.curried_args

        return MetadataLayer(
            inner_puzzle=UnknownPuzzle(known_program=inner_puzzle),
            metadata=metadata,
            metadata_updater=UnknownPuzzle(known_tree_hash=bytes32(metadata_updater_puzhash.as_atom())),
        )


_T_InnerSolution = TypeVar("_T_InnerSolution", bound=Solution)


@dataclass(frozen=True)
class MetadataLayerSolution(Generic[_T_InnerSolution]):
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast("MetadataLayerSolution[_T_InnerSolution]", None)

    inner_solution: _T_InnerSolution

    @property
    def program(self) -> Program:
        return Program.to([self.inner_solution.program])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> MetadataLayerSolution[UnknownSolution] | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
        if len(list_of_values) != 1:
            return None
        return MetadataLayerSolution(inner_solution=UnknownSolution(program=list_of_values[0]))


@dataclass(frozen=True, kw_only=True)
class TransferProgramCondition(Condition):
    trade_prices_list: dict[bytes32, int]
    new_owner: bytes32 | None = None
    new_owner_inner_puzzle_hash: bytes32 | None = None

    def __post_init__(self) -> None:
        # Driver-only condition; fields are not streamable-serializable.
        return None

    def to_program(self) -> Program:
        return Program.to(
            [-10, self.new_owner, [[v, k] for k, v in self.trade_prices_list.items()], self.new_owner_inner_puzzle_hash]
        )

    @classmethod
    def from_program(cls, program: Program) -> Self:
        _, launcher_id, trade_prices_list, inner_puzzle_hash = program.as_iter()
        return cls(
            # Conditions are serialized as [price, puzzle_hash]
            trade_prices_list={
                bytes32(tp_tuple.at("rf").as_atom()): tp_tuple.at("f").as_int()
                for tp_tuple in trade_prices_list.as_iter()
            },
            new_owner=bytes32(launcher_id.as_atom()) if launcher_id != Program.NIL else None,
            new_owner_inner_puzzle_hash=bytes32(inner_puzzle_hash.as_atom())
            if inner_puzzle_hash != Program.NIL
            else None,
        )


@dataclass(frozen=True, kw_only=True)
class DefaultTransferProgram(PuzzleBase):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("DefaultTransferProgram", None)

    self_launcher_id: bytes32
    royalty_address: bytes32 | None
    royalty_basis_points: int
    struct_driver: ClassVar[type[SingletonStruct]] = SingletonStruct

    @property
    def program(self) -> Program:
        return NFT_TRANSFER_PROGRAM_DEFAULT.curry(
            self.struct_driver(launcher_id=self.self_launcher_id).to_program(),
            self.royalty_address,
            self.royalty_basis_points,
        )

    @property
    def tree_hash_optimized(self) -> bytes32:
        return curry_and_treehash(
            HASH_OF_TRANSFER_PROGRAM_QUOTED_MOD_HASH,
            self.struct_driver(launcher_id=self.self_launcher_id).struct_hash(),
            Program.to(self.royalty_address).get_tree_hash(),
            Program.to(self.royalty_basis_points).get_tree_hash(),
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> DefaultTransferProgram | None:
        if unknown_puzzle.mod != NFT_TRANSFER_PROGRAM_DEFAULT or unknown_puzzle.curried_args is None:
            return None

        (singleton_struct, royalty_address, royalty_basis_points) = unknown_puzzle.curried_args

        return DefaultTransferProgram(
            self_launcher_id=cls.struct_driver.from_program(singleton_struct).launcher_id,
            royalty_address=bytes32(royalty_address.as_atom()) if royalty_address != Program.NIL else None,
            royalty_basis_points=royalty_basis_points.as_int(),
        )


_T_TransferProgram = TypeVar("_T_TransferProgram", bound=Puzzle)


@dataclass(frozen=True, kw_only=True)
class OwnershipLayer(PuzzleBase, Generic[_T_Puzzle, _T_TransferProgram]):
    if TYPE_CHECKING:
        _protocol_check: ClassVar[Puzzle] = cast("OwnershipLayer[_T_Puzzle, _T_TransferProgram]", None)

    current_owner: bytes32 | None
    inner_puzzle: _T_Puzzle
    transfer_program: _T_TransferProgram

    @property
    def program(self) -> Program:
        return NFT_OWNERSHIP_LAYER.curry(
            NFT_OWNERSHIP_LAYER_HASH, self.current_owner, self.transfer_program.program, self.inner_puzzle.program
        )

    @property
    def tree_hash_optimized(self) -> bytes32:
        return curry_and_treehash(
            HASH_OF_OWNERSHIP_LAYER_QUOTED_MOD_HASH,
            NFT_OWNERSHIP_LAYER_HASH_HASH,
            Program.to(self.current_owner).get_tree_hash(),
            self.transfer_program.tree_hash,
            self.inner_puzzle.tree_hash,
        )

    @classmethod
    def match(cls, *, unknown_puzzle: UnknownPuzzle) -> OwnershipLayer[UnknownPuzzle, UnknownPuzzle] | None:
        if unknown_puzzle.mod != NFT_OWNERSHIP_LAYER or unknown_puzzle.curried_args is None:
            return None

        (_, current_owner, transfer_program, inner_puzzle) = unknown_puzzle.curried_args

        return OwnershipLayer(
            inner_puzzle=UnknownPuzzle(known_program=inner_puzzle),
            current_owner=bytes32(current_owner.as_atom()) if current_owner != Program.NIL else None,
            transfer_program=UnknownPuzzle(known_program=transfer_program),
        )


@dataclass(frozen=True)
class OwnershipLayerSolution(Generic[_T_InnerSolution]):
    if TYPE_CHECKING:
        _solution_protocol_check: ClassVar[Solution] = cast("OwnershipLayerSolution[_T_InnerSolution]", None)

    inner_solution: _T_InnerSolution

    @property
    def program(self) -> Program:
        return Program.to([self.inner_solution.program])

    @classmethod
    def match(cls, *, unknown_solution: UnknownSolution) -> OwnershipLayerSolution[UnknownSolution] | None:
        if unknown_solution.program.atom is not None:
            return None
        list_of_values = list(unknown_solution.program.as_iter())
        if len(list_of_values) != 1:
            return None
        return OwnershipLayerSolution(inner_solution=UnknownSolution(program=list_of_values[0]))


def create_full_puzzle_with_nft_puzzle(singleton_id: bytes32, inner_puzzle: Program) -> Program:
    if log.isEnabledFor(logging.DEBUG):
        log.debug("Creating full NFT puzzle with inner puzzle: \n%r\n%r", singleton_id, inner_puzzle.get_tree_hash())
    singleton_struct = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_PUZZLE_HASH)))

    full_puzzle = SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, inner_puzzle)
    if log.isEnabledFor(logging.DEBUG):
        log.debug("Created NFT full puzzle with inner: %s", full_puzzle.get_tree_hash())
    return full_puzzle


def create_full_puzzle(
    singleton_id: bytes32, metadata: Program, metadata_updater_puzhash: bytes32, inner_puzzle: Program
) -> Program:
    if log.isEnabledFor(logging.DEBUG):
        log.debug(
            "Creating full NFT puzzle with: \n%r\n%r\n%r\n%r",
            singleton_id,
            metadata.get_tree_hash(),
            metadata_updater_puzhash,
            inner_puzzle.get_tree_hash(),
        )
    singleton_struct = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (singleton_id, SINGLETON_LAUNCHER_PUZZLE_HASH)))
    singleton_inner_puzzle = MetadataLayer(
        metadata=metadata,
        metadata_updater=UnknownPuzzle(known_tree_hash=metadata_updater_puzhash),
        inner_puzzle=UnknownPuzzle(known_program=inner_puzzle),
    ).program

    full_puzzle = SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, singleton_inner_puzzle)
    if log.isEnabledFor(logging.DEBUG):
        log.debug("Created NFT full puzzle: %s", full_puzzle.get_tree_hash())
    return full_puzzle


async def get_nft_info_from_puzzle(nft_coin_info: NFTCoinInfo, config: dict[str, Any]) -> NFTInfo:
    """
    Extract NFT info from a full puzzle
    :param nft_coin_info NFTCoinInfo in local database
    :param config Wallet config
    :param ignore_size_limit Ignore the off-chain metadata loading size limit
    :return: NFTInfo
    """
    uncurried_nft: UncurriedNFT | None = UncurriedNFT.uncurry(*nft_coin_info.full_puzzle.uncurry())
    assert uncurried_nft is not None
    data_uris: list[str] = []

    for uri in uncurried_nft.data_uris.as_python():
        data_uris.append(str(uri, "utf-8"))
    meta_uris: list[str] = []
    for uri in uncurried_nft.meta_uris.as_python():
        meta_uris.append(str(uri, "utf-8"))
    license_uris: list[str] = []
    for uri in uncurried_nft.license_uris.as_python():
        license_uris.append(str(uri, "utf-8"))
    off_chain_metadata: str | None = None
    nft_info = NFTInfo(
        encode_puzzle_hash(uncurried_nft.singleton_launcher_id, prefix=AddressType.NFT.hrp(config=config)),
        uncurried_nft.singleton_launcher_id,
        nft_coin_info.coin.name(),
        nft_coin_info.latest_height,
        uncurried_nft.owner_did,
        uncurried_nft.trade_price_percentage,
        uncurried_nft.royalty_address,
        data_uris,
        uncurried_nft.data_hash.as_python(),
        meta_uris,
        uncurried_nft.meta_hash.as_python(),
        license_uris,
        uncurried_nft.license_hash.as_python(),
        uint64(uncurried_nft.edition_total.as_int()),
        uint64(uncurried_nft.edition_number.as_int()),
        uncurried_nft.metadata_updater_hash.as_python(),
        disassemble(uncurried_nft.metadata),
        nft_coin_info.mint_height,
        uncurried_nft.supports_did,
        uncurried_nft.p2_puzzle.get_tree_hash(),
        nft_coin_info.pending_transaction,
        nft_coin_info.minter_did,
        off_chain_metadata=off_chain_metadata,
    )
    return nft_info


def metadata_to_program(metadata: dict[bytes, Any]) -> Program:
    """
    Convert the metadata dict to a Chialisp program
    :param metadata: User defined metadata
    :return: Chialisp program
    """
    kv_list = []
    for key, value in metadata.items():
        kv_list.append((key, value))
    program: Program = Program.to(kv_list)
    return program


def nft_program_to_metadata(program: Program) -> dict[bytes, Any]:
    """
    Convert a program to a metadata dict
    :param program: Chialisp program contains the metadata
    :return: Metadata dict
    """
    metadata = {}
    for kv_pair in program.as_iter():
        metadata[kv_pair.first().as_atom()] = kv_pair.rest().as_python()
    return metadata


def prepend_value(key: bytes, value: Program, metadata: dict[bytes, Any]) -> None:
    """
    Prepend a value to a list in the metadata
    :param key: Key of the field
    :param value: Value want to add
    :param metadata: Metadata
    :return:
    """
    if value != Program.to(0):
        if metadata[key] == b"":
            metadata[key] = [value.as_python()]
        else:
            metadata[key].insert(0, value.as_python())


def update_metadata(metadata: Program, update_condition: Program) -> Program:
    """
    Apply conditions of metadata updater to the previous metadata
    :param metadata: Previous metadata
    :param update_condition: Update metadata conditions
    :return: Updated metadata
    """
    new_metadata: dict[bytes, Any] = nft_program_to_metadata(metadata)
    uri: Program = update_condition.rest().rest().first()
    prepend_value(uri.first().as_python(), uri.rest(), new_metadata)
    return metadata_to_program(new_metadata)


def get_metadata_and_phs(unft: UncurriedNFT, solution: SerializedProgram) -> tuple[Program, bytes32]:
    conditions = unft.p2_puzzle.run(unft.get_innermost_solution(Program.from_serialized(solution)))
    metadata = unft.metadata
    puzhash_for_derivation: bytes32 | None = None
    for condition in conditions.as_iter():
        if condition.list_len() < 2:
            # invalid condition
            continue
        condition_code = condition.first().as_int()
        log.debug("Checking condition code: %r", condition_code)
        if condition_code == -24:
            # metadata update
            metadata = update_metadata(metadata, condition)
            metadata = Program.to(metadata)
        elif condition_code == 51:
            atom = condition.rest().rest().first().as_int()

            if atom == 1:
                # destination puzhash
                if puzhash_for_derivation is not None:
                    # ignore duplicated create coin conditions
                    continue
                memo = bytes32(condition.at("rrrff").as_atom())
                puzhash_for_derivation = memo
                log.debug("Got back puzhash from solution: %s", puzhash_for_derivation)
    assert puzhash_for_derivation
    return metadata, puzhash_for_derivation


def recurry_nft_puzzle(unft: UncurriedNFT, solution: Program, new_inner_puzzle: Program) -> Program:
    log.debug("Generating NFT puzzle with ownership support: %s", disassemble(solution))
    conditions = unft.p2_puzzle.run(unft.get_innermost_solution(solution))
    new_did_id = unft.owner_did
    new_puzhash = None
    for condition in conditions.as_iter():
        if condition.first().as_int() == -10:
            # this is the change owner magic condition
            atom = condition.at("rf").atom
            if atom is None or atom == b"":
                new_did_id = None
            else:
                new_did_id = bytes32(atom)
        elif condition.first().as_int() == 51:
            new_puzhash = condition.at("rf").atom
    # assert new_puzhash and new_did_id
    log.debug(f"Found NFT puzzle details: {new_did_id!r} {new_puzhash!r}")
    assert unft.transfer_program
    return OwnershipLayer(
        current_owner=new_did_id,
        transfer_program=UnknownPuzzle(known_program=unft.transfer_program),
        inner_puzzle=UnknownPuzzle(known_program=new_inner_puzzle),
    ).program


def get_new_owner_did(unft: UncurriedNFT, solution: Program) -> Literal[b""] | bytes32 | None:
    conditions = unft.p2_puzzle.run(unft.get_innermost_solution(solution))
    new_did_id: Literal[b""] | bytes32 | None = None
    for condition in conditions.as_iter():
        if condition.first().as_int() == -10:
            # this is the change owner magic condition
            atom = condition.at("rf").as_atom()
            if atom == b"":
                new_did_id = b""
            else:
                new_did_id = bytes32(atom)
    return new_did_id
