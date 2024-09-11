from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type, Union

import aiosqlite
from typing_extensions import final

from chia.data_layer.data_layer_errors import ProofIntegrityError
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.db_wrapper import DBWrapper2
from chia.util.ints import uint8, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.db_wallet.db_wallet_puzzles import create_host_fullpuz

if TYPE_CHECKING:
    from chia.data_layer.data_store import DataStore
    from chia.wallet.wallet_node import WalletNode


def internal_hash(left_hash: bytes32, right_hash: bytes32) -> bytes32:
    # see test for the definition this is optimized from
    return bytes32(sha256(b"\2" + left_hash + right_hash).digest())


def calculate_internal_hash(hash: bytes32, other_hash_side: Side, other_hash: bytes32) -> bytes32:
    if other_hash_side == Side.LEFT:
        return internal_hash(left_hash=other_hash, right_hash=hash)
    elif other_hash_side == Side.RIGHT:
        return internal_hash(left_hash=hash, right_hash=other_hash)

    raise Exception(f"Invalid side: {other_hash_side!r}")


def leaf_hash(key: bytes, value: bytes) -> bytes32:
    # see test for the definition this is optimized from
    return bytes32(sha256(b"\2" + sha256(b"\1" + key).digest() + sha256(b"\1" + value).digest()).digest())


def key_hash(key: bytes) -> bytes32:
    # see test for the definition this is optimized from
    return bytes32(sha256(b"\1" + key).digest())


@dataclasses.dataclass(frozen=True)
class PaginationData:
    total_pages: int
    total_bytes: int
    hashes: List[bytes32]


def get_hashes_for_page(page: int, lengths: Dict[bytes32, int], max_page_size: int) -> PaginationData:
    current_page = 0
    current_page_size = 0
    total_bytes = 0
    hashes: List[bytes32] = []
    for hash, length in sorted(lengths.items(), key=lambda x: (-x[1], x[0])):
        if length > max_page_size:
            raise RuntimeError(
                f"Cannot paginate data, item size is larger than max page size: {length} {max_page_size}"
            )
        total_bytes += length
        if current_page_size + length <= max_page_size:
            current_page_size += length
        else:
            current_page += 1
            current_page_size = length
        if current_page == page:
            hashes.append(hash)

    return PaginationData(current_page + 1, total_bytes, hashes)


async def _debug_dump(db: DBWrapper2, description: str = "") -> None:
    async with db.reader() as reader:
        cursor = await reader.execute("SELECT name FROM sqlite_master WHERE type='table';")
        print("-" * 50, description, flush=True)
        for [name] in await cursor.fetchall():
            cursor = await reader.execute(f"SELECT * FROM {name}")
            print(f"\n -- {name} ------", flush=True)
            async for row in cursor:
                print(f"        {dict(row)}")


async def _dot_dump(
    data_store: DataStore,
    store_id: bytes32,
    root_hash: bytes32,
) -> str:
    terminal_nodes = await data_store.get_keys_values(store_id=store_id, root_hash=root_hash)
    internal_nodes = await data_store.get_internal_nodes(store_id=store_id, root_hash=root_hash)

    n = 8

    dot_nodes: List[str] = []
    dot_connections: List[str] = []
    dot_pair_boxes: List[str] = []

    for terminal_node in terminal_nodes:
        hash = terminal_node.hash.hex()
        key = terminal_node.key.hex()
        value = terminal_node.value.hex()
        dot_nodes.append(f"""node_{hash} [shape=box, label="{hash[:n]}\\nkey: {key}\\nvalue: {value}"];""")

    for internal_node in internal_nodes:
        hash = internal_node.hash.hex()
        left = internal_node.left_hash.hex()
        right = internal_node.right_hash.hex()
        dot_nodes.append(f"""node_{hash} [label="{hash[:n]}"]""")
        dot_connections.append(f"""node_{hash} -> node_{left} [label="L"];""")
        dot_connections.append(f"""node_{hash} -> node_{right} [label="R"];""")
        dot_pair_boxes.append(
            f"node [shape = box]; {{rank = same; node_{left}->node_{right}[style=invis]; rankdir = LR}}"
        )

    lines = [
        "digraph {",
        *dot_nodes,
        *dot_connections,
        *dot_pair_boxes,
        "}",
    ]

    return "\n".join(lines)


