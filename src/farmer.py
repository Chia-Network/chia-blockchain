import asyncio
import logging
from typing import Dict, List, Optional, Callable, Set, Tuple

from blspy import G1Element, G2Element, AugSchemeMPL
from src.util.keychain import Keychain

from src.consensus.constants import ConsensusConstants
from src.consensus.pot_iterations import (
    calculate_iterations_quality,
    calculate_sp_interval_iters,
)
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
        # Keep track of all sps, keyed on challenge chain signage point hash
        self.sps: Dict[bytes32, farmer_protocol.NewSignagePoint] = {}

        # Keep track of harvester plot identifier (str), target sp index, and PoSpace for each challenge
        self.proofs_of_space: Dict[bytes32, List[Tuple[str, ProofOfSpace]]] = {}

        # Quality string to plot identifier and challenge_hash, for use with harvester.RequestSignatures
        self.quality_str_to_identifiers: Dict[bytes32, Tuple[str, bytes32]] = {}

        # number of responses to each signage point
        self.number_of_responses: Dict[bytes32, int] = {}

        # A dictionary of keys to time added. These keys refer to keys in the above 4 dictionaries. This is used
        # to periodically clear the memory
        self.cache_add_time: Dict[bytes32, uint64] = {}

        self.cache_clear_task: asyncio.Task
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
        self.cache_clear_task = asyncio.create_task(self._periodically_clear_cache_task())

    def _close(self):
        self._shut_down = True

    async def _await_closed(self):
        await self.cache_clear_task

    async def _on_connect(self):
        # Sends a handshake to the harvester
        msg = harvester_protocol.HarvesterHandshake(
            self._get_public_keys(),
            self.pool_public_keys,
        )
        yield OutboundMessage(NodeType.HARVESTER, Message("harvester_handshake", msg), Delivery.RESPOND)

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

    async def _periodically_clear_cache_task(self):
        time_slept: uint64 = uint64(0)
        while not self._shut_down:
            if time_slept > self.constants.SLOT_TIME_TARGET * 10:
                removed_keys: List[bytes32] = []
                for key, add_time in self.cache_add_time.items():
                    self.sps.pop(key, None)
                    self.proofs_of_space.pop(key, None)
                    self.quality_str_to_identifiers.pop(key, None)
                    self.number_of_responses.pop(key, None)
                    removed_keys.append(key)
                for key in removed_keys:
                    self.cache_add_time.pop(key, None)
                time_slept = uint64(0)
            time_slept += 1
            await asyncio.sleep(1)

    @api_request
    async def new_proof_of_space(self, new_proof_of_space: harvester_protocol.NewProofOfSpace):
        """
        This is a response from the harvester, for a NewChallenge. Here we check if the proof
        of space is sufficiently good, and if so, we ask for the whole proof.
        """
        if new_proof_of_space.proof.challenge_hash not in self.number_of_responses:
            self.number_of_responses[new_proof_of_space.proof.challenge_hash] = 0

        if self.number_of_responses[new_proof_of_space.proof.challenge_hash] >= 5:
            log.warning(
                f"Surpassed 5 PoSpace for one SP, no longer submitting PoSpace for signage point "
                f"{new_proof_of_space.proof.challenge_hash}"
            )
            return

        if new_proof_of_space.proof.challenge_hash not in self.sps:
            log.warning(
                f"Received response for challenge that we do not have {new_proof_of_space.proof.challenge_hash}"
            )
            return

        sp = self.sps[new_proof_of_space.proof.challenge_hash]

        computed_quality_string = new_proof_of_space.proof.verify_and_get_quality_string(
            self.constants, new_proof_of_space.challenge_hash, new_proof_of_space.proof.challenge_hash
        )
        if computed_quality_string is None:
            log.error(f"Invalid proof of space {new_proof_of_space.proof}")
            return

        self.number_of_responses[new_proof_of_space.proof.challenge_hash] += 1

        required_iters: uint64 = calculate_iterations_quality(
            computed_quality_string,
            new_proof_of_space.proof.size,
            sp.difficulty,
            new_proof_of_space.proof.challenge_hash,
        )
        # Double check that the iters are good
        assert required_iters < calculate_sp_interval_iters(sp.slot_iterations, sp.sub_slot_iters)

        self._state_changed("proof")

        # Proceed at getting the signatures for this PoSpace
        request = harvester_protocol.RequestSignatures(
            new_proof_of_space.plot_identifier,
            new_proof_of_space.proof.challenge_hash,
            [sp.challenge_chain_sp, sp.reward_chain_sp],
        )
        yield OutboundMessage(
            NodeType.HARVESTER,
            Message("request_signatures", request),
            Delivery.RESPOND,
        )
        if new_proof_of_space.proof.challenge_hash not in self.proofs_of_space:
            self.proofs_of_space[new_proof_of_space.proof.challenge_hash] = [
                (
                    new_proof_of_space.plot_identifier,
                    new_proof_of_space.proof,
                )
            ]
        else:
            self.proofs_of_space[new_proof_of_space.proof.challenge_hash].append(
                (
                    new_proof_of_space.plot_identifier,
                    new_proof_of_space.proof,
                )
            )
        self.quality_str_to_identifiers[computed_quality_string] = (
            new_proof_of_space.plot_identifier,
            new_proof_of_space.proof.challenge_hash,
        )

    @api_request
    async def respond_signatures(self, response: harvester_protocol.RespondSignatures):
        """
        There are two cases: receiving signatures for sps, or receiving signatures for the block.
        """
        if response.sp_hash not in self.sps:
            log.warning(f"Do not have challenge hash {response.challenge_hash}")
            return
        is_sp_signatures: bool = False
        sp = self.sps[response.sp_hash]
        if response.sp_hash == response.message_signatures[0]:
            assert sp.reward_chain_sp == response.message_signatures[1]
            is_sp_signatures = True

        pospace = None
        for plot_identifier, _, candidate_pospace in self.proofs_of_space[response.sp_hash]:
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
                        self.constants, sp.challenge_hash, challenge_chain_sp
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
                            response.challenge_hash,
                            challenge_chain_sp,
                            sp.signage_point_index,
                            reward_chain_sp,
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
                        log.warning(f"Have invalid PoSpace {pospace}")

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
    async def new_signage_point(self, new_signage_point: farmer_protocol.NewSignagePoint):
        message = harvester_protocol.NewSignagePoint(
            new_signage_point.challenge_hash,
            new_signage_point.difficulty,
            new_signage_point.sub_slot_iters,
            new_signage_point.signage_point_index,
            new_signage_point.challenge_chain_sp,
        )
        yield OutboundMessage(
            NodeType.HARVESTER,
            Message("new_signage_point", message),
            Delivery.BROADCAST,
        )
        self.sps[new_signage_point.challenge_chain_sp] = new_signage_point
        self._state_changed("signage_point")

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
