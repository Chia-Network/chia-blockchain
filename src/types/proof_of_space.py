import math
from dataclasses import dataclass
from typing import Optional

from bitstring import BitArray
from blspy import G1Element

from chiapos import Verifier

from src.types.sized_bytes import bytes32
from src.util.ints import uint8
from src.util.streamable import Streamable, streamable
from src.util.hash import std_hash
from src.consensus.constants import ConsensusConstants


@dataclass(frozen=True)
@streamable
class ProofOfSpace(Streamable):
    challenge_hash: bytes32
    pool_public_key: Optional[G1Element]  # Only one of these two should be present
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    size: uint8
    proof: bytes

    def get_plot_id(self) -> bytes32:
        assert self.pool_public_key is None or self.pool_contract_puzzle_hash is None
        if self.pool_public_key is None:
            return self.calculate_plot_id_ph(self.pool_contract_puzzle_hash, self.plot_public_key)
        return self.calculate_plot_id_pk(self.pool_public_key, self.plot_public_key)

    def verify_and_get_quality_string(
        self, constants: ConsensusConstants, original_challenge_hash: bytes32, signage_point: bytes32
    ) -> Optional[bytes32]:
        v: Verifier = Verifier()
        plot_id: bytes32 = self.get_plot_id()
        new_challenge: bytes32 = ProofOfSpace.calculate_new_challenge_hash(
            plot_id, original_challenge_hash, signage_point
        )

        if new_challenge != self.challenge_hash:
            return None

        if not ProofOfSpace.passes_plot_filter(constants, plot_id, original_challenge_hash, signage_point):
            return None

        quality_str = v.validate_proof(plot_id, self.size, self.challenge_hash, bytes(self.proof))

        if not quality_str:
            return None

        return quality_str

    @staticmethod
    def passes_plot_filter(
        constants: ConsensusConstants, plot_id: bytes32, challenge_hash: bytes32, signage_point: bytes32
    ) -> bool:
        plot_filter: BitArray = BitArray(
            ProofOfSpace.calculate_plot_filter_input(plot_id, challenge_hash, signage_point)
        )
        additional_signage_point_filter_bits = math.log2(constants.NUM_SPS_SUB_SLOT)
        assert additional_signage_point_filter_bits == math.ceil(additional_signage_point_filter_bits)
        return (
            plot_filter[: constants.NUMBER_ZERO_BITS_PLOT_FILTER + int(additional_signage_point_filter_bits)].uint == 0
        )

    @staticmethod
    def calculate_plot_filter_input(plot_id: bytes32, challenge_hash: bytes32, signage_point: bytes32) -> bytes32:
        return std_hash(plot_id + challenge_hash + signage_point)

    @staticmethod
    def calculate_new_challenge_hash(plot_id: bytes32, challenge_hash: bytes32, signage_point: bytes32) -> bytes32:
        return std_hash(ProofOfSpace.calculate_plot_filter_input(plot_id, challenge_hash, signage_point))

    @staticmethod
    def calculate_plot_id_pk(
        pool_public_key: G1Element,
        plot_public_key: G1Element,
    ) -> bytes32:
        return bytes32(std_hash(bytes(pool_public_key) + bytes(plot_public_key)))

    @staticmethod
    def calculate_plot_id_ph(
        pool_contract_puzzle_hash: bytes32,
        plot_public_key: G1Element,
    ) -> bytes32:
        return bytes32(std_hash(bytes(pool_contract_puzzle_hash) + bytes(plot_public_key)))

    @staticmethod
    def generate_plot_public_key(local_pk: G1Element, farmer_pk: G1Element) -> G1Element:
        return local_pk + farmer_pk
