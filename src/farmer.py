import logging
import os
from hashlib import sha256
from typing import Any, Dict, List, Set

from blspy import PrependSignature, PrivateKey, Util
from yaml import safe_load

from definitions import ROOT_DIR
from src.consensus.block_rewards import calculate_block_reward
from src.consensus.constants import constants
from src.consensus.pot_iterations import calculate_iterations_quality
from src.protocols import farmer_protocol, harvester_protocol
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.coinbase import CoinbaseInfo
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request
from src.util.ints import uint32, uint64

log = logging.getLogger(__name__)


"""
HARVESTER PROTOCOL (FARMER <-> HARVESTER)
"""


class Farmer:
    def __init__(self):
        config_filename = os.path.join(ROOT_DIR, "config", "config.yaml")
        key_config_filename = os.path.join(ROOT_DIR, "config", "keys.yaml")
        if not os.path.isfile(key_config_filename):
            raise RuntimeError("Keys not generated. Run ./scripts/regenerate_keys.py.")
        self.config = safe_load(open(config_filename, "r"))["farmer"]
        self.key_config = safe_load(open(key_config_filename, "r"))
        self.harvester_responses_header_hash: Dict[bytes32, bytes32] = {}
        self.harvester_responses_challenge: Dict[bytes32, bytes32] = {}
        self.harvester_responses_proofs: Dict[bytes32, ProofOfSpace] = {}
        self.harvester_responses_proof_hash_to_qual: Dict[bytes32, bytes32] = {}
        self.challenges: Dict[uint32, List[farmer_protocol.ProofOfSpaceFinalized]] = {}
        self.challenge_to_height: Dict[bytes32, uint32] = {}
        self.challenge_to_best_iters: Dict[bytes32, uint64] = {}
        self.seen_challenges: Set[bytes32] = set()
        self.unfinished_challenges: Dict[uint32, List[bytes32]] = {}
        self.current_height: uint32 = uint32(0)
        self.coinbase_rewards: Dict[uint32, Any] = {}
        self.proof_of_time_estimate_ips: uint64 = uint64(10000)

    @api_request
    async def challenge_response(
        self, challenge_response: harvester_protocol.ChallengeResponse
    ):
        """
        This is a response from the harvester, for a NewChallenge. Here we check if the proof
        of space is sufficiently good, and if so, we ask for the whole proof.
        """

        if challenge_response.quality in self.harvester_responses_challenge:
            log.warning(f"Have already seen quality {challenge_response.quality}")
            return
        height: uint32 = self.challenge_to_height[challenge_response.challenge_hash]
        difficulty: uint64 = uint64(0)
        for posf in self.challenges[height]:
            if posf.challenge_hash == challenge_response.challenge_hash:
                difficulty = posf.difficulty
        if difficulty == 0:
            raise RuntimeError("Did not find challenge")

        number_iters: uint64 = calculate_iterations_quality(
            challenge_response.quality,
            challenge_response.plot_size,
            difficulty,
            self.proof_of_time_estimate_ips,
            constants["MIN_BLOCK_TIME"],
        )
        if height < 700:  # As the difficulty adjusts, don't fetch all qualities
            if challenge_response.challenge_hash not in self.challenge_to_best_iters:
                self.challenge_to_best_iters[
                    challenge_response.challenge_hash
                ] = number_iters
            elif (
                number_iters
                < self.challenge_to_best_iters[challenge_response.challenge_hash]
            ):
                self.challenge_to_best_iters[
                    challenge_response.challenge_hash
                ] = number_iters
            else:
                return
        estimate_secs: float = number_iters / self.proof_of_time_estimate_ips

        log.info(f"Estimate: {estimate_secs}, rate: {self.proof_of_time_estimate_ips}")
        if (
            estimate_secs < self.config["pool_share_threshold"]
            or estimate_secs < self.config["propagate_threshold"]
        ):
            self.harvester_responses_challenge[
                challenge_response.quality
            ] = challenge_response.challenge_hash
            request = harvester_protocol.RequestProofOfSpace(challenge_response.quality)

            yield OutboundMessage(
                NodeType.HARVESTER,
                Message("request_proof_of_space", request),
                Delivery.RESPOND,
            )

    @api_request
    async def respond_proof_of_space(
        self, response: harvester_protocol.RespondProofOfSpace
    ):
        """
        This is a response from the harvester with a proof of space. We check it's validity,
        and request a pool partial, a header signature, or both, if the proof is good enough.
        """

        pool_sks: List[PrivateKey] = [
            PrivateKey.from_bytes(bytes.fromhex(ce))
            for ce in self.key_config["pool_sks"]
        ]
        assert response.proof.pool_pubkey in [sk.get_public_key() for sk in pool_sks]

        challenge_hash: bytes32 = self.harvester_responses_challenge[response.quality]
        challenge_height: uint32 = self.challenge_to_height[challenge_hash]
        new_proof_height: uint32 = uint32(challenge_height + 1)
        difficulty: uint64 = uint64(0)
        for posf in self.challenges[challenge_height]:
            if posf.challenge_hash == challenge_hash:
                difficulty = posf.difficulty
        if difficulty == 0:
            raise RuntimeError("Did not find challenge")

        computed_quality = response.proof.verify_and_get_quality()
        assert response.quality == computed_quality

        self.harvester_responses_proofs[response.quality] = response.proof
        self.harvester_responses_proof_hash_to_qual[
            response.proof.get_hash()
        ] = response.quality

        number_iters: uint64 = calculate_iterations_quality(
            computed_quality,
            response.proof.size,
            difficulty,
            self.proof_of_time_estimate_ips,
            constants["MIN_BLOCK_TIME"],
        )
        estimate_secs: float = number_iters / self.proof_of_time_estimate_ips

        if estimate_secs < self.config["pool_share_threshold"]:
            request1 = harvester_protocol.RequestPartialProof(
                response.quality,
                sha256(bytes.fromhex(self.key_config["farmer_target"])).digest(),
            )
            yield OutboundMessage(
                NodeType.HARVESTER,
                Message("request_partial_proof", request1),
                Delivery.RESPOND,
            )
        if estimate_secs < self.config["propagate_threshold"]:
            if new_proof_height not in self.coinbase_rewards:
                log.error(
                    f"Don't have coinbase transaction for height {new_proof_height}, cannot submit PoS"
                )
                return

            coinbase, signature = self.coinbase_rewards[new_proof_height]
            request2 = farmer_protocol.RequestHeaderHash(
                challenge_hash,
                coinbase,
                signature,
                bytes.fromhex(self.key_config["farmer_target"]),
                response.proof,
            )

            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_header_hash", request2),
                Delivery.BROADCAST,
            )

    @api_request
    async def respond_header_signature(
        self, response: harvester_protocol.RespondHeaderSignature
    ):
        """
        Receives a signature on a block header hash, which is required for submitting
        a block to the blockchain.
        """
        header_hash: bytes32 = self.harvester_responses_header_hash[response.quality]
        proof_of_space: bytes32 = self.harvester_responses_proofs[response.quality]
        plot_pubkey = self.harvester_responses_proofs[response.quality].plot_pubkey

        assert response.header_hash_signature.verify(
            [Util.hash256(header_hash)], [plot_pubkey]
        )

        pos_hash: bytes32 = proof_of_space.get_hash()

        request = farmer_protocol.HeaderSignature(
            pos_hash, header_hash, response.header_hash_signature
        )
        yield OutboundMessage(
            NodeType.FULL_NODE, Message("header_signature", request), Delivery.BROADCAST
        )

    @api_request
    async def respond_partial_proof(
        self, response: harvester_protocol.RespondPartialProof
    ):
        """
        Receives a signature on the hash of the farmer payment target, which is used in a pool
        share, to tell the pool where to pay the farmer.
        """

        farmer_target_hash = sha256(
            bytes.fromhex(self.key_config["farmer_target"])
        ).digest()
        plot_pubkey = self.harvester_responses_proofs[response.quality].plot_pubkey

        assert response.farmer_target_signature.verify(
            [Util.hash256(farmer_target_hash)], [plot_pubkey]
        )
        # TODO: Send partial to pool

    """
    FARMER PROTOCOL (FARMER <-> FULL NODE)
    """

    @api_request
    async def header_hash(self, response: farmer_protocol.HeaderHash):
        """
        Full node responds with the hash of the created header
        """
        header_hash: bytes32 = response.header_hash

        quality: bytes32 = self.harvester_responses_proof_hash_to_qual[
            response.pos_hash
        ]
        self.harvester_responses_header_hash[quality] = header_hash

        # TODO: only send to the harvester who made the proof of space, not all plotters
        request = harvester_protocol.RequestHeaderSignature(quality, header_hash)
        yield OutboundMessage(
            NodeType.HARVESTER,
            Message("request_header_signature", request),
            Delivery.BROADCAST,
        )

    @api_request
    async def proof_of_space_finalized(
        self, proof_of_space_finalized: farmer_protocol.ProofOfSpaceFinalized
    ):
        """
        Full node notifies farmer that a proof of space has been completed. It gets added to the
        challenges list at that height, and height is updated if necessary
        """
        get_proofs: bool = False
        if (
            proof_of_space_finalized.height >= self.current_height
            and proof_of_space_finalized.challenge_hash not in self.seen_challenges
        ):
            # Only get proofs for new challenges, at a current or new height
            get_proofs = True
            if proof_of_space_finalized.height > self.current_height:
                self.current_height = proof_of_space_finalized.height

            # TODO: ask the pool for this information
            coinbase: CoinbaseInfo = CoinbaseInfo(
                uint32(self.current_height + 1),
                calculate_block_reward(self.current_height),
                bytes.fromhex(self.key_config["pool_target"]),
            )

            pool_sks: List[PrivateKey] = [
                PrivateKey.from_bytes(bytes.fromhex(ce))
                for ce in self.key_config["pool_sks"]
            ]
            coinbase_signature: PrependSignature = pool_sks[0].sign_prepend(
                bytes(coinbase)
            )
            self.coinbase_rewards[uint32(self.current_height + 1)] = (
                coinbase,
                coinbase_signature,
            )

            log.info(f"\tCurrent height set to {self.current_height}")
        self.seen_challenges.add(proof_of_space_finalized.challenge_hash)
        if proof_of_space_finalized.height not in self.challenges:
            self.challenges[proof_of_space_finalized.height] = [
                proof_of_space_finalized
            ]
        else:
            self.challenges[proof_of_space_finalized.height].append(
                proof_of_space_finalized
            )
        self.challenge_to_height[
            proof_of_space_finalized.challenge_hash
        ] = proof_of_space_finalized.height

        if get_proofs:
            message = harvester_protocol.NewChallenge(
                proof_of_space_finalized.challenge_hash
            )
            yield OutboundMessage(
                NodeType.HARVESTER,
                Message("new_challenge", message),
                Delivery.BROADCAST,
            )

    @api_request
    async def proof_of_space_arrived(
        self, proof_of_space_arrived: farmer_protocol.ProofOfSpaceArrived
    ):
        """
        Full node notifies the farmer that a new proof of space was created. The farmer can use this
        information to decide whether to propagate a proof.
        """
        if proof_of_space_arrived.height not in self.unfinished_challenges:
            self.unfinished_challenges[proof_of_space_arrived.height] = []
        else:
            self.unfinished_challenges[proof_of_space_arrived.height].append(
                proof_of_space_arrived.quality
            )

    @api_request
    async def deep_reorg_notification(
        self, deep_reorg_notification: farmer_protocol.DeepReorgNotification
    ):
        """
        Resets everything. This will be triggered when a long reorg happens, which means blocks of lower
        height (but greater weight) might come.
        """
        self.harvester_responses_header_hash = {}
        self.harvester_responses_challenge = {}
        self.harvester_responses_proofs = {}
        self.harvester_responses_proof_hash_to_qual = {}
        self.challenges = {}
        self.challenge_to_height = {}
        self.seen_challenges = set()
        self.unfinished_challenges = {}
        self.current_height = uint32(0)
        self.coinbase_rewards = {}

    @api_request
    async def proof_of_time_rate(
        self, proof_of_time_rate: farmer_protocol.ProofOfTimeRate
    ):
        """
        Updates our internal etimate of the iterations per second for the fastest proof of time
        in the network.
        """
        self.proof_of_time_estimate_ips = proof_of_time_rate.pot_estimate_ips
