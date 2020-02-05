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
    filter_hash: bytes32
    proof_of_space_hash: bytes32
    body_hash: bytes32
    extension_data: bytes32


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
