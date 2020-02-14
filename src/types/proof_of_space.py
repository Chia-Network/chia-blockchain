from dataclasses import dataclass
from typing import Optional

from blspy import PublicKey

from chiapos import Verifier
from src.types.sized_bytes import bytes32
from src.util.ints import uint8
from src.util.streamable import Streamable, streamable
from src.util.hash import std_hash


@dataclass(frozen=True)
@streamable
class ProofOfSpace(Streamable):
    challenge_hash: bytes32
    pool_pubkey: PublicKey
    plot_pubkey: PublicKey
    size: uint8
    proof: bytes

    def get_plot_seed(self) -> bytes32:
        return self.calculate_plot_seed(self.pool_pubkey, self.plot_pubkey)

    def verify_and_get_quality_string(self) -> Optional[bytes32]:
        v: Verifier = Verifier()
        plot_seed: bytes32 = self.get_plot_seed()
        quality_str = v.validate_proof(
            plot_seed, self.size, self.challenge_hash, bytes(self.proof)
        )
        if not quality_str:
            return None
        return quality_str

    @staticmethod
    def calculate_plot_seed(pool_pubkey: PublicKey, plot_pubkey: PublicKey) -> bytes32:
        return bytes32(std_hash(bytes(pool_pubkey) + bytes(plot_pubkey)))
