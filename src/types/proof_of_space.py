from typing import List, Optional
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

    _cached_quality = None

    def get_plot_seed(self) -> bytes32:
        return self.calculate_plot_seed(self.pool_pubkey, self.plot_pubkey)

    def verify_and_get_quality(self, challenge_hash: bytes32) -> Optional[bytes32]:
        if self._cached_quality:
            return self._cached_quality
        v: Verifier = Verifier()
        plot_seed: bytes32 = self.get_plot_seed()
        quality_str = v.validate_proof(plot_seed, self.size, challenge_hash,
                                       bytes(self.proof))
        if not quality_str:
            return None
        self._cached_quality: bytes32 = self.quality_str_to_quality(challenge_hash, quality_str)
        return self._cached_quality

    @staticmethod
    def calculate_plot_seed(pool_pubkey: PublicKey, plot_pubkey: PublicKey) -> bytes32:
        return bytes32(sha256(pool_pubkey.serialize() +
                              plot_pubkey.serialize()).digest())

    @staticmethod
    def quality_str_to_quality(challenge_hash: bytes32, quality_str: bytes) -> bytes32:
        return bytes32(sha256(challenge_hash + quality_str).digest())
