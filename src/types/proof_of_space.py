from blspy import PublicKey
from ..util.streamable import streamable
from ..util.ints import uint8


@streamable
class ProofOfSpace:
    pool_pubkey: PublicKey
    plot_pubkey: PublicKey
    size: uint8
    proof: bytes
