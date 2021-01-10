import time
from typing import Callable

from blspy import AugSchemeMPL, G2Element
import src.server.ws_connection as ws

from src.consensus.pot_iterations import (
    calculate_iterations_quality,
    calculate_sp_interval_iters,
)
from src.farmer.farmer import Farmer
from src.protocols import harvester_protocol, farmer_protocol
from src.server.outbound_message import Message, NodeType
from src.types.pool_target import PoolTarget
from src.types.proof_of_space import ProofOfSpace
from src.util.api_decorators import api_request, peer_required
from src.util.ints import uint32, uint64


class FarmerAPI:
    farmer: Farmer

    def __init__(self, farmer):
        self.farmer = farmer

    def _set_state_changed_callback(self, callback: Callable):
        self.farmer.state_changed_callback = callback

    @api_request
    @peer_required
    async def new_proof_of_space(
        self, new_proof_of_space: harvester_protocol.NewProofOfSpace, peer: ws.WSChiaConnection
    ):
        """
        This is a response from the harvester, for a NewChallenge. Here we check if the proof
        of space is sufficiently good, and if so, we ask for the whole proof.
        """
        if new_proof_of_space.sp_hash not in self.farmer.number_of_responses:
            self.farmer.number_of_responses[new_proof_of_space.sp_hash] = 0
            self.farmer.cache_add_time[new_proof_of_space.sp_hash] = uint64(int(time.time()))

        self.farmer.state_changed("proof", {"proof": new_proof_of_space})
        max_pos_per_sp = 5
        if self.farmer.number_of_responses[new_proof_of_space.sp_hash] > max_pos_per_sp:
            self.farmer.log.warning(
                f"Surpassed {max_pos_per_sp} PoSpace for one SP, no longer submitting PoSpace for signage point "
                f"{new_proof_of_space.sp_hash}"
            )
            return

        if new_proof_of_space.sp_hash not in self.farmer.sps:
            self.farmer.log.warning(
                f"Received response for a signage point that we do not have {new_proof_of_space.sp_hash}"
            )
            return

        sps = self.farmer.sps[new_proof_of_space.sp_hash]
        for sp in sps:
            computed_quality_string = new_proof_of_space.proof.verify_and_get_quality_string(
                self.farmer.constants,
                new_proof_of_space.challenge_hash,
                new_proof_of_space.sp_hash,
            )
            if computed_quality_string is None:
                self.farmer.log.error(f"Invalid proof of space {new_proof_of_space.proof}")
                return

            self.farmer.number_of_responses[new_proof_of_space.sp_hash] += 1

            required_iters: uint64 = calculate_iterations_quality(
                computed_quality_string,
                new_proof_of_space.proof.size,
                sp.difficulty,
                new_proof_of_space.sp_hash,
            )
            # Double check that the iters are good
            assert required_iters < calculate_sp_interval_iters(self.farmer.constants, sp.sub_slot_iters)

            self.farmer.state_changed("proof", {"proof": new_proof_of_space})

            # Proceed at getting the signatures for this PoSpace
            request = harvester_protocol.RequestSignatures(
                new_proof_of_space.plot_identifier,
                new_proof_of_space.challenge_hash,
                new_proof_of_space.sp_hash,
                [sp.challenge_chain_sp, sp.reward_chain_sp],
            )

            if new_proof_of_space.sp_hash not in self.farmer.proofs_of_space:
                self.farmer.proofs_of_space[new_proof_of_space.sp_hash] = [
                    (
                        new_proof_of_space.plot_identifier,
                        new_proof_of_space.proof,
                    )
                ]
            else:
                self.farmer.proofs_of_space[new_proof_of_space.sp_hash].append(
                    (
                        new_proof_of_space.plot_identifier,
                        new_proof_of_space.proof,
                    )
                )
            self.farmer.cache_add_time[new_proof_of_space.sp_hash] = uint64(int(time.time()))
            self.farmer.quality_str_to_identifiers[computed_quality_string] = (
                new_proof_of_space.plot_identifier,
                new_proof_of_space.challenge_hash,
                new_proof_of_space.sp_hash,
                peer.peer_node_id,
            )
            self.farmer.cache_add_time[computed_quality_string] = uint64(int(time.time()))

            return Message("request_signatures", request)

    @api_request
    async def respond_signatures(self, response: harvester_protocol.RespondSignatures):
        """
        There are two cases: receiving signatures for sps, or receiving signatures for the block.
        """
        if response.sp_hash not in self.farmer.sps:
            self.farmer.log.warning(f"Do not have challenge hash {response.challenge_hash}")
            return
        is_sp_signatures: bool = False
        sps = self.farmer.sps[response.sp_hash]
        signage_point_index = sps[0].signage_point_index
        found_sp_hash_debug = False
        for sp_candidate in sps:
            if response.sp_hash == response.message_signatures[0][0]:
                found_sp_hash_debug = True
                if sp_candidate.reward_chain_sp == response.message_signatures[1][0]:
                    is_sp_signatures = True
        if found_sp_hash_debug:
            assert is_sp_signatures

        pospace = None
        for plot_identifier, candidate_pospace in self.farmer.proofs_of_space[response.sp_hash]:
            if plot_identifier == response.plot_identifier:
                pospace = candidate_pospace
        assert pospace is not None

        computed_quality_string = pospace.verify_and_get_quality_string(
            self.farmer.constants, response.challenge_hash, response.sp_hash
        )
        if computed_quality_string is None:
            self.farmer.log.warning(f"Have invalid PoSpace {pospace}")
            return

        if is_sp_signatures:
            (
                challenge_chain_sp,
                challenge_chain_sp_harv_sig,
            ) = response.message_signatures[0]
            reward_chain_sp, reward_chain_sp_harv_sig = response.message_signatures[1]
            for sk in self.farmer.get_private_keys():
                pk = sk.get_g1()
                if pk == response.farmer_pk:
                    agg_pk = ProofOfSpace.generate_plot_public_key(response.local_pk, pk)
                    assert agg_pk == pospace.plot_public_key
                    farmer_share_cc_sp = AugSchemeMPL.sign(sk, challenge_chain_sp, agg_pk)
                    agg_sig_cc_sp = AugSchemeMPL.aggregate([challenge_chain_sp_harv_sig, farmer_share_cc_sp])
                    assert AugSchemeMPL.verify(agg_pk, challenge_chain_sp, agg_sig_cc_sp)

                    # This means it passes the sp filter
                    farmer_share_rc_sp = AugSchemeMPL.sign(sk, reward_chain_sp, agg_pk)
                    agg_sig_rc_sp = AugSchemeMPL.aggregate([reward_chain_sp_harv_sig, farmer_share_rc_sp])
                    assert AugSchemeMPL.verify(agg_pk, reward_chain_sp, agg_sig_rc_sp)

                    assert pospace.pool_public_key is not None
                    pool_pk = bytes(pospace.pool_public_key)
                    if pool_pk not in self.farmer.pool_sks_map:
                        self.farmer.log.error(
                            f"Don't have the private key for the pool key used by harvester: {pool_pk.hex()}"
                        )
                        return
                    pool_target: PoolTarget = PoolTarget(self.farmer.pool_target, uint32(0))
                    pool_target_signature: G2Element = AugSchemeMPL.sign(
                        self.farmer.pool_sks_map[pool_pk], bytes(pool_target)
                    )
                    request = farmer_protocol.DeclareProofOfSpace(
                        response.challenge_hash,
                        challenge_chain_sp,
                        signage_point_index,
                        reward_chain_sp,
                        pospace,
                        agg_sig_cc_sp,
                        agg_sig_rc_sp,
                        self.farmer.wallet_target,
                        pool_target,
                        pool_target_signature,
                    )

                    msg = Message("declare_proof_of_space", request)
                    await self.farmer.server.send_to_all([msg], NodeType.FULL_NODE)
                    return

        else:
            # This is a response with block signatures
            for sk in self.farmer.get_private_keys():
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

                    request_to_nodes = farmer_protocol.SignedValues(
                        computed_quality_string,
                        foliage_sub_block_agg_sig,
                        foliage_block_agg_sig,
                    )

                    msg = Message("signed_values", request_to_nodes)
                    await self.farmer.server.send_to_all([msg], NodeType.FULL_NODE)

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

        msg = Message("new_signage_point", message)
        await self.farmer.server.send_to_all([msg], NodeType.HARVESTER)
        if new_signage_point.challenge_chain_sp not in self.farmer.sps:
            self.farmer.sps[new_signage_point.challenge_chain_sp] = []
        self.farmer.sps[new_signage_point.challenge_chain_sp].append(new_signage_point)
        self.farmer.cache_add_time[new_signage_point.challenge_chain_sp] = uint64(int(time.time()))
        self.farmer.state_changed("signage_point", {"sp_hash": new_signage_point.challenge_chain_sp})

    @api_request
    async def request_signed_values(self, full_node_request: farmer_protocol.RequestSignedValues):
        if full_node_request.quality_string not in self.farmer.quality_str_to_identifiers:
            self.farmer.log.error(f"Do not have quality string {full_node_request.quality_string}")
            return

        (plot_identifier, challenge_hash, sp_hash, node_id) = self.farmer.quality_str_to_identifiers[
            full_node_request.quality_string
        ]
        request = harvester_protocol.RequestSignatures(
            plot_identifier,
            challenge_hash,
            sp_hash,
            [full_node_request.foliage_sub_block_hash, full_node_request.foliage_block_hash],
        )

        msg = Message("request_signatures", request)
        await self.farmer.server.send_to_specific([msg], node_id)
