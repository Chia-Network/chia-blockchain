from blspy import PublicKey
from typing import Any
from ..util.streamable import streamable
from ..util.ints import uint8


@streamable
class ProofOfSpace:
    pool_pubkey: PublicKey
    plot_pubkey: PublicKey
    size: uint8
    proof: bytes

    @classmethod
    def parse(cls: Any, f):
        return cls(PublicKey.from_bytes(f.read(PublicKey.PUBLIC_KEY_SIZE)),
                   PublicKey.from_bytes(f.read(PublicKey.PUBLIC_KEY_SIZE)),
                   uint8.parse(f),
                   f.read())
