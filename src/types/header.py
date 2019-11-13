from blspy import PrependSignature
from src.util.streamable import streamable, Streamable
from src.util.ints import uint64
from src.types.sized_bytes import bytes32
from dataclasses import dataclass


@dataclass(frozen=True)
@streamable
class HeaderData(Streamable):
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
    def header_hash(self):
        return self.get_hash()
