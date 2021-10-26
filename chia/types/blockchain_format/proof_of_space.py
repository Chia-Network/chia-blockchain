import copy
import logging
from dataclasses import dataclass
from typing import Optional

from bitstring import BitArray
from blspy import AugSchemeMPL, G1Element, PrivateKey
from chiapos import Verifier

from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.consensus.constants import ConsensusConstants
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.hash import std_hash
from chia.util.ints import uint8
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
@streamable
class ProofOfSpace(Streamable):
    challenge: bytes32
    pool_public_key: Optional[G1Element]  # Only one of these two should be present
    pool_contract_puzzle_hash: Optional[bytes32]
    local_public_key: G1Element
    size: uint8
    proof: bytes
    farmer_public_key: G1Element

    @property
    def plot_public_key(self):
        return ProofOfSpace.generate_plot_public_key(
            self.local_public_key, self.farmer_public_key, self.pool_contract_puzzle_hash is not None
        )

    def to_legacy(self):
        if self.farmer_public_key is not None:
            return ProofOfSpace(
                self.challenge,
                self.pool_public_key,
                self.pool_contract_puzzle_hash,
                self.plot_public_key,
                self.size,
                self.proof,
            )
        else:
            return copy.copy(self)

    def get_plot_id(self) -> bytes32:
        assert self.pool_public_key is None or self.pool_contract_puzzle_hash is None
        if self.pool_public_key is None:
            return self.calculate_plot_id_ph(self.pool_contract_puzzle_hash, self.plot_public_key)
        return self.calculate_plot_id_pk(self.pool_public_key, self.plot_public_key)

    def verify_and_get_quality_string(
        self,
        constants: ConsensusConstants,
        original_challenge_hash: bytes32,
        signage_point: bytes32,
    ) -> Optional[bytes32]:
        # Exactly one of (pool_public_key, pool_contract_puzzle_hash) must not be None
        if (self.pool_public_key is None) and (self.pool_contract_puzzle_hash is None):
            log.error("Fail 1")
            return None
        if (self.pool_public_key is not None) and (self.pool_contract_puzzle_hash is not None):
            log.error("Fail 2")
            return None
        if self.size < constants.MIN_PLOT_SIZE:
            log.error("Fail 3")
            return None
        if self.size > constants.MAX_PLOT_SIZE:
            log.error("Fail 4")
            return None
        plot_id: bytes32 = self.get_plot_id()
        new_challenge: bytes32 = ProofOfSpace.calculate_pos_challenge(plot_id, original_challenge_hash, signage_point)

        if new_challenge != self.challenge:
            log.error("New challenge is not challenge")
            return None

        if not ProofOfSpace.passes_plot_filter(constants, plot_id, original_challenge_hash, signage_point):
            log.error("Fail 5")
            return None

        return self.get_quality_string(plot_id)

    def get_quality_string(self, plot_id: bytes32) -> Optional[bytes32]:
        quality_str = Verifier().validate_proof(plot_id, self.size, self.challenge, bytes(self.proof))
        if not quality_str:
            return None
        return bytes32(quality_str)

    def get_farmer_ph(self):
        return encode_puzzle_hash(create_puzzlehash_for_pk(self.farmer_public_key))

    @staticmethod
    def passes_plot_filter(
        constants: ConsensusConstants,
        plot_id: bytes32,
        challenge_hash: bytes32,
        signage_point: bytes32,
    ) -> bool:
        plot_filter: BitArray = BitArray(
            ProofOfSpace.calculate_plot_filter_input(plot_id, challenge_hash, signage_point)
        )
        return plot_filter[: constants.NUMBER_ZERO_BITS_PLOT_FILTER].uint == 0

    @staticmethod
    def calculate_plot_filter_input(plot_id: bytes32, challenge_hash: bytes32, signage_point: bytes32) -> bytes32:
        return std_hash(plot_id + challenge_hash + signage_point)

    @staticmethod
    def calculate_pos_challenge(plot_id: bytes32, challenge_hash: bytes32, signage_point: bytes32) -> bytes32:
        return std_hash(ProofOfSpace.calculate_plot_filter_input(plot_id, challenge_hash, signage_point))

    @staticmethod
    def calculate_plot_id_pk(
        pool_public_key: G1Element,
        plot_public_key: G1Element,
    ) -> bytes32:
        return std_hash(bytes(pool_public_key) + bytes(plot_public_key))

    @staticmethod
    def calculate_plot_id_ph(
        pool_contract_puzzle_hash: bytes32,
        plot_public_key: G1Element,
    ) -> bytes32:
        return std_hash(bytes(pool_contract_puzzle_hash) + bytes(plot_public_key))

    @staticmethod
    def generate_taproot_sk(local_pk: G1Element, farmer_pk: G1Element) -> PrivateKey:
        taproot_message: bytes = bytes(local_pk + farmer_pk) + bytes(local_pk) + bytes(farmer_pk)
        taproot_hash: bytes32 = std_hash(taproot_message)
        return AugSchemeMPL.key_gen(taproot_hash)

    @staticmethod
    def generate_plot_public_key(local_pk: G1Element, farmer_pk: G1Element, include_taproot: bool = False) -> G1Element:
        if include_taproot:
            taproot_sk: PrivateKey = ProofOfSpace.generate_taproot_sk(local_pk, farmer_pk)
            return local_pk + farmer_pk + taproot_sk.get_g1()
        else:
            return local_pk + farmer_pk
