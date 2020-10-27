from dataclasses import dataclass
from typing import Optional

from bitstring import BitArray
from blspy import G1Element

from chiapos import Verifier
from src.types.sized_bytes import bytes32
from src.util.ints import uint8
from src.util.streamable import Streamable, streamable
from src.util.hash import std_hash
from src.types.classgroup import ClassgroupElement
from src.consensus.constants import ConsensusConstants


@dataclass(frozen=True)
@streamable
class ProofOfSpace(Streamable):
    challenge_hash: bytes32
    pool_public_key: G1Element
    plot_public_key: G1Element
    size: uint8
    proof: bytes

    def get_plot_id(self) -> bytes32:
        return self.calculate_plot_id(self.pool_public_key, self.plot_public_key)

    def verify_and_get_quality_string(self, num_zero_bits: int) -> Optional[bytes32]:
        v: Verifier = Verifier()
        plot_id: bytes32 = self.get_plot_id()

        if not self.can_create_proof(plot_id, self.challenge_hash, num_zero_bits):
            return None

        quality_str = v.validate_proof(plot_id, self.size, self.challenge_hash, bytes(self.proof))

        if not quality_str:
            return None
        return quality_str

    @staticmethod
    def can_create_proof(
        constants: ConsensusConstants,
        plot_id: bytes32,
        challenge_hash: bytes32,
        icp_output: Optional[ClassgroupElement] = None,
    ) -> bool:
        # If icp_output is provided, both plot filters are checked. Otherwise only the first one is checked
        plot_filter_1 = BitArray(std_hash(bytes(plot_id) + bytes(challenge_hash)))
        if icp_output is None:
            return plot_filter_1[: constants.NUMBER_ZERO_BITS_CHALLENGE_SIG].uint == 0
        else:
            plot_filter_2 = BitArray(std_hash(bytes(plot_id) + bytes(icp_output)))
            return (
                plot_filter_1[: constants.NUMBER_ZERO_BITS_CHALLENGE_SIG].uint == 0
                and plot_filter_2[: constants.NUMBER_ZERO_BITS_ICP_SIG].uint == 0
            )

    @staticmethod
    def calculate_plot_id(
        pool_public_key: G1Element,
        plot_public_key: G1Element,
    ) -> bytes32:
        return bytes32(std_hash(bytes(pool_public_key) + bytes(plot_public_key)))

    @staticmethod
    def generate_plot_public_key(local_pk: G1Element, farmer_pk: G1Element) -> G1Element:
        return local_pk + farmer_pk
