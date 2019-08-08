from typing import List
from hashlib import sha256
from chiapos import Verifier
from blspy import PublicKey
from src.util.streamable import streamable
from src.util.ints import uint8
from src.types.sized_bytes import bytes32


@streamable
class ProofOfSpace:
    pool_pubkey: PublicKey
    plot_pubkey: PublicKey
    size: uint8
    proof: List[uint8]

    def is_valid(self):
        # TODO
        return True

    def get_plot_seed(self) -> bytes32:
        return self.calculate_plot_seed(self.pool_pubkey, self.plot_pubkey)

    def verify_and_get_quality(self, challenge_hash: bytes32) -> bytes32:
        v: Verifier = Verifier()
        plot_seed: bytes32 = self.get_plot_seed()
        quality_str = v.validate_proof(plot_seed, self.size, challenge_hash,
                                       bytes(self.proof))
        return sha256(challenge_hash + quality_str).digest()

    @staticmethod
    def calculate_plot_seed(pool_pubkey: PublicKey, plot_pubkey: PublicKey) -> bytes32:
        return bytes32(sha256(pool_pubkey.serialize() +
                              plot_pubkey.serialize()).digest())
