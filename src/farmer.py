import asyncio
import logging
from typing import Dict, List, Optional, Callable, Set, Tuple

from blspy import G1Element, G2Element, AugSchemeMPL
from src.util.keychain import Keychain

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_iterations_quality,
    calculate_sp_index,
)
from src.protocols import farmer_protocol, harvester_protocol
from src.server.connection import PeerConnections
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.types.proof_of_space import ProofOfSpace
from src.types.sized_bytes import bytes32
from src.types.pool_target import PoolTarget
from src.util.api_decorators import api_request
from src.util.ints import uint32, uint64, uint8
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

        # Keep track of all sps for each challenge
        self.sps: Dict[bytes32, List[farmer_protocol.SignagePoint]] = {}

        # Keep track of harvester plot identifier (str), target sp index, and PoSpace for each challenge
        self.proofs_of_space: Dict[bytes32, List[Tuple[str, uint8, ProofOfSpace]]] = {}

        # Quality string to plot identifier and challenge_hash, for use with harvester.RequestSignatures
        self.quality_str_to_identifiers: Dict[bytes32, Tuple[str, bytes32]] = {}

        # number of responses to each challenge
        self.number_of_responses: Dict[bytes32, int] = {}
        self.seen_challenges: Set[bytes32] = set()

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
        msg = harvester_protocol.HarvesterHandshake(
            self._get_public_keys(),
            self.pool_public_keys,
            self.config["pool_share_threshold"],
        )
        yield OutboundMessage(NodeType.HARVESTER, Message("harvester_handshake", msg), Delivery.RESPOND)
        if self.latest_challenge is not None and len(self.sps[self.latest_challenge]) > 0:
            sp = self.sps[self.latest_challenge][0]
            message = harvester_protocol.NewChallenge(sp.challenge_hash, sp.difficulty, sp.slot_iterations)
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
        if challenge_response.proof.challenge_hash not in self.number_of_responses:
            self.number_of_responses[challenge_response.proof.challenge_hash] = 0

        if self.number_of_responses[challenge_response.proof.challenge_hash] >= 32:
            log.warning(
                f"Surpassed 32 PoSpace for one challenge, no longer submitting PoSpace for challenge "
                f"{challenge_response.proof.challenge_hash}"
            )
            return

        difficulty: uint64 = uint64(0)
        for sp in self.sps[challenge_response.proof.challenge_hash]:
            if sp.challenge_hash == challenge_response.proof.challenge_hash:
                difficulty = sp.difficulty
        if difficulty == 0:
            log.error(f"Did not find challenge {challenge_response.proof.challenge_hash}")
            return

        computed_quality_string = challenge_response.proof.verify_and_get_quality_string(self.constants, None, None)
        if computed_quality_string is None:
            log.error(f"Invalid proof of space {challenge_response.proof}")
            return

        required_iters: uint64 = calculate_iterations_quality(
            computed_quality_string,
            challenge_response.proof.size,
            difficulty,
        )

        if challenge_response.proof.challenge_hash not in self.sps:
            log.warning(f"Received response for challenge that we do not have {challenge_response.challenge_hash}")
            return
        elif len(self.sps[challenge_response.proof.challenge_hash]) == 0:
            log.warning(f"Received response for challenge {challenge_response.challenge_hash} with no sp data")
            return

        sub_slot_iters = self.sps[challenge_response.proof.challenge_hash][0].slot_iterations

        # Double check that the iters are good
        if required_iters < sub_slot_iters or required_iters < self.config["pool_share_threshold"]:
            self.number_of_responses[challenge_response.proof.challenge_hash] += 1
            self._state_changed("challenge")
            ips = sub_slot_iters // self.constants.SLOT_TIME_TARGET
            # This is the sp which this proof of space is assigned to
            target_sp_index: uint8 = calculate_sp_index(self.constants, ips, required_iters)

            # Requests signatures for the first sp (maybe the second if we were really slow at getting proofs)
            for sp in self.sps[challenge_response.proof.challenge_hash]:
                # If we already have the target sp, proceed at getting the signatures for this PoSpace
                if sp.signage_point_index == target_sp_index:
                    request = harvester_protocol.RequestSignatures(
                        challenge_response.plot_identifier,
                        challenge_response.proof.challenge_hash,
                        [sp.challenge_chain_sp, sp.reward_chain_sp],
                    )
                    yield OutboundMessage(
                        NodeType.HARVESTER,
                        Message("request_signatures", request),
                        Delivery.RESPOND,
                    )
            if challenge_response.proof.challenge_hash not in self.proofs_of_space:
                self.proofs_of_space[challenge_response.proof.challenge_hash] = [
                    (
                        challenge_response.plot_identifier,
                        target_sp_index,
                        challenge_response.proof,
                    )
                ]
            else:
                self.proofs_of_space[challenge_response.proof.challenge_hash].append(
                    (
                        challenge_response.plot_identifier,
                        target_sp_index,
                        challenge_response.proof,
                    )
                )
            self.quality_str_to_identifiers[computed_quality_string] = (
                challenge_response.plot_identifier,
                challenge_response.proof.challenge_hash,
            )
        else:
            log.warning(f"Required_iters: {required_iters}, too high. Must be < sub_slot_iters={sub_slot_iters}")

    @api_request
    async def respond_signatures(self, response: harvester_protocol.RespondSignatures):
        """
        There are two cases: receiving signatures for sps, or receiving signatures for the block.
        """
        if response.challenge_hash not in self.sps:
            log.warning(f"Do not have challenge hash {response.challenge_hash}")
            return
        is_sp_signatures: bool = False
        for sp in self.sps[response.challenge_hash]:
            if sp.challenge_chain_sp == response.message_signatures[0]:
                assert sp.reward_chain_sp == response.message_signatures[1]
                is_sp_signatures = True
                break

        pospace = None
        for plot_identifier, _, candidate_pospace in self.proofs_of_space[response.challenge_hash]:
            if plot_identifier == response.plot_identifier:
                pospace = candidate_pospace
        assert pospace is not None

        if is_sp_signatures:
            (
                challenge_chain_sp,
                challenge_chain_sp_harv_sig,
            ) = response.message_signatures[0]
            reward_chain_sp, reward_chain_sp_harv_sig = response.message_signatures[1]
            for sk in self._get_private_keys():
                pk = sk.get_g1()
                if pk == response.farmer_pk:
                    agg_pk = ProofOfSpace.generate_plot_public_key(response.local_pk, pk)
                    assert agg_pk == pospace.plot_public_key
                    farmer_share_cc_sp = AugSchemeMPL.sign(sk, challenge_chain_sp, agg_pk)
                    agg_sig_cc_sp = AugSchemeMPL.aggregate([challenge_chain_sp_harv_sig, farmer_share_cc_sp])
                    assert AugSchemeMPL.verify(agg_pk, challenge_chain_sp, agg_sig_cc_sp)

                    computed_quality_string = pospace.verify_and_get_quality_string(
                        self.constants, challenge_chain_sp, agg_sig_cc_sp
                    )

                    # This means it passes the sp filter
                    if computed_quality_string is not None:
                        farmer_share_rc_sp = AugSchemeMPL.sign(sk, reward_chain_sp, agg_pk)
                        agg_sig_rc_sp = AugSchemeMPL.aggregate([reward_chain_sp_harv_sig, farmer_share_rc_sp])
                        assert AugSchemeMPL.verify(agg_pk, reward_chain_sp, agg_sig_rc_sp)

                        pool_pk = bytes(pospace.pool_public_key)
                        if pool_pk not in self.pool_sks_map:
                            log.error(f"Don't have the private key for the pool key used by harvester: {pool_pk.hex()}")
                            return
                        pool_target: PoolTarget = PoolTarget(self.pool_target, uint32(0))
                        pool_target_signature: G2Element = AugSchemeMPL.sign(
                            self.pool_sks_map[pool_pk], bytes(pool_target)
                        )
                        request = farmer_protocol.DeclareProofOfSpace(
                            challenge_chain_sp,
                            pospace,
                            agg_sig_cc_sp,
                            agg_sig_rc_sp,
                            self.wallet_target,
                            pool_target,
                            pool_target_signature,
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
                (
                    foliage_sub_block_hash,
                    foliage_sub_block_sig_harvester,
                ) = response.message_signatures[0]
                (
                    foliage_block_hash,
                    foliage_block_sig_harvester,
                ) = response.message_signatures[1]
                pk = sk.get_g1()
                if pk == response.farmer_pk:
                    computed_quality_string = pospace.verify_and_get_quality_string(self.constants, None, None)

                    agg_pk = ProofOfSpace.generate_plot_public_key(response.local_pk, pk)
                    assert agg_pk == pospace.plot_public_key
                    foliage_sub_block_sig_farmer = AugSchemeMPL.sign(sk, foliage_sub_block_hash, agg_pk)
                    foliage_block_sig_farmer = AugSchemeMPL.sign(sk, foliage_block_hash, agg_pk)
                    foliage_sub_block_agg_sig = AugSchemeMPL.aggregate(
                        [foliage_sub_block_sig_harvester, foliage_sub_block_sig_farmer]
                    )
                    foliage_block_agg_sig = AugSchemeMPL.aggregate(
                        [foliage_block_sig_harvester, foliage_block_sig_farmer]
                    )
                    assert AugSchemeMPL.verify(agg_pk, foliage_sub_block_hash, foliage_sub_block_agg_sig)
                    assert AugSchemeMPL.verify(agg_pk, foliage_block_hash, foliage_block_agg_sig)

                    request = farmer_protocol.SignedValues(
                        computed_quality_string,
                        foliage_sub_block_agg_sig,
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
    async def signage_point(self, signage_point: farmer_protocol.SignagePoint):
        if signage_point.challenge_hash not in self.seen_challenges:
            message = harvester_protocol.NewChallenge(
                signage_point.challenge_hash,
                signage_point.difficulty,
                signage_point.slot_iterations,
            )
            yield OutboundMessage(
                NodeType.HARVESTER,
                Message("new_challenge", message),
                Delivery.BROADCAST,
            )
            self.seen_challenges.add(signage_point.challenge_hash)
            # This allows time for the collection of proofs from the harvester
            self._state_changed("challenge")
            for _ in range(20):
                if self._shut_down:
                    return
                await asyncio.sleep(1)
            self._state_changed("challenge")

        if self.latest_challenge != signage_point.challenge_hash:
            self.latest_challenge = signage_point.challenge_hash

        if self.latest_challenge not in self.sps:
            self.sps[self.latest_challenge] = [signage_point]
        else:
            self.sps[self.latest_challenge].append(signage_point)

        # We already have fetched proofs for this challenge
        if signage_point.challenge_hash in self.proofs_of_space:
            for plot_identifier, target_sp_index, pospace in self.proofs_of_space[signage_point.challenge_hash]:
                if target_sp_index == signage_point.signage_point_index:
                    # Only proceeds with proofs of space that can be infused at this infusion point
                    request = harvester_protocol.RequestSignatures(
                        plot_identifier,
                        signage_point.challenge_hash,
                        [
                            signage_point.challenge_chain_sp,
                            signage_point.reward_chain_sp,
                        ],
                    )

                    yield OutboundMessage(
                        NodeType.HARVESTER,
                        Message("request_signatures", request),
                        Delivery.BROADCAST,
                    )

    @api_request
    async def request_signed_values(self, full_node_request: farmer_protocol.RequestSignedValues):
        if full_node_request.quality_string not in self.quality_str_to_identifiers:
            log.error(f"Do not have quality string {full_node_request.quality_string}")
            return

        plot_identifier, challenge_hash = self.quality_str_to_identifiers[full_node_request.quality_string]
        request = harvester_protocol.RequestSignatures(
            plot_identifier,
            challenge_hash,
            [
                full_node_request.foliage_sub_block_hash,
                full_node_request.foliage_block_hash,
            ],
        )

        yield OutboundMessage(
            NodeType.HARVESTER,
            Message("request_signatures", request),
            Delivery.BROADCAST,
        )
