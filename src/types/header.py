from dataclasses import dataclass

from blspy import PrependSignature

from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from src.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class HeaderData(Streamable):
    height: uint32
    prev_header_hash: bytes32
    timestamp: uint64
    filter: bytes
    proof_of_space_hash: bytes32
    body_hash: bytes32
    weight: uint64
    total_iters: uint64
    additions_root: bytes32
    removals_root: bytes32


@dataclass(frozen=True)
@streamable
class Header(Streamable):
    data: HeaderData
    harvester_signature: PrependSignature

    @property
    def height(self):
        return self.data.height

    @property
    def header_hash(self):
        return self.get_hash()

    @property
    def prev_header_hash(self) -> bytes32:
        return self.data.prev_header_hash

    @property
    def weight(self) -> bytes32:
        return self.data.weight
