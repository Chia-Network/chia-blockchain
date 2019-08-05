from typing import List
from blspy import PublicKey
from src.util.streamable import streamable
from src.util.ints import uint8


@streamable
class ProofOfSpace:
    pool_pubkey: PublicKey
    plot_pubkey: PublicKey
    size: uint8
    proof: List[uint8]

    def is_valid(self):
        # TODO
        return True