def row_to_node(row: aiosqlite.Row) -> Node:
    cls = node_type_to_class[row["node_type"]]
    return cls.from_row(row=row)


class Status(IntEnum):
    PENDING = 1
    COMMITTED = 2
    PENDING_BATCH = 3


class NodeType(IntEnum):
    INTERNAL = 1
    TERMINAL = 2


@final
class Side(IntEnum):
    LEFT = 0
    RIGHT = 1

    def other(self) -> Side:
        if self == Side.LEFT:
            return Side.RIGHT

        return Side.LEFT

    @classmethod
    def unmarshal(cls, o: str) -> Side:
        return getattr(cls, o.upper())  # type: ignore[no-any-return]

    def marshal(self) -> str:
        return self.name.lower()


class OperationType(IntEnum):
    INSERT = 0
    DELETE = 1


class CommitState(IntEnum):
    OPEN = 0
    FINALIZED = 1
    ROLLED_BACK = 2


Node = Union["TerminalNode", "InternalNode"]


@final
@dataclass(frozen=True)
class TerminalNode:
    hash: bytes32
    # generation: int
    key: bytes
    value: bytes

    # left for now for interface back-compat even though it is constant
    atom: None = field(init=False, default=None)

    @classmethod
    def from_key_value(cls, key: bytes, value: bytes) -> TerminalNode:
        return cls(
            hash=leaf_hash(key=key, value=value),
            key=key,
            value=value,
        )

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> TerminalNode:
        return cls(
            hash=bytes32(row["hash"]),
            # generation=row["generation"],
            key=row["key"],
            value=row["value"],
        )


@final
@dataclass(frozen=True)
class ProofOfInclusionLayer:
    other_hash_side: Side
    other_hash: bytes32
    combined_hash: bytes32

    @classmethod
    def from_internal_node(
        cls,
        internal_node: InternalNode,
        traversal_child_hash: bytes32,
    ) -> ProofOfInclusionLayer:
        return ProofOfInclusionLayer(
            other_hash_side=internal_node.other_child_side(hash=traversal_child_hash),
            other_hash=internal_node.other_child_hash(hash=traversal_child_hash),
            combined_hash=internal_node.hash,
        )

    @classmethod
    def from_hashes(cls, primary_hash: bytes32, other_hash_side: Side, other_hash: bytes32) -> ProofOfInclusionLayer:
        combined_hash = calculate_internal_hash(
            hash=primary_hash,
            other_hash_side=other_hash_side,
            other_hash=other_hash,
        )

        return cls(other_hash_side=other_hash_side, other_hash=other_hash, combined_hash=combined_hash)


other_side_to_bit = {Side.LEFT: 1, Side.RIGHT: 0}


@dataclass(frozen=True)
class ProofOfInclusion:
    node_hash: bytes32
    # children before parents
    layers: List[ProofOfInclusionLayer]

    @property
    def root_hash(self) -> bytes32:
        if len(self.layers) == 0:
            return self.node_hash

        return self.layers[-1].combined_hash

    def sibling_sides_integer(self) -> int:
        return sum(other_side_to_bit[layer.other_hash_side] << index for index, layer in enumerate(self.layers))

    def sibling_hashes(self) -> List[bytes32]:
        return [layer.other_hash for layer in self.layers]

    def as_program(self) -> Program:
        return Program.to([self.sibling_sides_integer(), self.sibling_hashes()])

    def valid(self) -> bool:
        existing_hash = self.node_hash

        for layer in self.layers:
            calculated_hash = calculate_internal_hash(
                hash=existing_hash, other_hash_side=layer.other_hash_side, other_hash=layer.other_hash
            )

            if calculated_hash != layer.combined_hash:
                return False

            existing_hash = calculated_hash

        if existing_hash != self.root_hash:
            return False

        return True


