from blspy import PrependSignature
from src.util.streamable import streamable
from src.util.ints import uint64
from src.types.sized_bytes import bytes32


@streamable
class BlockHeaderData:
    prev_header_hash: bytes32
    timestamp: uint64
    filter_hash: bytes32
    proof_of_space_hash: bytes32
    body_hash: bytes32
    extension_data: bytes32

    def is_valid(self):
        # TODO
        return True


@streamable
class BlockHeader:
    data: BlockHeaderData
    plotter_signature: PrependSignature

    def is_valid(self):
        return all(
            component.is_valid()
            for key in self.__slots__
            if (component := getattr(self, key, None)) is not None
        )

    @property
    def header_hash(self):
        return sha256(self.serialize()).digest()