import asyncio
from typing import Optional, Callable

from blspy import AugSchemeMPL, G2Element

from src.consensus.pot_iterations import calculate_iterations_quality
from src.farmer import Farmer
from src.protocols import harvester_protocol, farmer_protocol
from src.server.outbound_message import Message, NodeType
from src.server.ws_connection import WSChiaConnection
from src.types.pool_target import PoolTarget
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.util.api_decorators import api_request
from src.util.ints import uint32, uint128, uint64


class FarmerAPI:
    farmer: Farmer

    def __init__(self, farmer):
        self.farmer = farmer

    def _set_state_changed_callback(self, callback: Callable):
        self.farmer.state_changed_callback = callback

    @api_request
    async def challenge_response(
        self,
        challenge_response: harvester_protocol.ChallengeResponse,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        """
        This is a response from the harvester, for a NewChallenge. Here we check if the proof
        of space is sufficiently good, and if so, we ask for the whole proof.
        """
        height: uint32 = self.farmer.challenge_to_height[
            challenge_response.challenge_hash
        ]
        number_iters = await self.farmer._get_required_iters(
            challenge_response.challenge_hash,
            challenge_response.quality_string,
            challenge_response.plot_size,
        )
        if height < 1000:  # As the difficulty adjusts, don't fetch all qualities
            if (
                challenge_response.challenge_hash
                not in self.farmer.challenge_to_best_iters
            ):
                self.farmer.challenge_to_best_iters[
                    challenge_response.challenge_hash
                ] = number_iters
            elif (
                number_iters
                < self.farmer.challenge_to_best_iters[challenge_response.challenge_hash]
            ):
                self.farmer.challenge_to_best_iters[
                    challenge_response.challenge_hash
                ] = number_iters
            else:
                return None

        estimate_secs: float = number_iters / self.farmer.proof_of_time_estimate_ips
        if challenge_response.challenge_hash not in self.farmer.challenge_to_estimates:
            self.farmer.challenge_to_estimates[challenge_response.challenge_hash] = []
        self.farmer.challenge_to_estimates[challenge_response.challenge_hash].append(
            estimate_secs
        )

        self.farmer.log.info(
            f"Estimate: {estimate_secs}, rate: {self.farmer.proof_of_time_estimate_ips}"
        )
        if (
            estimate_secs < self.farmer.config["pool_share_threshold"]
            or estimate_secs < self.farmer.config["propagate_threshold"]
        ):

            request = harvester_protocol.RequestProofOfSpace(
                challenge_response.challenge_hash,
                challenge_response.plot_id,
                challenge_response.response_number,
            )

            self.farmer._state_changed("challenge")
            msg = Message("request_proof_of_space", request)
            return msg
        return None

    @api_request
    async def respond_proof_of_space(
        self, response: harvester_protocol.RespondProofOfSpace, peer: WSChiaConnection
    ) -> Optional[Message]:
        """
        This is a response from the harvester with a proof of space. We check it's validity,
        and request a pool partial, a header signature, or both, if the proof is good enough.
        """

        challenge_hash: bytes32 = response.proof.challenge_hash
        challenge_weight: uint128 = self.farmer.challenge_to_weight[challenge_hash]
        difficulty: uint64 = uint64(0)
        for posf in self.farmer.challenges[challenge_weight]:
            if posf.challenge_hash == challenge_hash:
                difficulty = posf.difficulty
        if difficulty == 0:
            raise RuntimeError("Did not find challenge")

        computed_quality_string = response.proof.verify_and_get_quality_string(
            self.farmer.constants.NUMBER_ZERO_BITS_CHALLENGE_SIG
        )
        if computed_quality_string is None:
            raise RuntimeError("Invalid proof of space")

        self.farmer.harvester_responses_proofs[
            (response.proof.challenge_hash, response.plot_id, response.response_number)
        ] = response.proof
        self.farmer.harvester_responses_proof_hash_to_info[
            response.proof.get_hash()
        ] = (
            response.proof.challenge_hash,
            response.plot_id,
            response.response_number,
        )

        estimate_min = (
            self.farmer.proof_of_time_estimate_ips
            * self.farmer.constants.BLOCK_TIME_TARGET
            / self.farmer.constants.MIN_ITERS_PROPORTION
        )
        estimate_min = uint64(int(estimate_min))
        number_iters: uint64 = calculate_iterations_quality(
            computed_quality_string,
            response.proof.size,
            difficulty,
            estimate_min,
        )
        estimate_secs: float = number_iters / self.farmer.proof_of_time_estimate_ips

        if estimate_secs < self.farmer.config["pool_share_threshold"]:
            # TODO: implement pooling
            pass
        if estimate_secs < self.farmer.config["propagate_threshold"]:
            pool_pk = bytes(response.proof.pool_public_key)
            if pool_pk not in self.farmer.pool_sks_map:
                self.farmer.log.error(
                    f"Don't have the private key for the pool key used by harvester: {pool_pk.hex()}"
                )
                return None
            pool_target: PoolTarget = PoolTarget(self.farmer.pool_target, uint32(0))
            pool_target_signature: G2Element = AugSchemeMPL.sign(
                self.farmer.pool_sks_map[pool_pk], bytes(pool_target)
            )

            request2 = farmer_protocol.RequestHeaderHash(
                challenge_hash,
                response.proof,
                pool_target,
                pool_target_signature,
                self.farmer.wallet_target,
            )
            msg = Message("request_header_hash", request2)
            assert self.farmer.server is not None
            await self.farmer.server.send_to_all([msg], NodeType.FULL_NODE)
            return None
        return None

    @api_request
    async def respond_signature(
        self, response: harvester_protocol.RespondSignature, peer: WSChiaConnection
    ):
        """
        Receives a signature on a block header hash, which is required for submitting
        a block to the blockchain.
        """
        header_hash = response.message
        proof_of_space: bytes32 = self.farmer.header_hash_to_pos[header_hash]
        validates: bool = False
        for sk in self.farmer._get_private_keys():
            pk = sk.get_g1()
            if pk == response.farmer_pk:
                agg_pk = ProofOfSpace.generate_plot_public_key(response.local_pk, pk)
                assert agg_pk == proof_of_space.plot_public_key
                farmer_share = AugSchemeMPL.sign(sk, header_hash, agg_pk)
                agg_sig = AugSchemeMPL.aggregate(
                    [response.message_signature, farmer_share]
                )
                validates = AugSchemeMPL.verify(agg_pk, header_hash, agg_sig)

                if validates:
                    break
        assert validates

        pos_hash: bytes32 = proof_of_space.get_hash()

        request = farmer_protocol.HeaderSignature(pos_hash, header_hash, agg_sig)
        msg = Message("header_signature", request)
        assert self.farmer.server is not None
        await self.farmer.server.send_to_all([msg], NodeType.FULL_NODE)

    """
    FARMER PROTOCOL (FARMER <-> FULL NODE)
    """

    @api_request
    async def header_hash(
        self, response: farmer_protocol.HeaderHash, peer: WSChiaConnection
    ):
        """
        Full node responds with the hash of the created header
        """
        header_hash: bytes32 = response.header_hash

        (
            challenge_hash,
            plot_id,
            response_number,
        ) = self.farmer.harvester_responses_proof_hash_to_info[response.pos_hash]
        pos = self.farmer.harvester_responses_proofs[
            challenge_hash, plot_id, response_number
        ]
        self.farmer.header_hash_to_pos[header_hash] = pos

        # TODO: only send to the harvester who made the proof of space, not all harvesters
        request = harvester_protocol.RequestSignature(plot_id, header_hash)

        msg = Message("request_signature", request)
        assert self.farmer.server is not None
        await self.farmer.server.send_to_all([msg], NodeType.HARVESTER)

    @api_request
    async def proof_of_space_finalized(
        self,
        proof_of_space_finalized: farmer_protocol.ProofOfSpaceFinalized,
        peer: WSChiaConnection,
    ):
        """
        Full node notifies farmer that a proof of space has been completed. It gets added to the
        challenges list at that weight, and weight is updated if necessary
        """
        get_proofs: bool = False
        if (
            proof_of_space_finalized.weight >= self.farmer.current_weight
            and proof_of_space_finalized.challenge_hash
            not in self.farmer.seen_challenges
        ):
            # Only get proofs for new challenges, at a current or new weight
            get_proofs = True
            if proof_of_space_finalized.weight > self.farmer.current_weight:
                self.farmer.current_weight = proof_of_space_finalized.weight

            self.farmer.log.info(
                f"\tCurrent weight set to {self.farmer.current_weight}"
            )
        self.farmer.seen_challenges.add(proof_of_space_finalized.challenge_hash)
        if proof_of_space_finalized.weight not in self.farmer.challenges:
            self.farmer.challenges[proof_of_space_finalized.weight] = [
                proof_of_space_finalized
            ]
        else:
            self.farmer.challenges[proof_of_space_finalized.weight].append(
                proof_of_space_finalized
            )
        self.farmer.challenge_to_weight[
            proof_of_space_finalized.challenge_hash
        ] = proof_of_space_finalized.weight
        self.farmer.challenge_to_height[
            proof_of_space_finalized.challenge_hash
        ] = proof_of_space_finalized.height

        if get_proofs:
            message = harvester_protocol.NewChallenge(
                proof_of_space_finalized.challenge_hash
            )

            msg = Message("new_challenge", message)
            assert self.farmer.server is not None
            await self.farmer.server.send_to_all([msg], NodeType.HARVESTER)
            # This allows the collection of estimates from the harvesters
            self.farmer._state_changed("challenge")

    @api_request
    async def proof_of_space_arrived(
        self,
        proof_of_space_arrived: farmer_protocol.ProofOfSpaceArrived,
        peer: WSChiaConnection,
    ) -> Optional[Message]:

        """
        Full node notifies the farmer that a new proof of space was created. The farmer can use this
        information to decide whether to propagate a proof.
        """
        if proof_of_space_arrived.weight not in self.farmer.unfinished_challenges:
            self.farmer.unfinished_challenges[proof_of_space_arrived.weight] = []
        else:
            self.farmer.unfinished_challenges[proof_of_space_arrived.weight].append(
                proof_of_space_arrived.quality_string
            )
        return None

    @api_request
    async def proof_of_time_rate(
        self,
        proof_of_time_rate: farmer_protocol.ProofOfTimeRate,
        peer: WSChiaConnection,
    ) -> Optional[Message]:
        """
        Updates our internal estimate of the iterations per second for the fastest proof of time
        in the network.
        """
        self.farmer.proof_of_time_estimate_ips = proof_of_time_rate.pot_estimate_ips
        return None
