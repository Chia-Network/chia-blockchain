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
    farmer_puzzle_hash: bytes32
    pool_puzzle_hash: bytes32
    plot_pubkey: PublicKey
    size: uint8
    proof: bytes

    def get_plot_seed(self) -> bytes32:
        return self.calculate_plot_seed(
            self.farmer_puzzle_hash, self.pool_puzzle_hash, self.plot_pubkey
        )

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
    def calculate_plot_seed(
        farmer_puzzle_hash: bytes32,
        pool_puzzle_hash: bytes32,
        plot_public_key: PublicKey,
    ) -> bytes32:
        return bytes32(
            std_hash(farmer_puzzle_hash + pool_puzzle_hash + bytes(plot_public_key))
        )

    @staticmethod
    def generate_plot_pubkey(
        harvester_pk: PublicKey, farmer_pk: PublicKey
    ) -> PublicKey:
        # Insecure aggregation is fine here, since the harvester can choose any public key
        # she wants. Insecure refers to suceptibility to the rogue pk attack:
        # https://crypto.stanford.edu/~dabo/pubs/papers/BLSmultisig.html
        # This however, is not relevant since the consensus will just verify the 2/2 signature as
        # if it was a normal signature.
        return PublicKey.aggregate_insecure([harvester_pk, farmer_pk])
