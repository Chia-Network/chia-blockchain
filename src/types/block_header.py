from blspy import PrependSignature
from src.util.streamable import streamable
from src.util.ints import uint64
from src.types.sized_bytes import bytes32


@streamable
class BlockHeaderData:
    previous_header_hash: bytes32
    timestamp: uint64
    filter_hash: bytes32
    proof_of_space_hash: bytes32
    body_hash: bytes32
    extension_data: bytes32


@streamable
class BlockHeader:
    data: BlockHeaderData
    plotter_signature: PrependSignature
