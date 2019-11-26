from dataclasses import dataclass
from typing import List
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.peer_info import PeerInfo
from src.server.connection import NodeType
from src.util.cbor_message import cbor_message
from src.types.sized_bytes import bytes32
from src.util.ints import uint16, uint64


@dataclass(frozen=True)
@cbor_message
class StopNodeRequest:
    pass


@dataclass(frozen=True)
@cbor_message
class StopNodeResponse:
    pass


@dataclass(frozen=True)
@cbor_message
class GetConnectionsRequest:
    pass


@dataclass(frozen=True)
@cbor_message
class Connection:
    peer_info: PeerInfo
    node_type: NodeType
    node_id: bytes32


@dataclass(frozen=True)
@cbor_message
class GetConnectionsResponse:
    connections: List[Connection]


@dataclass(frozen=True)
@cbor_message
class AddConnectionRequest:
    host: str
    port: uint16


@dataclass(frozen=True)
@cbor_message
class AddConnectionResponse:
    pass


@dataclass(frozen=True)
@cbor_message
class GetBlockchainInfoRequest:
    pass


@dataclass(frozen=True)
@cbor_message
class GetBlockchainInfoResponse:
    lca_header_hash: bytes32
    next_difficulty: uint64
    next_ips: uint64
    tips_header_hashes: List[bytes32]


@dataclass(frozen=True)
@cbor_message
class GetBlockRequest:
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class GetBlockResponse:
    block: FullBlock


@dataclass(frozen=True)
@cbor_message
class GetHeaderBlockRequest:
    header_hash: bytes32


@dataclass(frozen=True)
@cbor_message
class GetHeaderBlockResponse:
    header_block: HeaderBlock