@final
@dataclass(frozen=True)
class InternalNode:
    hash: bytes32
    # generation: int
    left_hash: bytes32
    right_hash: bytes32

    left: Optional[Node] = None
    right: Optional[Node] = None

    @classmethod
    def from_child_nodes(cls, left: Node, right: Node) -> InternalNode:
        return cls(
            hash=internal_hash(left_hash=left.hash, right_hash=right.hash),
            left_hash=left.hash,
            right_hash=right.hash,
            left=left,
            right=right,
        )

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> InternalNode:
        return cls(
            hash=bytes32(row["hash"]),
            # generation=row["generation"],
            left_hash=bytes32(row["left"]),
            right_hash=bytes32(row["right"]),
        )

    def other_child_hash(self, hash: bytes32) -> bytes32:
        if self.left_hash == hash:
            return self.right_hash
        elif self.right_hash == hash:
            return self.left_hash

        # TODO: real exception considerations
        raise Exception("provided hash not present")

    def other_child_side(self, hash: bytes32) -> Side:
        if self.left_hash == hash:
            return Side.RIGHT
        elif self.right_hash == hash:
            return Side.LEFT

        # TODO: real exception considerations
        raise Exception("provided hash not present")


class Unspecified(Enum):
    # not beautiful, improve when a better way is known
    # https://github.com/python/typing/issues/236#issuecomment-229515556

    instance = None

    def __repr__(self) -> str:
        return "Unspecified"


unspecified = Unspecified.instance


