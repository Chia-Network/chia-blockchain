import asyncio
import logging
from typing import Any, Dict, List, Set

from blspy import PrivateKey, Util

from src.consensus.block_rewards import calculate_block_reward
from src.consensus.constants import constants as consensus_constants
from src.consensus.pot_iterations import calculate_iterations_quality
from src.consensus.coinbase import create_coinbase_coin_and_signature
from src.protocols import farmer_protocol, harvester_protocol
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.peer_info import PeerInfo
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request
from src.util.ints import uint32, uint64, uint128

log = logging.getLogger(__name__)


"""
HARVESTER PROTOCOL (FARMER <-> HARVESTER)
"""


class Farmer:
    def __init__(self, farmer_config: Dict, key_config: Dict, override_constants={}):
        self.config = farmer_config
        self.key_config = key_config
        self.harvester_responses_header_hash: Dict[bytes32, bytes32] = {}
        self.harvester_responses_challenge: Dict[bytes32, bytes32] = {}
        self.harvester_responses_proofs: Dict[bytes32, ProofOfSpace] = {}
        self.harvester_responses_proof_hash_to_qual: Dict[bytes32, bytes32] = {}
        self.challenges: Dict[uint128, List[farmer_protocol.ProofOfSpaceFinalized]] = {}
        self.challenge_to_weight: Dict[bytes32, uint128] = {}
        self.challenge_to_height: Dict[bytes32, uint32] = {}
        self.challenge_to_best_iters: Dict[bytes32, uint64] = {}
        self.seen_challenges: Set[bytes32] = set()
        self.unfinished_challenges: Dict[uint128, List[bytes32]] = {}
        self.current_weight: uint128 = uint128(0)
        self.coinbase_rewards: Dict[uint32, Any] = {}
        self.proof_of_time_estimate_ips: uint64 = uint64(10000)
        self.constants = consensus_constants.copy()
        self.server = None
        self._shut_down = False
        for key, value in override_constants.items():
            self.constants[key] = value

    async def _on_connect(self):
        # Sends a handshake to the harvester
        pool_sks: List[PrivateKey] = [
            PrivateKey.from_bytes(bytes.fromhex(ce))
            for ce in self.key_config["pool_sks"]
        ]
        msg = harvester_protocol.HarvesterHandshake(
            [sk.get_public_key() for sk in pool_sks]
        )
        yield OutboundMessage(
            NodeType.HARVESTER, Message("harvester_handshake", msg), Delivery.RESPOND
        )

    def set_server(self, server):
        self.server = server

    @api_request
    async def challenge_response(
        self, challenge_response: harvester_protocol.ChallengeResponse
    ):
        """
        This is a response from the harvester, for a NewChallenge. Here we check if the proof
        of space is sufficiently good, and if so, we ask for the whole proof.
        """

        if challenge_response.quality_string in self.harvester_responses_challenge:
            log.warning(
                f"Have already seen quality string {challenge_response.quality_string}"
            )
            return
        weight: uint128 = self.challenge_to_weight[challenge_response.challenge_hash]
        height: uint32 = self.challenge_to_height[challenge_response.challenge_hash]
        difficulty: uint64 = uint64(0)
        for posf in self.challenges[weight]:
            if posf.challenge_hash == challenge_response.challenge_hash:
                difficulty = posf.difficulty
        if difficulty == 0:
            raise RuntimeError("Did not find challenge")

        estimate_min = (
            self.proof_of_time_estimate_ips
            * self.constants["BLOCK_TIME_TARGET"]
            / self.constants["MIN_ITERS_PROPORTION"]
        )
        number_iters: uint64 = calculate_iterations_quality(
            challenge_response.quality_string,
            challenge_response.plot_size,
            difficulty,
            estimate_min,
        )
        if height < 1000:  # As the difficulty adjusts, don't fetch all qualities
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
                challenge_response.quality_string
            ] = challenge_response.challenge_hash
            request = harvester_protocol.RequestProofOfSpace(
                challenge_response.quality_string
            )

            yield OutboundMessage(
                NodeType.HARVESTER,
                Message("request_proof_of_space", request),
                Delivery.RESPOND,
            )

    def _start_bg_tasks(self):
        """
        Start a background task that checks connection and reconnects periodically to the full_node.
        """

        full_node_peer = PeerInfo(
            self.config["full_node_peer"]["host"], self.config["full_node_peer"]["port"]
        )

        async def connection_check():
            while not self._shut_down:
                if self.server is not None:
                    full_node_retry = True

                    for connection in self.server.global_connections.get_connections():
                        if connection.get_peer_info() == full_node_peer:
                            full_node_retry = False

                    if full_node_retry:
                        log.info(f"Reconnecting to full_node {full_node_peer}")
                        if not await self.server.start_client(
                            full_node_peer, None, auth=False
                        ):
                            await asyncio.sleep(1)
                await asyncio.sleep(30)

        self.reconnect_task = asyncio.create_task(connection_check())

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
        if response.proof.pool_pubkey not in [sk.get_public_key() for sk in pool_sks]:
            raise RuntimeError("Pool pubkey not in list of approved keys")

        challenge_hash: bytes32 = self.harvester_responses_challenge[
            response.quality_string
        ]
        challenge_weight: uint128 = self.challenge_to_weight[challenge_hash]
        challenge_height: uint32 = self.challenge_to_height[challenge_hash]
        new_proof_height: uint32 = uint32(challenge_height + 1)
        difficulty: uint64 = uint64(0)
        for posf in self.challenges[challenge_weight]:
            if posf.challenge_hash == challenge_hash:
                difficulty = posf.difficulty
        if difficulty == 0:
            raise RuntimeError("Did not find challenge")

        computed_quality_string = response.proof.verify_and_get_quality_string()
        if response.quality_string != computed_quality_string:
            raise RuntimeError("Invalid quality for proof of space")

        self.harvester_responses_proofs[response.quality_string] = response.proof
        self.harvester_responses_proof_hash_to_qual[
            response.proof.get_hash()
        ] = response.quality_string

        estimate_min = (
            self.proof_of_time_estimate_ips
            * self.constants["BLOCK_TIME_TARGET"]
            / self.constants["MIN_ITERS_PROPORTION"]
        )
        number_iters: uint64 = calculate_iterations_quality(
            computed_quality_string, response.proof.size, difficulty, estimate_min,
        )
        estimate_secs: float = number_iters / self.proof_of_time_estimate_ips

        if estimate_secs < self.config["pool_share_threshold"]:
            request1 = harvester_protocol.RequestPartialProof(
                response.quality_string,
                bytes.fromhex(self.key_config["wallet_target"]),
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
                bytes.fromhex(self.key_config["wallet_target"]),
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
        header_hash: bytes32 = self.harvester_responses_header_hash[
            response.quality_string
        ]
        proof_of_space: bytes32 = self.harvester_responses_proofs[
            response.quality_string
        ]
        plot_pubkey = self.harvester_responses_proofs[
            response.quality_string
        ].plot_pubkey

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

        farmer_target = bytes.fromhex(self.key_config["wallet_target"])
        plot_pubkey = self.harvester_responses_proofs[
            response.quality_string
        ].plot_pubkey

        assert response.farmer_target_signature.verify(
            [Util.hash256(farmer_target)], [plot_pubkey]
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

        # TODO: only send to the harvester who made the proof of space, not all harvesters
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
        challenges list at that weight, and weight is updated if necessary
        """
        get_proofs: bool = False
        if (
            proof_of_space_finalized.weight >= self.current_weight
            and proof_of_space_finalized.challenge_hash not in self.seen_challenges
        ):
            # Only get proofs for new challenges, at a current or new weight
            get_proofs = True
            if proof_of_space_finalized.weight > self.current_weight:
                self.current_weight = proof_of_space_finalized.weight

            # TODO: ask the pool for this information

            pool_sks: List[PrivateKey] = [
                PrivateKey.from_bytes(bytes.fromhex(ce))  # type: ignore # noqa
                for ce in self.key_config["pool_sks"]
            ]

            coinbase_reward = uint64(
                calculate_block_reward(uint32(proof_of_space_finalized.height + 1))
            )

            coinbase_coin, coinbase_signature = create_coinbase_coin_and_signature(
                proof_of_space_finalized.height + 1,
                bytes.fromhex(self.key_config["pool_target"]),
                coinbase_reward,
                pool_sks[0],
            )

            self.coinbase_rewards[uint32(proof_of_space_finalized.height + 1)] = (
                coinbase_coin,
                coinbase_signature,
            )

            log.info(f"\tCurrent weight set to {self.current_weight}")
        self.seen_challenges.add(proof_of_space_finalized.challenge_hash)
        if proof_of_space_finalized.weight not in self.challenges:
            self.challenges[proof_of_space_finalized.weight] = [
                proof_of_space_finalized
            ]
        else:
            self.challenges[proof_of_space_finalized.weight].append(
                proof_of_space_finalized
            )
        self.challenge_to_weight[
            proof_of_space_finalized.challenge_hash
        ] = proof_of_space_finalized.weight
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
        if proof_of_space_arrived.weight not in self.unfinished_challenges:
            self.unfinished_challenges[proof_of_space_arrived.weight] = []
        else:
            self.unfinished_challenges[proof_of_space_arrived.weight].append(
                proof_of_space_arrived.quality_string
            )

    @api_request
    async def proof_of_time_rate(
        self, proof_of_time_rate: farmer_protocol.ProofOfTimeRate
    ):
        """
        Updates our internal estimate of the iterations per second for the fastest proof of time
        in the network.
        """
        self.proof_of_time_estimate_ips = proof_of_time_rate.pot_estimate_ips
