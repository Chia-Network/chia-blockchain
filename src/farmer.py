import asyncio
import logging
from typing import Dict, List, Optional, Callable

from blspy import G1Element, G2Element, AugSchemeMPL
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
from src.util.ints import uint32, uint64
from src.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk
from src.util.chech32 import decode_puzzle_hash

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
        # To send to harvester on connect
        self.latest_challenge: bytes32 = None

        # Keep track of all icps for each challenge
        self.icps: Dict[bytes32, List[farmer_protocol.InfusionChallengePoint]] = {}

        # Keep track of proofs of space for each challenge
        self.proofs_of_space: Dict[bytes32, List[ProofOfSpace]] = {}

        # Quality string to pos, for use with harvester.RequestSignatures
        self.quality_str_to_pos: Dict[bytes32, ProofOfSpace] = {}

        # number of responses to each challenge
        self.number_of_responses: Dict[bytes32, int] = {}

        self.constants = consensus_constants
        self._shut_down = False
        self.server = None
        self.keychain = keychain
        self.state_changed_callback: Optional[Callable] = None

        if len(self._get_public_keys()) == 0:
            error_str = "No keys exist. Please run 'chia keys generate' or open the UI."
            raise RuntimeError(error_str)

        # This is the farmer configuration
        self.wallet_target = decode_puzzle_hash(self.config["xch_target_address"])
        self.pool_public_keys = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in self.config["pool_public_keys"]]

        # This is the pool configuration, which should be moved out to the pool once it exists
        self.pool_target = decode_puzzle_hash(pool_config["xch_target_address"])
        self.pool_sks_map: Dict = {}
        for key in self._get_private_keys():
            self.pool_sks_map[bytes(key.get_g1())] = key

        assert len(self.wallet_target) == 32
        assert len(self.pool_target) == 32
        if len(self.pool_sks_map) == 0:
            error_str = "No keys exist. Please run 'chia keys generate' or open the UI."
            raise RuntimeError(error_str)

    async def _start(self):
        pass

    def _close(self):
        pass

    async def _await_closed(self):
        pass

    async def _on_connect(self):
        # Sends a handshake to the harvester
        msg = harvester_protocol.HarvesterHandshake(self._get_public_keys(), self.pool_public_keys)
        yield OutboundMessage(NodeType.HARVESTER, Message("harvester_handshake", msg), Delivery.RESPOND)
        if self.latest_challenge is not None and len(self.icps[self.latest_challenge]) > 0:
            message = harvester_protocol.NewChallenge(self.icps[self.latest_challenge][0].challenge_hash)
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
        return [child_sk.get_g1() for child_sk in self._get_private_keys()]

    def _get_private_keys(self):
        all_sks = self.keychain.get_all_private_keys()
        return [master_sk_to_farmer_sk(sk) for sk, _ in all_sks] + [master_sk_to_pool_sk(sk) for sk, _ in all_sks]

    @api_request
    async def challenge_response(self, challenge_response: harvester_protocol.ChallengeResponse):
        """
        This is a response from the harvester, for a NewChallenge. Here we check if the proof
        of space is sufficiently good, and if so, we ask for the whole proof.
        """
        if challenge_response.challenge_hash not in self.number_of_responses:
            self.number_of_responses[challenge_response.challenge_hash] = 0

        if self.number_of_responses[challenge_response.challenge_hash] >= 32:
            log.warning(
                f"Surpassed 32 PoSpace for one challenge, no longer submitting PoSpace for challenge "
                f"{challenge_response.challenge_hash}"
            )
            return

        difficulty: uint64 = uint64(0)
        for icp in self.icps[challenge_response.challenge_hash]:
            if icp.challenge_hash == challenge_response.challenge_hash:
                difficulty = icp.difficulty
        if difficulty == 0:
            raise RuntimeError("Did not find challenge")

        required_iters: uint64 = calculate_iterations_quality(
            challenge_response.quality_string,
            challenge_response.plot_size,
            difficulty,
        )

        if challenge_response.challenge_hash not in self.icps:
            log.warning(f"Received response for challenge that we do not have {challenge_response.challenge_hash}")
            return
        elif len(self.icps[challenge_response.challenge_hash]) == 0:
            log.warning(f"Received response for challenge {challenge_response.challenge_hash} with no icp data")
            return

        slot_iters = self.icps[challenge_response.challenge_hash][0].slot_iterations

        if required_iters < slot_iters or required_iters < self.config["pool_share_threshold"]:
            self.number_of_responses[challenge_response.challenge_hash] += 1
            log.info(f"Required_iters: {required_iters}, PoSpace potentially eligible")
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
        else:
            log.info(f"Required_iters: {required_iters}, too high. Must be < slot_iters={slot_iters}")

    @api_request
    async def respond_proof_of_space(self, response: harvester_protocol.RespondProofOfSpace):
        """
        This is a response from the harvester with a proof of space. We check it's validity,
        and request a pool partial, a header signature, or both, if the proof is good enough.
        """
        if response.proof.challenge_hash not in self.icps:
            log.warning(f"Received proof of space for non-existent challenge hash {response.proof.challenge_hash}")
        computed_quality_string = response.proof.verify_and_get_quality_string(self.constants, None, None)
        if computed_quality_string is None:
            raise RuntimeError("Invalid proof of space")

        if response.proof.challenge_hash not in self.proofs_of_space:
            self.proofs_of_space[response.proof.challenge_hash] = [response.proof]
        else:
            self.proofs_of_space[response.proof.challenge_hash].append(response.proof)
        self.quality_str_to_pos[computed_quality_string] = response.proof

        # Requests signatures for the first icp (maybe the second if we were really slow at getting proofs)
        for icp in self.icps[response.proof.challenge_hash]:
            request = harvester_protocol.RequestSignatures(
                response.plot_id, response.proof.challenge_hash, [icp.challenge_chain_icp, icp.reward_chain_icp]
            )

            yield OutboundMessage(
                NodeType.HARVESTER,
                Message("request_signatures", request),
                Delivery.RESPOND,
            )

    @api_request
    async def respond_signatures(self, response: harvester_protocol.RespondSignatures):
        """
        There are two cases: receiving signatures for icps, or receiving signatures for the block.
        """
        if response.challenge_hash not in self.icps:
            log.warning(f"Do not have challenge hash {response.challenge_hash}")
            return
        is_icp_signatures: bool = False
        for icp in self.icps[response.challenge_hash]:
            if icp.challenge_chain_icp == response.message_signatures[0]:
                assert icp.reward_chain_icp == response.message_signatures[1]
                is_icp_signatures = True
                break

        pospace = None
        for candidate_pospace in self.proofs_of_space[response.challenge_hash]:
            if candidate_pospace.get_plot_id() == response.plot_id:
                pospace = candidate_pospace
        assert pospace is not None

        if is_icp_signatures:
            challenge_chain_icp, challenge_chain_icp_harv_sig = response.message_signatures[0]
            reward_chain_icp, reward_chain_icp_harv_sig = response.message_signatures[1]
            for sk in self._get_private_keys():
                pk = sk.get_g1()
                if pk == response.farmer_pk:
                    agg_pk = ProofOfSpace.generate_plot_public_key(response.local_pk, pk)
                    assert agg_pk == pospace.plot_public_key
                    farmer_share_cc_icp = AugSchemeMPL.sign(sk, challenge_chain_icp, agg_pk)
                    agg_sig_cc_icp = AugSchemeMPL.aggregate([challenge_chain_icp_harv_sig, farmer_share_cc_icp])
                    assert AugSchemeMPL.verify(agg_pk, challenge_chain_icp, agg_sig_cc_icp)

                    computed_quality_string = pospace.verify_and_get_quality_string(
                        self.constants, challenge_chain_icp, agg_sig_cc_icp
                    )

                    # This means it passes the icp filter
                    if computed_quality_string is not None:
                        farmer_share_rc_icp = AugSchemeMPL.sign(sk, reward_chain_icp, agg_pk)
                        agg_sig_rc_icp = AugSchemeMPL.aggregate([reward_chain_icp_harv_sig, farmer_share_rc_icp])
                        assert AugSchemeMPL.verify(agg_pk, reward_chain_icp, agg_sig_rc_icp)
                        request = farmer_protocol.DeclareProofOfSpace(
                            challenge_chain_icp, pospace, computed_quality_string, agg_sig_cc_icp, agg_sig_rc_icp
                        )
                        yield OutboundMessage(
                            NodeType.FULL_NODE,
                            Message("declare_proof_of_space", request),
                            Delivery.BROADCAST,
                        )
                        return

        else:
            # This is a response with block signatures
            for sk in self._get_private_keys():
                reward_sub_block_hash, reward_sub_block_sig_harvester = response.message_signatures[0]
                foliage_block_hash, foliage_block_sig_harvester = response.message_signatures[1]
                pk = sk.get_g1()
                if pk == response.farmer_pk:
                    computed_quality_string = pospace.verify_and_get_quality_string(self.constants, None, None)
                    pool_pk = bytes(pospace.pool_public_key)
                    if pool_pk not in self.pool_sks_map:
                        log.error(f"Don't have the private key for the pool key used by harvester: {pool_pk.hex()}")
                        return
                    pool_target: PoolTarget = PoolTarget(self.pool_target, uint32(0))
                    pool_target_signature: G2Element = AugSchemeMPL.sign(self.pool_sks_map[pool_pk], bytes(pool_target))

                    agg_pk = ProofOfSpace.generate_plot_public_key(response.local_pk, pk)
                    assert agg_pk == pospace.plot_public_key
                    reward_sub_block_sig_farmer = AugSchemeMPL.sign(sk, reward_sub_block_hash, agg_pk)
                    foliage_block_sig_farmer = AugSchemeMPL.sign(sk, foliage_block_hash, agg_pk)
                    reward_sub_block_agg_sig = AugSchemeMPL.aggregate(
                        [reward_sub_block_sig_harvester, reward_sub_block_sig_farmer]
                    )
                    foliage_block_agg_sig = AugSchemeMPL.aggregate(
                        [foliage_block_sig_harvester, foliage_block_sig_farmer]
                    )
                    assert AugSchemeMPL.verify(agg_pk, reward_sub_block_hash, reward_sub_block_agg_sig)
                    assert AugSchemeMPL.verify(agg_pk, foliage_block_hash, foliage_block_agg_sig)

                    request = farmer_protocol.SignedValues(
                        computed_quality_string,
                        pospace,
                        self.wallet_target,
                        pool_target,
                        pool_target_signature,
                        reward_sub_block_agg_sig,
                        foliage_block_agg_sig,
                    )

                    yield OutboundMessage(
                        NodeType.FULL_NODE,
                        Message("signed_values", request),
                        Delivery.BROADCAST,
                    )

    """
    FARMER PROTOCOL (FARMER <-> FULL NODE)
    """

    @api_request
    async def infusion_challenge_point(self, infusion_challenge_point: farmer_protocol.InfusionChallengePoint):
        if infusion_challenge_point.challenge_hash not in self.seen_challenges:
            message = harvester_protocol.NewChallenge(infusion_challenge_point.challenge_hash)
            yield OutboundMessage(
                NodeType.HARVESTER,
                Message("new_challenge", message),
                Delivery.BROADCAST,
            )
            self.seen_challenges.add(infusion_challenge_point.challenge_hash)
            # This allows time for the collection of estimates from the harvesters
            self._state_changed("challenge")
            for _ in range(20):
                if self._shut_down:
                    return
                await asyncio.sleep(1)
            self._state_changed("challenge")

        if self.latest_challenge != infusion_challenge_point.challenge_hash:
            self.latest_challenge = infusion_challenge_point.challenge_hash

        if self.latest_challenge not in self.icps:
            self.icps[self.latest_challenge] = [infusion_challenge_point]
        else:
            self.icps[self.latest_challenge].append(infusion_challenge_point)

        # We already have fetched proofs for this challenge
        if infusion_challenge_point.challenge_hash in self.proofs_of_space:
            for pospace in self.proofs_of_space[infusion_challenge_point.challenge_hash]:
                request = harvester_protocol.RequestSignatures(
                    pospace.get_plot_id(),
                    infusion_challenge_point.challenge_hash,
                    [infusion_challenge_point.challenge_chain_icp, infusion_challenge_point.reward_chain_icp],
                )

                yield OutboundMessage(
                    NodeType.HARVESTER,
                    Message("request_signatures", request),
                    Delivery.BROADCAST,
                )

    @api_request
    async def request_signed_values(self, full_node_request: farmer_protocol.RequestSignedValues):
        if full_node_request.quality_string not in self.quality_str_to_pos:
            log.error(f"Do not have quality string {full_node_request.quality_string}")
            return

        pospace = self.quality_str_to_pos[full_node_request.quality_string]
        request = harvester_protocol.RequestSignatures(
            pospace.get_plot_id(),
            pospace.challenge_hash,
            [full_node_request.reward_block_hash, full_node_request.transaction_block_hash],
        )

        yield OutboundMessage(
            NodeType.HARVESTER,
            Message("request_signatures", request),
            Delivery.BROADCAST,
        )
