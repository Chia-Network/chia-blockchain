import logging
import asyncio
from yaml import safe_load
from hashlib import sha256
from typing import List, Dict, Set, Tuple, Any

from blspy import PrivateKey, Util, PrependSignature
from src.util.api_decorators import api_request
from src.types.proof_of_space import ProofOfSpace
from src.types.coinbase import CoinbaseInfo
from src.protocols import plotter_protocol, farmer_protocol
from src.types.sized_bytes import bytes32
from src.util.ints import uint32, uint64
from src.consensus.block_rewards import calculate_block_reward
from src.consensus.pot_iterations import calculate_iterations_quality
from src.consensus.constants import constants
from src.server.outbound_message import OutboundMessage, Delivery, Message, NodeType


log = logging.getLogger(__name__)


"""
PLOTTER PROTOCOL (FARMER <-> PLOTTER)
"""


class Farmer:
    def __init__(self):
        self.config = safe_load(open("src/config/farmer.yaml", "r"))
        self.lock = asyncio.Lock()
        self.plotter_responses_header_hash: Dict[bytes32, bytes32] = {}
        self.plotter_responses_challenge: Dict[bytes32, bytes32] = {}
        self.plotter_responses_proofs: Dict[bytes32, ProofOfSpace] = {}
        self.plotter_responses_proof_hash_to_qual: Dict[bytes32, bytes32] = {}
        self.challenges: Dict[uint32, List[farmer_protocol.ProofOfSpaceFinalized]] = {}
        self.challenge_to_height: Dict[bytes32, uint32] = {}
        self.current_heads: List[Tuple[bytes32, uint32]] = []
        self.seen_challenges: Set[bytes32] = set()
        self.unfinished_challenges: Dict[uint32, List[bytes32]] = {}
        self.current_height: uint32 = uint32(0)
        self.coinbase_rewards: Dict[uint32, Any] = {}
        self.proof_of_time_estimate_ips: uint64 = uint64(3000)

    @api_request
    async def challenge_response(self, challenge_response: plotter_protocol.ChallengeResponse):
        """
        This is a response from the plotter, for a NewChallenge. Here we check if the proof
        of space is sufficiently good, and if so, we ask for the whole proof.
        """

        async with self.lock:
            if challenge_response.quality in self.plotter_responses_challenge:
                log.warning(f"Have already seen quality {challenge_response.quality}")
                return
            height: uint32 = self.challenge_to_height[challenge_response.challenge_hash]
            difficulty: uint64 = uint64(0)
            for posf in self.challenges[height]:
                if posf.challenge_hash == challenge_response.challenge_hash:
                    difficulty = posf.difficulty
            if difficulty == 0:
                raise RuntimeError("Did not find challenge")

            number_iters: uint64 = calculate_iterations_quality(challenge_response.quality,
                                                                challenge_response.plot_size,
                                                                difficulty,
                                                                self.proof_of_time_estimate_ips,
                                                                constants["MIN_BLOCK_TIME"])
            estimate_secs: float = number_iters / self.proof_of_time_estimate_ips

        log.info(f"Estimate: {estimate_secs}, rate: {self.proof_of_time_estimate_ips}")
        if estimate_secs < self.config['pool_share_threshold'] or estimate_secs < self.config['propagate_threshold']:
            async with self.lock:
                self.plotter_responses_challenge[challenge_response.quality] = challenge_response.challenge_hash
            request = plotter_protocol.RequestProofOfSpace(challenge_response.quality)

            yield OutboundMessage(NodeType.PLOTTER, Message("request_proof_of_space", request), Delivery.RESPOND)

    @api_request
    async def respond_proof_of_space(self, response: plotter_protocol.RespondProofOfSpace):
        """
        This is a response from the plotter with a proof of space. We check it's validity,
        and request a pool partial, a header signature, or both, if the proof is good enough.
        """

        async with self.lock:
            pool_sks: List[PrivateKey] = [PrivateKey.from_bytes(bytes.fromhex(ce)) for ce in self.config["pool_sks"]]
            assert response.proof.pool_pubkey in [sk.get_public_key() for sk in pool_sks]

            challenge_hash: bytes32 = self.plotter_responses_challenge[response.quality]
            challenge_height: uint32 = self.challenge_to_height[challenge_hash]
            new_proof_height: uint32 = uint32(challenge_height + 1)
            difficulty: uint64 = uint64(0)
            for posf in self.challenges[challenge_height]:
                if posf.challenge_hash == challenge_hash:
                    difficulty = posf.difficulty
            if difficulty == 0:
                raise RuntimeError("Did not find challenge")

        computed_quality = response.proof.verify_and_get_quality(challenge_hash)
        assert response.quality == computed_quality

        async with self.lock:
            self.plotter_responses_proofs[response.quality] = response.proof
            self.plotter_responses_proof_hash_to_qual[response.proof.get_hash()] = response.quality

        number_iters: uint64 = calculate_iterations_quality(computed_quality,
                                                            response.proof.size,
                                                            difficulty,
                                                            self.proof_of_time_estimate_ips,
                                                            constants["MIN_BLOCK_TIME"])
        async with self.lock:
            estimate_secs: float = number_iters / self.proof_of_time_estimate_ips
        if estimate_secs < self.config['pool_share_threshold']:
            request1 = plotter_protocol.RequestPartialProof(response.quality,
                                                            sha256(bytes.fromhex(
                                                                   self.config['farmer_target'])).digest())
            yield OutboundMessage(NodeType.PLOTTER, Message("request_partial_proof", request1), Delivery.RESPOND)
        if estimate_secs < self.config['propagate_threshold']:
            async with self.lock:
                if new_proof_height not in self.coinbase_rewards:
                    log.error(f"Don't have coinbase transaction for height {new_proof_height}, cannot submit PoS")
                    return

                coinbase, signature = self.coinbase_rewards[new_proof_height]
                request2 = farmer_protocol.RequestHeaderHash(challenge_hash, coinbase, signature,
                                                             bytes.fromhex(self.config['farmer_target']),
                                                             response.proof)

            yield OutboundMessage(NodeType.FULL_NODE, Message("request_header_hash", request2), Delivery.BROADCAST)

    @api_request
    async def respond_header_signature(self, response: plotter_protocol.RespondHeaderSignature):
        """
        Receives a signature on a block header hash, which is required for submitting
        a block to the blockchain.
        """
        async with self.lock:
            header_hash: bytes32 = self.plotter_responses_header_hash[response.quality]
            proof_of_space: bytes32 = self.plotter_responses_proofs[response.quality]
            plot_pubkey = self.plotter_responses_proofs[response.quality].plot_pubkey

            assert response.header_hash_signature.verify([Util.hash256(header_hash)],
                                                         [plot_pubkey])

            # TODO: wait a while if it's a good quality, but not so good.
            pos_hash: bytes32 = proof_of_space.get_hash()

        request = farmer_protocol.HeaderSignature(pos_hash, header_hash, response.header_hash_signature)
        yield OutboundMessage(NodeType.FULL_NODE, Message("header_signature", request), Delivery.BROADCAST)

    @api_request
    async def respond_partial_proof(self, response: plotter_protocol.RespondPartialProof):
        """
        Receives a signature on the hash of the farmer payment target, which is used in a pool
        share, to tell the pool where to pay the farmer.
        """

        async with self.lock:
            farmer_target_hash = sha256(bytes.fromhex(self.config['farmer_target'])).digest()
            plot_pubkey = self.plotter_responses_proofs[response.quality].plot_pubkey

        assert response.farmer_target_signature.verify([Util.hash256(farmer_target_hash)],
                                                       [plot_pubkey])
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

        async with self.lock:
            quality: bytes32 = self.plotter_responses_proof_hash_to_qual[response.pos_hash]
            self.plotter_responses_header_hash[quality] = header_hash

        # TODO: only send to the plotter who made the proof of space, not all plotters
        request = plotter_protocol.RequestHeaderSignature(quality, header_hash)
        yield OutboundMessage(NodeType.PLOTTER, Message("request_header_signature", request), Delivery.BROADCAST)

    @api_request
    async def proof_of_space_finalized(self, proof_of_space_finalized: farmer_protocol.ProofOfSpaceFinalized):
        """
        Full node notifies farmer that a proof of space has been completed. It gets added to the
        challenges list at that height, and height is updated if necessary
        """
        get_proofs: bool = False
        async with self.lock:
            if (proof_of_space_finalized.height >= self.current_height and
                    proof_of_space_finalized.challenge_hash not in self.seen_challenges):
                # Only get proofs for new challenges, at a current or new height
                get_proofs = True
                if (proof_of_space_finalized.height > self.current_height):
                    self.current_height = proof_of_space_finalized.height

                # TODO: ask the pool for this information
                coinbase: CoinbaseInfo = CoinbaseInfo(uint32(self.current_height + 1),
                                                      calculate_block_reward(self.current_height),
                                                      bytes.fromhex(self.config["pool_target"]))

                pool_sks: List[PrivateKey] = [PrivateKey.from_bytes(bytes.fromhex(ce))
                                              for ce in self.config["pool_sks"]]
                coinbase_signature: PrependSignature = pool_sks[0].sign_prepend(coinbase.serialize())
                self.coinbase_rewards[uint32(self.current_height + 1)] = (coinbase, coinbase_signature)

                log.info(f"\tCurrent height set to {self.current_height}")
            self.seen_challenges.add(proof_of_space_finalized.challenge_hash)
            if proof_of_space_finalized.height not in self.challenges:
                self.challenges[proof_of_space_finalized.height] = [proof_of_space_finalized]
            else:
                self.challenges[proof_of_space_finalized.height].append(proof_of_space_finalized)
            self.challenge_to_height[proof_of_space_finalized.challenge_hash] = proof_of_space_finalized.height

        if get_proofs:
            message = plotter_protocol.NewChallenge(proof_of_space_finalized.challenge_hash)
            yield OutboundMessage(NodeType.PLOTTER, Message("new_challenge", message), Delivery.BROADCAST)

    @api_request
    async def proof_of_space_arrived(self, proof_of_space_arrived: farmer_protocol.ProofOfSpaceArrived):
        """
        Full node notifies the farmer that a new proof of space was created. The farmer can use this
        information to decide whether to propagate a proof.
        """
        async with self.lock:
            if proof_of_space_arrived.height not in self.unfinished_challenges:
                self.unfinished_challenges[proof_of_space_arrived.height] = []
            else:
                self.unfinished_challenges[proof_of_space_arrived.height].append(proof_of_space_arrived.quality)

    @api_request
    async def deep_reorg_notification(self, deep_reorg_notification: farmer_protocol.DeepReorgNotification):
        # TODO: implement
        # TODO: "forget everything and start over (reset db)"
        log.error(f"Deep reorg notification not implemented.")
        async with self.lock:
            pass

    @api_request
    async def proof_of_time_rate(self, proof_of_time_rate: farmer_protocol.ProofOfTimeRate):
        async with self.lock:
            self.proof_of_time_estimate_ips = proof_of_time_rate.pot_estimate_ips