@dataclass(frozen=True)
class Root:
    store_id: bytes32
    node_hash: Optional[bytes32]
    generation: int
    status: Status

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> Root:
        raw_node_hash = row["node_hash"]
        if raw_node_hash is None:
            node_hash = None
        else:
            node_hash = bytes32(raw_node_hash)

        return cls(
            store_id=bytes32(row["tree_id"]),
            node_hash=node_hash,
            generation=row["generation"],
            status=Status(row["status"]),
        )

    def to_row(self) -> Dict[str, Any]:
        return {
            "tree_id": self.store_id,
            "node_hash": self.node_hash,
            "generation": self.generation,
            "status": self.status.value,
        }

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> Root:
        return cls(
            store_id=bytes32.from_hexstr(marshalled["tree_id"]),
            node_hash=None if marshalled["node_hash"] is None else bytes32.from_hexstr(marshalled["node_hash"]),
            generation=marshalled["generation"],
            status=Status(marshalled["status"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "tree_id": self.store_id.hex(),
            "node_hash": None if self.node_hash is None else self.node_hash.hex(),
            "generation": self.generation,
            "status": self.status.value,
        }


node_type_to_class: Dict[NodeType, Union[Type[InternalNode], Type[TerminalNode]]] = {
    NodeType.INTERNAL: InternalNode,
    NodeType.TERMINAL: TerminalNode,
}


@dataclass(frozen=True)
class ServerInfo:
    url: str
    num_consecutive_failures: int
    ignore_till: int


@dataclass(frozen=True)
class Subscription:
    store_id: bytes32
    servers_info: List[ServerInfo]


@dataclass(frozen=True)
class DiffData:
    type: OperationType
    key: bytes
    value: bytes


@streamable
@dataclass(frozen=True)
class SerializedNode(Streamable):
    is_terminal: bool
    value1: bytes
    value2: bytes


@final
@dataclasses.dataclass(frozen=True)
class KeyValue:
    key: bytes
    value: bytes

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> KeyValue:
        return cls(
            key=hexstr_to_bytes(marshalled["key"]),
            value=hexstr_to_bytes(marshalled["value"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "key": self.key.hex(),
            "value": self.value.hex(),
        }


@dataclasses.dataclass(frozen=True)
class OfferStore:
    store_id: bytes32
    inclusions: Tuple[KeyValue, ...]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> OfferStore:
        return cls(
            store_id=bytes32.from_hexstr(marshalled["store_id"]),
            inclusions=tuple(KeyValue.unmarshal(key_value) for key_value in marshalled["inclusions"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "store_id": self.store_id.hex(),
            "inclusions": [key_value.marshal() for key_value in self.inclusions],
        }


@dataclasses.dataclass(frozen=True)
class Layer:
    # This class is similar to chia.data_layer.data_layer_util.ProofOfInclusionLayer
    # but is being retained for now to keep the API schema definition localized here.

    other_hash_side: Side
    other_hash: bytes32
    combined_hash: bytes32

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> Layer:
        return cls(
            other_hash_side=Side.unmarshal(marshalled["other_hash_side"]),
            other_hash=bytes32.from_hexstr(marshalled["other_hash"]),
            combined_hash=bytes32.from_hexstr(marshalled["combined_hash"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "other_hash_side": self.other_hash_side.marshal(),
            "other_hash": self.other_hash.hex(),
            "combined_hash": self.combined_hash.hex(),
        }


@dataclasses.dataclass(frozen=True)
class MakeOfferRequest:
    maker: Tuple[OfferStore, ...]
    taker: Tuple[OfferStore, ...]
    fee: Optional[uint64]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> MakeOfferRequest:
        return cls(
            maker=tuple(OfferStore.unmarshal(offer_store) for offer_store in marshalled["maker"]),
            taker=tuple(OfferStore.unmarshal(offer_store) for offer_store in marshalled["taker"]),
            fee=None if marshalled["fee"] is None else uint64(marshalled["fee"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "maker": [offer_store.marshal() for offer_store in self.maker],
            "taker": [offer_store.marshal() for offer_store in self.taker],
            "fee": None if self.fee is None else int(self.fee),
        }


@dataclasses.dataclass(frozen=True)
class Proof:
    key: bytes
    value: bytes
    node_hash: bytes32
    layers: Tuple[Layer, ...]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> Proof:
        return cls(
            key=hexstr_to_bytes(marshalled["key"]),
            value=hexstr_to_bytes(marshalled["value"]),
            node_hash=bytes32.from_hexstr(marshalled["node_hash"]),
            layers=tuple(Layer.unmarshal(layer) for layer in marshalled["layers"]),
        )

    def root(self) -> bytes32:
        if len(self.layers) == 0:
            return self.node_hash

        return self.layers[-1].combined_hash

    def marshal(self) -> Dict[str, Any]:
        return {
            "key": self.key.hex(),
            "value": self.value.hex(),
            "node_hash": self.node_hash.hex(),
            "layers": [layer.marshal() for layer in self.layers],
        }


@dataclasses.dataclass(frozen=True)
class StoreProofs:
    store_id: bytes32
    proofs: Tuple[Proof, ...]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> StoreProofs:
        return cls(
            store_id=bytes32.from_hexstr(marshalled["store_id"]),
            proofs=tuple(Proof.unmarshal(proof) for proof in marshalled["proofs"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "store_id": self.store_id.hex(),
            "proofs": [proof.marshal() for proof in self.proofs],
        }


@dataclasses.dataclass(frozen=True)
class Offer:
    trade_id: bytes
    offer: bytes
    taker: Tuple[OfferStore, ...]
    maker: Tuple[StoreProofs, ...]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> Offer:
        return cls(
            trade_id=bytes32.from_hexstr(marshalled["trade_id"]),
            offer=hexstr_to_bytes(marshalled["offer"]),
            taker=tuple(OfferStore.unmarshal(offer_store) for offer_store in marshalled["taker"]),
            maker=tuple(StoreProofs.unmarshal(store_proof) for store_proof in marshalled["maker"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id.hex(),
            "offer": self.offer.hex(),
            "taker": [offer_store.marshal() for offer_store in self.taker],
            "maker": [store_proofs.marshal() for store_proofs in self.maker],
        }


@dataclasses.dataclass(frozen=True)
class MakeOfferResponse:
    success: bool
    offer: Offer

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> MakeOfferResponse:
        return cls(
            success=marshalled["success"],
            offer=Offer.unmarshal(marshalled["offer"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "offer": self.offer.marshal(),
        }


@dataclasses.dataclass(frozen=True)
class TakeOfferRequest:
    offer: Offer
    fee: Optional[uint64]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> TakeOfferRequest:
        return cls(
            offer=Offer.unmarshal(marshalled["offer"]),
            fee=None if marshalled["fee"] is None else uint64(marshalled["fee"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "offer": self.offer.marshal(),
            "fee": None if self.fee is None else int(self.fee),
        }


@dataclasses.dataclass(frozen=True)
class TakeOfferResponse:
    success: bool
    trade_id: bytes32

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> TakeOfferResponse:
        return cls(
            success=marshalled["success"],
            trade_id=bytes32.from_hexstr(marshalled["trade_id"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "trade_id": self.trade_id.hex(),
        }


@final
@dataclasses.dataclass(frozen=True)
class VerifyOfferResponse:
    success: bool
    valid: bool
    error: Optional[str] = None
    fee: Optional[uint64] = None

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> VerifyOfferResponse:
        return cls(
            success=marshalled["success"],
            valid=marshalled["valid"],
            error=marshalled["error"],
            fee=None if marshalled["fee"] is None else uint64(marshalled["fee"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "valid": self.valid,
            "error": self.error,
            "fee": None if self.fee is None else int(self.fee),
        }


@dataclasses.dataclass(frozen=True)
class CancelOfferRequest:
    trade_id: bytes32
    # cancel on chain (secure) vs. just locally
    secure: bool
    fee: Optional[uint64]

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> CancelOfferRequest:
        return cls(
            trade_id=bytes32.from_hexstr(marshalled["trade_id"]),
            secure=marshalled["secure"],
            fee=None if marshalled["fee"] is None else uint64(marshalled["fee"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id.hex(),
            "secure": self.secure,
            "fee": None if self.fee is None else int(self.fee),
        }


@dataclasses.dataclass(frozen=True)
class CancelOfferResponse:
    success: bool

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> CancelOfferResponse:
        return cls(
            success=marshalled["success"],
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "success": self.success,
        }


@final
@dataclasses.dataclass(frozen=True)
class ClearPendingRootsRequest:
    store_id: bytes32

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> ClearPendingRootsRequest:
        return cls(
            store_id=bytes32.from_hexstr(marshalled["store_id"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "store_id": self.store_id.hex(),
        }


@final
@dataclasses.dataclass(frozen=True)
class ClearPendingRootsResponse:
    success: bool

    root: Optional[Root]
    # store_id: bytes32
    # node_hash: Optional[bytes32]
    # generation: int
    # status: Status

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> ClearPendingRootsResponse:
        return cls(
            success=marshalled["success"],
            root=None if marshalled["root"] is None else Root.unmarshal(marshalled["root"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "root": None if self.root is None else self.root.marshal(),
        }


@dataclasses.dataclass(frozen=True)
class SyncStatus:
    root_hash: bytes32
    generation: int
    target_root_hash: bytes32
    target_generation: int


@final
@dataclasses.dataclass(frozen=True)
class PluginRemote:
    url: str
    # repr=False to avoid leaking secrets
    headers: Dict[str, str] = dataclasses.field(default_factory=dict, hash=False, repr=False)

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> PluginRemote:
        return cls(
            url=marshalled["url"],
            headers=marshalled.get("headers", {}),
        )


@dataclasses.dataclass(frozen=True)
class PluginStatus:
    uploaders: Dict[str, Dict[str, Any]]
    downloaders: Dict[str, Dict[str, Any]]

    def marshal(self) -> Dict[str, Any]:
        return {
            "plugin_status": {
                "uploaders": self.uploaders,
                "downloaders": self.downloaders,
            }
        }


@dataclasses.dataclass(frozen=True)
class InsertResult:
    node_hash: bytes32
    root: Root


@dataclasses.dataclass(frozen=True)
class UnsubscribeData:
    store_id: bytes32
    retain_data: bool


@dataclasses.dataclass(frozen=True)
class KeysValuesCompressed:
    keys_values_hashed: Dict[bytes32, bytes32]
    key_hash_to_length: Dict[bytes32, int]
    leaf_hash_to_length: Dict[bytes32, int]
    root_hash: Optional[bytes32]


@dataclasses.dataclass(frozen=True)
class KeysPaginationData:
    total_pages: int
    total_bytes: int
    keys: List[bytes]
    root_hash: Optional[bytes32]


@dataclasses.dataclass(frozen=True)
class KeysValuesPaginationData:
    total_pages: int
    total_bytes: int
    keys_values: List[TerminalNode]
    root_hash: Optional[bytes32]


@dataclasses.dataclass(frozen=True)
class KVDiffPaginationData:
    total_pages: int
    total_bytes: int
    kv_diff: List[DiffData]


#
# GetProof and VerifyProof support classes
#
@streamable
@dataclasses.dataclass(frozen=True)
class ProofLayer(Streamable):
    # This class is basically Layer but streamable
    other_hash_side: uint8
    other_hash: bytes32
    combined_hash: bytes32


@streamable
@dataclasses.dataclass(frozen=True)
class HashOnlyProof(Streamable):
    key_clvm_hash: bytes32
    value_clvm_hash: bytes32
    node_hash: bytes32
    layers: List[ProofLayer]

    def root(self) -> bytes32:
        if len(self.layers) == 0:
            return self.node_hash
        return self.layers[-1].combined_hash

    @classmethod
    def from_key_value(cls, key: bytes, value: bytes, node_hash: bytes32, layers: List[ProofLayer]) -> HashOnlyProof:
        return cls(
            key_clvm_hash=Program.to(key).get_tree_hash(),
            value_clvm_hash=Program.to(value).get_tree_hash(),
            node_hash=node_hash,
            layers=layers,
        )


@streamable
@dataclasses.dataclass(frozen=True)
class KeyValueHashes(Streamable):
    key_clvm_hash: bytes32
    value_clvm_hash: bytes32


@streamable
@dataclasses.dataclass(frozen=True)
class ProofResultInclusions(Streamable):
    store_id: bytes32
    inclusions: List[KeyValueHashes]


@streamable
@dataclasses.dataclass(frozen=True)
class GetProofRequest(Streamable):
    store_id: bytes32
    keys: List[bytes]


@streamable
@dataclasses.dataclass(frozen=True)
class StoreProofsHashes(Streamable):
    store_id: bytes32
    proofs: List[HashOnlyProof]


@streamable
@dataclasses.dataclass(frozen=True)
class DLProof(Streamable):
    store_proofs: StoreProofsHashes
    coin_id: bytes32
    inner_puzzle_hash: bytes32


@streamable
@dataclasses.dataclass(frozen=True)
class GetProofResponse(Streamable):
    proof: DLProof
    success: bool


@streamable
@dataclasses.dataclass(frozen=True)
class VerifyProofResponse(Streamable):
    verified_clvm_hashes: ProofResultInclusions
    current_root: bool
    success: bool


def dl_verify_proof_internal(dl_proof: DLProof, puzzle_hash: bytes32) -> List[KeyValueHashes]:
    """Verify a proof of inclusion for a DL singleton"""

    verified_keys: List[KeyValueHashes] = []

    for reference_proof in dl_proof.store_proofs.proofs:
        inner_puz_hash = dl_proof.inner_puzzle_hash
        host_fullpuz_program = create_host_fullpuz(
            inner_puz_hash, reference_proof.root(), dl_proof.store_proofs.store_id
        )
        expected_puzzle_hash = host_fullpuz_program.get_tree_hash_precalc(inner_puz_hash)

        if puzzle_hash != expected_puzzle_hash:
            raise ProofIntegrityError(
                "Invalid Proof: incorrect puzzle hash: expected:"
                f"{expected_puzzle_hash.hex()} received: {puzzle_hash.hex()}"
            )

        proof = ProofOfInclusion(
            node_hash=reference_proof.node_hash,
            layers=[
                ProofOfInclusionLayer(
                    other_hash_side=Side(layer.other_hash_side),
                    other_hash=layer.other_hash,
                    combined_hash=layer.combined_hash,
                )
                for layer in reference_proof.layers
            ],
        )

        leaf_hash = internal_hash(left_hash=reference_proof.key_clvm_hash, right_hash=reference_proof.value_clvm_hash)
        if leaf_hash != proof.node_hash:
            raise ProofIntegrityError("Invalid Proof: node hash does not match key and value")

        if not proof.valid():
            raise ProofIntegrityError("Invalid Proof: invalid proof of inclusion found")

        verified_keys.append(
            KeyValueHashes(key_clvm_hash=reference_proof.key_clvm_hash, value_clvm_hash=reference_proof.value_clvm_hash)
        )

    return verified_keys


async def dl_verify_proof(
    request: Dict[str, Any],
    wallet_node: WalletNode,
    peer: WSChiaConnection,
) -> Dict[str, Any]:
    """Verify a proof of inclusion for a DL singleton"""

    dlproof = DLProof.from_json_dict(request)

    coin_id = dlproof.coin_id
    coin_states = await wallet_node.get_coin_state([coin_id], peer=peer)
    if len(coin_states) == 0:
        raise ProofIntegrityError(f"Invalid Proof: No DL singleton found at coin id: {coin_id.hex()}")

    verified_keys = dl_verify_proof_internal(dlproof, coin_states[0].coin.puzzle_hash)

    response = VerifyProofResponse(
        verified_clvm_hashes=ProofResultInclusions(dlproof.store_proofs.store_id, verified_keys),
        success=True,
        current_root=coin_states[0].spent_height is None,
    )
    return response.to_json_dict()
