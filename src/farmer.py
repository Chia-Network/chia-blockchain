import asyncio
import logging
from typing import Dict, List, Set, Optional, Callable, Tuple

from blspy import Util, InsecureSignature, PrependSignature, PublicKey
from src.util.keychain import Keychain

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import calculate_iterations_quality
from src.protocols import farmer_protocol, harvester_protocol
from src.server.connection import PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.types.pool_target import PoolTarget
from src.util.api_decorators import api_request
from src.util.ints import uint32, uint64, uint128, uint8

log = logging.getLogger(__name__)


"""
HARVESTER PROTOCOL (FARMER <-> HARVESTER)
"""


class Farmer:
    def __init__(
        self,
        farmer_config: Dict,
        pool_config: Dict,
        keychain: Keychain,
        consensus_constants: ConsensusConstants,
    ):
        self.config = farmer_config
        self.harvester_responses_proofs: Dict[Tuple, ProofOfSpace] = {}
        self.harvester_responses_proof_hash_to_info: Dict[bytes32, Tuple] = {}
        self.header_hash_to_pos: Dict[bytes32, ProofOfSpace] = {}
        self.challenges: Dict[uint128, List[farmer_protocol.ProofOfSpaceFinalized]] = {}
        self.challenge_to_weight: Dict[bytes32, uint128] = {}
        self.challenge_to_height: Dict[bytes32, uint32] = {}
        self.challenge_to_best_iters: Dict[bytes32, uint64] = {}
        self.challenge_to_estimates: Dict[bytes32, List[float]] = {}
        self.seen_challenges: Set[bytes32] = set()
        self.unfinished_challenges: Dict[uint128, List[bytes32]] = {}
        self.current_weight: uint128 = uint128(0)
        self.proof_of_time_estimate_ips: uint64 = uint64(10000)
        self.constants = consensus_constants
        self._shut_down = False
        self.server = None
        self.keychain = keychain
        self.state_changed_callback: Optional[Callable] = None

        if len(self._get_public_keys()) == 0:
            error_str = "No keys exist. Please run 'chia keys generate' or open the UI."
            raise RuntimeError(error_str)

        # This is the farmer configuration
        self.wallet_target = bytes.fromhex(self.config["xch_target_puzzle_hash"])
        self.pool_public_keys = [
            PublicKey.from_bytes(bytes.fromhex(pk))
            for pk in self.config["pool_public_keys"]
        ]

        # This is the pool configuration, which should be moved out to the pool once it exists
        self.pool_target = bytes.fromhex(pool_config["xch_target_puzzle_hash"])
        self.pool_sks_map: Dict = {}
        for key in self._get_private_keys():
            self.pool_sks_map[bytes(key.get_public_key())] = key

        assert len(self.wallet_target) == 32
        assert len(self.pool_target) == 32
        if len(self.pool_sks_map) == 0:
            error_str = "No keys exist. Please run 'chia keys generate' or open the UI."
            raise RuntimeError(error_str)

    async def _on_connect(self):
        # Sends a handshake to the harvester
        msg = harvester_protocol.HarvesterHandshake(
            self._get_public_keys(), self.pool_public_keys
        )
        yield OutboundMessage(
            NodeType.HARVESTER, Message("harvester_handshake", msg), Delivery.RESPOND
        )
        if self.current_weight in self.challenges:
            for posf in self.challenges[self.current_weight]:
                message = harvester_protocol.NewChallenge(posf.challenge_hash)
                yield OutboundMessage(
                    NodeType.HARVESTER,
                    Message("new_challenge", message),
                    Delivery.BROADCAST,
                )

    def _set_global_connections(self, global_connections: PeerConnections):
        self.global_connections: PeerConnections = global_connections

    def _set_server(self, server):
        self.server = server

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback
        if self.global_connections is not None:
            self.global_connections.set_state_changed_callback(callback)

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    def _get_public_keys(self):
        return [
            epk.public_child(0).get_public_key()
            for epk in self.keychain.get_all_public_keys()
        ]

    def _get_private_keys(self):
        return [
            esk.private_child(0).get_private_key()
            for esk, _ in self.keychain.get_all_private_keys()
        ]

    async def _get_required_iters(
        self, challenge_hash: bytes32, quality_string: bytes32, plot_size: uint8
    ):
        weight: uint128 = self.challenge_to_weight[challenge_hash]
        difficulty: uint64 = uint64(0)
        for posf in self.challenges[weight]:
            if posf.challenge_hash == challenge_hash:
                difficulty = posf.difficulty
        if difficulty == 0:
            raise RuntimeError("Did not find challenge")

        estimate_min = (
            self.proof_of_time_estimate_ips
            * self.constants.BLOCK_TIME_TARGET
            / self.constants.MIN_ITERS_PROPORTION
        )
        estimate_min = uint64(int(estimate_min))
        number_iters: uint64 = calculate_iterations_quality(
            quality_string, plot_size, difficulty, estimate_min,
        )
        return number_iters

    @api_request
    async def challenge_response(
        self, challenge_response: harvester_protocol.ChallengeResponse
    ):
        """
        This is a response from the harvester, for a NewChallenge. Here we check if the proof
        of space is sufficiently good, and if so, we ask for the whole proof.
        """

        height: uint32 = self.challenge_to_height[challenge_response.challenge_hash]
        number_iters = await self._get_required_iters(
            challenge_response.challenge_hash,
            challenge_response.quality_string,
            challenge_response.plot_size,
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
        if challenge_response.challenge_hash not in self.challenge_to_estimates:
            self.challenge_to_estimates[challenge_response.challenge_hash] = []
        self.challenge_to_estimates[challenge_response.challenge_hash].append(
            estimate_secs
        )

        log.info(f"Estimate: {estimate_secs}, rate: {self.proof_of_time_estimate_ips}")
        if (
            estimate_secs < self.config["pool_share_threshold"]
            or estimate_secs < self.config["propagate_threshold"]
        ):

            request = harvester_protocol.RequestProofOfSpace(
                challenge_response.challenge_hash,
                challenge_response.plot_id,
                challenge_response.response_number,
            )

            yield OutboundMessage(
                NodeType.HARVESTER,
                Message("request_proof_of_space", request),
                Delivery.RESPOND,
            )

            self._state_changed("challenge")

    @api_request
    async def respond_proof_of_space(
        self, response: harvester_protocol.RespondProofOfSpace
    ):
        """
        This is a response from the harvester with a proof of space. We check it's validity,
        and request a pool partial, a header signature, or both, if the proof is good enough.
        """

        challenge_hash: bytes32 = response.proof.challenge_hash
        challenge_weight: uint128 = self.challenge_to_weight[challenge_hash]
        difficulty: uint64 = uint64(0)
        for posf in self.challenges[challenge_weight]:
            if posf.challenge_hash == challenge_hash:
                difficulty = posf.difficulty
        if difficulty == 0:
            raise RuntimeError("Did not find challenge")

        computed_quality_string = response.proof.verify_and_get_quality_string(
            self.constants["NUMBER_ZERO_BITS_CHALLENGE_SIG"]
        )
        if computed_quality_string is None:
            raise RuntimeError("Invalid proof of space")

        self.harvester_responses_proofs[
            (response.proof.challenge_hash, response.plot_id, response.response_number)
        ] = response.proof
        self.harvester_responses_proof_hash_to_info[response.proof.get_hash()] = (
            response.proof.challenge_hash,
            response.plot_id,
            response.response_number,
        )

        estimate_min = (
            self.proof_of_time_estimate_ips
            * self.constants.BLOCK_TIME_TARGET
            / self.constants.MIN_ITERS_PROPORTION
        )
        estimate_min = uint64(int(estimate_min))
        number_iters: uint64 = calculate_iterations_quality(
            computed_quality_string, response.proof.size, difficulty, estimate_min,
        )
        estimate_secs: float = number_iters / self.proof_of_time_estimate_ips

        if estimate_secs < self.config["pool_share_threshold"]:
            # TODO: implement pooling
            pass
        if estimate_secs < self.config["propagate_threshold"]:
            pool_pk = bytes(response.proof.pool_public_key)
            if pool_pk not in self.pool_sks_map:
                log.error(
                    f"Don't have the private key for the pool key used by harvester: {pool_pk.hex()}"
                )
                return
            pool_target: PoolTarget = PoolTarget(self.pool_target, uint32(0))
            pool_target_signature: PrependSignature = self.pool_sks_map[
                pool_pk
            ].sign_prepend(bytes(pool_target))

            request2 = farmer_protocol.RequestHeaderHash(
                challenge_hash,
                response.proof,
                pool_target,
                pool_target_signature,
                self.wallet_target,
            )

            yield OutboundMessage(
                NodeType.FULL_NODE,
                Message("request_header_hash", request2),
                Delivery.BROADCAST,
            )

    @api_request
    async def respond_signature(self, response: harvester_protocol.RespondSignature):
        """
        Receives a signature on a block header hash, which is required for submitting
        a block to the blockchain.
        """
        header_hash = response.message
        proof_of_space: bytes32 = self.header_hash_to_pos[header_hash]
        validates: bool = False
        for sk in self._get_private_keys():
            pk = sk.get_public_key()
            if pk == response.farmer_pk:
                agg_pk = ProofOfSpace.generate_plot_public_key(
                    response.harvester_pk, pk
                )
                assert agg_pk == proof_of_space.plot_public_key
                new_m = bytes(agg_pk) + Util.hash256(header_hash)
                farmer_share = sk.sign_insecure(new_m)
                agg_sig = PrependSignature.from_insecure_sig(
                    InsecureSignature.aggregate(
                        [response.message_signature, farmer_share]
                    )
                )

                validates = agg_sig.verify([Util.hash256(header_hash)], [agg_pk])
                if validates:
                    break
        assert validates

        pos_hash: bytes32 = proof_of_space.get_hash()

        request = farmer_protocol.HeaderSignature(pos_hash, header_hash, agg_sig)
        yield OutboundMessage(
            NodeType.FULL_NODE, Message("header_signature", request), Delivery.BROADCAST
        )

    """
    FARMER PROTOCOL (FARMER <-> FULL NODE)
    """

    @api_request
    async def header_hash(self, response: farmer_protocol.HeaderHash):
        """
        Full node responds with the hash of the created header
        """
        header_hash: bytes32 = response.header_hash

        (
            challenge_hash,
            plot_id,
            response_number,
        ) = self.harvester_responses_proof_hash_to_info[response.pos_hash]
        pos = self.harvester_responses_proofs[challenge_hash, plot_id, response_number]
        self.header_hash_to_pos[header_hash] = pos

        # TODO: only send to the harvester who made the proof of space, not all harvesters
        request = harvester_protocol.RequestSignature(plot_id, header_hash)
        yield OutboundMessage(
            NodeType.HARVESTER,
            Message("request_signature", request),
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
            # This allows the collection of estimates from the harvesters
            self._state_changed("challenge")
            for _ in range(20):
                if self._shut_down:
                    return
                await asyncio.sleep(1)
            self._state_changed("challenge")

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
