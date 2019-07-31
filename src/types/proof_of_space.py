from blspy import PublicKey
from src.util.streamable import streamable, StreamableList
from src.util.ints import uint8


@streamable
class ProofOfSpace:
    pool_pubkey: PublicKey
    plot_pubkey: PublicKey
    size: uint8
    proof: StreamableList(uint8)
