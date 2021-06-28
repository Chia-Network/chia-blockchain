import json
import time
from typing import Callable, Optional, List, Any, Dict

import aiohttp
from blspy import AugSchemeMPL, G2Element, PrivateKey

import chia.server.ws_connection as ws
from chia.consensus.pot_iterations import calculate_iterations_quality, calculate_sp_interval_iters
from chia.farmer.farmer import Farmer
from chia.protocols import farmer_protocol, harvester_protocol
from chia.protocols.harvester_protocol import PoolDifficulty
from chia.protocols.pool_protocol import (
    get_current_authentication_token,
    PoolErrorCode,
    PostPartialRequest,
    PostPartialPayload,
)
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import NodeType, make_msg
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.proof_of_space import ProofOfSpace
from chia.util.api_decorators import api_request, peer_required
from chia.util.ints import uint32, uint64


class FarmerAPI:
    farmer: Farmer

    def __init__(self, farmer) -> None:
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

        max_pos_per_sp = 5
        if self.farmer.number_of_responses[new_proof_of_space.sp_hash] > max_pos_per_sp:
            # This will likely never happen for any farmer with less than 10% of global space
            # It's meant to make testnets more stable
            self.farmer.log.info(
                f"Surpassed {max_pos_per_sp} PoSpace for one SP, no longer submitting PoSpace for signage point "
                f"{new_proof_of_space.sp_hash}"
            )
            return None

        if new_proof_of_space.sp_hash not in self.farmer.sps:
            self.farmer.log.warning(
                f"Received response for a signage point that we do not have {new_proof_of_space.sp_hash}"
            )
            return None

        sps = self.farmer.sps[new_proof_of_space.sp_hash]
        for sp in sps:
            computed_quality_string = new_proof_of_space.proof.verify_and_get_quality_string(
                self.farmer.constants,
                new_proof_of_space.challenge_hash,
                new_proof_of_space.sp_hash,
            )
            if computed_quality_string is None:
                self.farmer.log.error(f"Invalid proof of space {new_proof_of_space.proof}")
                return None

            self.farmer.number_of_responses[new_proof_of_space.sp_hash] += 1

            required_iters: uint64 = calculate_iterations_quality(
                self.farmer.constants.DIFFICULTY_CONSTANT_FACTOR,
                computed_quality_string,
                new_proof_of_space.proof.size,
                sp.difficulty,
                new_proof_of_space.sp_hash,
            )

            # If the iters are good enough to make a block, proceed with the block making flow
            if required_iters < calculate_sp_interval_iters(self.farmer.constants, sp.sub_slot_iters):
                # Proceed at getting the signatures for this PoSpace
                request = harvester_protocol.RequestSignatures(
                    new_proof_of_space.plot_identifier,
                    new_proof_of_space.challenge_hash,
                    new_proof_of_space.sp_hash,
                    [sp.challenge_chain_sp, sp.reward_chain_sp],
                )

                if new_proof_of_space.sp_hash not in self.farmer.proofs_of_space:
                    self.farmer.proofs_of_space[new_proof_of_space.sp_hash] = []
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

                await peer.send_message(make_msg(ProtocolMessageTypes.request_signatures, request))

            p2_singleton_puzzle_hash = new_proof_of_space.proof.pool_contract_puzzle_hash
            if p2_singleton_puzzle_hash is not None:
                # Otherwise, send the proof of space to the pool
                # When we win a block, we also send the partial to the pool
                if p2_singleton_puzzle_hash not in self.farmer.pool_state:
                    self.farmer.log.info(f"Did not find pool info for {p2_singleton_puzzle_hash}")
                    return
                pool_state_dict: Dict = self.farmer.pool_state[p2_singleton_puzzle_hash]
                pool_url = pool_state_dict["pool_config"].pool_url
                if pool_url == "":
                    return

                if pool_state_dict["current_difficulty"] is None:
                    self.farmer.log.warning(
                        f"No pool specific difficulty has been set for {p2_singleton_puzzle_hash}, "
                        f"check communication with the pool, skipping this partial to {pool_url}."
                    )
                    return

                required_iters = calculate_iterations_quality(
                    self.farmer.constants.DIFFICULTY_CONSTANT_FACTOR,
                    computed_quality_string,
                    new_proof_of_space.proof.size,
                    pool_state_dict["current_difficulty"],
                    new_proof_of_space.sp_hash,
                )
                if required_iters >= calculate_sp_interval_iters(
                    self.farmer.constants, self.farmer.constants.POOL_SUB_SLOT_ITERS
                ):
                    self.farmer.log.info(
                        f"Proof of space not good enough for pool {pool_url}: {pool_state_dict['current_difficulty']}"
                    )
                    return

                authentication_token_timeout = pool_state_dict["authentication_token_timeout"]
                if authentication_token_timeout is None:
                    self.farmer.log.warning(
                        f"No pool specific authentication_token_timeout has been set for {p2_singleton_puzzle_hash}"
                        f", check communication with the pool."
                    )
                    return

                # Submit partial to pool
                is_eos = new_proof_of_space.signage_point_index == 0

                payload = PostPartialPayload(
                    pool_state_dict["pool_config"].launcher_id,
                    get_current_authentication_token(authentication_token_timeout),
                    new_proof_of_space.proof,
                    new_proof_of_space.sp_hash,
                    is_eos,
                    peer.peer_node_id,
                )

                # The plot key is 2/2 so we need the harvester's half of the signature
                m_to_sign = payload.get_hash()
                request = harvester_protocol.RequestSignatures(
                    new_proof_of_space.plot_identifier,
                    new_proof_of_space.challenge_hash,
                    new_proof_of_space.sp_hash,
                    [m_to_sign],
                )
                response: Any = await peer.request_signatures(request)
                if not isinstance(response, harvester_protocol.RespondSignatures):
                    self.farmer.log.error(f"Invalid response from harvester: {response}")
                    return

                assert len(response.message_signatures) == 1

                plot_signature: Optional[G2Element] = None
                for sk in self.farmer.get_private_keys():
                    pk = sk.get_g1()
                    if pk == response.farmer_pk:
                        agg_pk = ProofOfSpace.generate_plot_public_key(response.local_pk, pk, True)
                        assert agg_pk == new_proof_of_space.proof.plot_public_key
                        sig_farmer = AugSchemeMPL.sign(sk, m_to_sign, agg_pk)
                        taproot_sk: PrivateKey = ProofOfSpace.generate_taproot_sk(response.local_pk, pk)
                        taproot_sig: G2Element = AugSchemeMPL.sign(taproot_sk, m_to_sign, agg_pk)

                        plot_signature = AugSchemeMPL.aggregate(
                            [sig_farmer, response.message_signatures[0][1], taproot_sig]
                        )
                        assert AugSchemeMPL.verify(agg_pk, m_to_sign, plot_signature)
                authentication_pk = pool_state_dict["pool_config"].authentication_public_key
                if bytes(authentication_pk) is None:
                    self.farmer.log.error(f"No authentication sk for {authentication_pk}")
                    return
                authentication_sk: PrivateKey = self.farmer.authentication_keys[bytes(authentication_pk)]
                authentication_signature = AugSchemeMPL.sign(authentication_sk, m_to_sign)

                assert plot_signature is not None

                agg_sig: G2Element = AugSchemeMPL.aggregate([plot_signature, authentication_signature])

                post_partial_request: PostPartialRequest = PostPartialRequest(payload, agg_sig)
                post_partial_body = json.dumps(post_partial_request.to_json_dict())
                self.farmer.log.info(
                    f"Submitting partial for {post_partial_request.payload.launcher_id.hex()} to {pool_url}"
                )
                pool_state_dict["points_found_since_start"] += pool_state_dict["current_difficulty"]
                pool_state_dict["points_found_24h"].append((time.time(), pool_state_dict["current_difficulty"]))
                headers = {
                    "content-type": "application/json;",
                }
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(f"{pool_url}/partial", data=post_partial_body, headers=headers) as resp:
                            if resp.ok:
                                pool_response: Dict = json.loads(await resp.text())
                                self.farmer.log.info(f"Pool response: {pool_response}")
                                if "error_code" in pool_response:
                                    self.farmer.log.error(
                                        f"Error in pooling: "
                                        f"{pool_response['error_code'], pool_response['error_message']}"
                                    )
                                    pool_state_dict["pool_errors_24h"].append(pool_response)
                                    if pool_response["error_code"] == PoolErrorCode.PROOF_NOT_GOOD_ENOUGH.value:
                                        self.farmer.log.error(
                                            "Partial not good enough, forcing pool farmer update to "
                                            "get our current difficulty."
                                        )
                                        pool_state_dict["next_farmer_update"] = 0
                                        await self.farmer.update_pool_state()
                                else:
                                    new_difficulty = pool_response["new_difficulty"]
                                    pool_state_dict["points_acknowledged_since_start"] += new_difficulty
                                    pool_state_dict["points_acknowledged_24h"].append((time.time(), new_difficulty))
                                    pool_state_dict["current_difficulty"] = new_difficulty
                            else:
                                self.farmer.log.error(f"Error sending partial to {pool_url}, {resp.status}")
                except Exception as e:
                    self.farmer.log.error(f"Error connecting to pool: {e}")
                    return

                return

    @api_request
    async def respond_signatures(self, response: harvester_protocol.RespondSignatures):
        """
        There are two cases: receiving signatures for sps, or receiving signatures for the block.
        """
        if response.sp_hash not in self.farmer.sps:
            self.farmer.log.warning(f"Do not have challenge hash {response.challenge_hash}")
            return None
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
        include_taproot: bool = pospace.pool_contract_puzzle_hash is not None

        computed_quality_string = pospace.verify_and_get_quality_string(
            self.farmer.constants, response.challenge_hash, response.sp_hash
        )
        if computed_quality_string is None:
            self.farmer.log.warning(f"Have invalid PoSpace {pospace}")
            return None

        if is_sp_signatures:
            (
                challenge_chain_sp,
                challenge_chain_sp_harv_sig,
            ) = response.message_signatures[0]
            reward_chain_sp, reward_chain_sp_harv_sig = response.message_signatures[1]
            for sk in self.farmer.get_private_keys():
                pk = sk.get_g1()
                if pk == response.farmer_pk:
                    agg_pk = ProofOfSpace.generate_plot_public_key(response.local_pk, pk, include_taproot)
                    assert agg_pk == pospace.plot_public_key
                    if include_taproot:
                        taproot_sk: PrivateKey = ProofOfSpace.generate_taproot_sk(response.local_pk, pk)
                        taproot_share_cc_sp: G2Element = AugSchemeMPL.sign(taproot_sk, challenge_chain_sp, agg_pk)
                        taproot_share_rc_sp: G2Element = AugSchemeMPL.sign(taproot_sk, reward_chain_sp, agg_pk)
                    else:
                        taproot_share_cc_sp = G2Element()
                        taproot_share_rc_sp = G2Element()
                    farmer_share_cc_sp = AugSchemeMPL.sign(sk, challenge_chain_sp, agg_pk)
                    agg_sig_cc_sp = AugSchemeMPL.aggregate(
                        [challenge_chain_sp_harv_sig, farmer_share_cc_sp, taproot_share_cc_sp]
                    )
                    assert AugSchemeMPL.verify(agg_pk, challenge_chain_sp, agg_sig_cc_sp)

                    # This means it passes the sp filter
                    farmer_share_rc_sp = AugSchemeMPL.sign(sk, reward_chain_sp, agg_pk)
                    agg_sig_rc_sp = AugSchemeMPL.aggregate(
                        [reward_chain_sp_harv_sig, farmer_share_rc_sp, taproot_share_rc_sp]
                    )
                    assert AugSchemeMPL.verify(agg_pk, reward_chain_sp, agg_sig_rc_sp)

                    if pospace.pool_public_key is not None:
                        assert pospace.pool_contract_puzzle_hash is None
                        pool_pk = bytes(pospace.pool_public_key)
                        if pool_pk not in self.farmer.pool_sks_map:
                            self.farmer.log.error(
                                f"Don't have the private key for the pool key used by harvester: {pool_pk.hex()}"
                            )
                            return None

                        pool_target: Optional[PoolTarget] = PoolTarget(self.farmer.pool_target, uint32(0))
                        assert pool_target is not None
                        pool_target_signature: Optional[G2Element] = AugSchemeMPL.sign(
                            self.farmer.pool_sks_map[pool_pk], bytes(pool_target)
                        )
                    else:
                        assert pospace.pool_contract_puzzle_hash is not None
                        pool_target = None
                        pool_target_signature = None

                    request = farmer_protocol.DeclareProofOfSpace(
                        response.challenge_hash,
                        challenge_chain_sp,
                        signage_point_index,
                        reward_chain_sp,
                        pospace,
                        agg_sig_cc_sp,
                        agg_sig_rc_sp,
                        self.farmer.farmer_target,
                        pool_target,
                        pool_target_signature,
                    )
                    self.farmer.state_changed("proof", {"proof": request, "passed_filter": True})
                    msg = make_msg(ProtocolMessageTypes.declare_proof_of_space, request)
                    await self.farmer.server.send_to_all([msg], NodeType.FULL_NODE)
                    return None

        else:
            # This is a response with block signatures
            for sk in self.farmer.get_private_keys():
                (
                    foliage_block_data_hash,
                    foliage_sig_harvester,
                ) = response.message_signatures[0]
                (
                    foliage_transaction_block_hash,
                    foliage_transaction_block_sig_harvester,
                ) = response.message_signatures[1]
                pk = sk.get_g1()
                if pk == response.farmer_pk:
                    agg_pk = ProofOfSpace.generate_plot_public_key(response.local_pk, pk, include_taproot)
                    assert agg_pk == pospace.plot_public_key
                    if include_taproot:
                        taproot_sk = ProofOfSpace.generate_taproot_sk(response.local_pk, pk)
                        foliage_sig_taproot: G2Element = AugSchemeMPL.sign(taproot_sk, foliage_block_data_hash, agg_pk)
                        foliage_transaction_block_sig_taproot: G2Element = AugSchemeMPL.sign(
                            taproot_sk, foliage_transaction_block_hash, agg_pk
                        )
                    else:
                        foliage_sig_taproot = G2Element()
                        foliage_transaction_block_sig_taproot = G2Element()

                    foliage_sig_farmer = AugSchemeMPL.sign(sk, foliage_block_data_hash, agg_pk)
                    foliage_transaction_block_sig_farmer = AugSchemeMPL.sign(sk, foliage_transaction_block_hash, agg_pk)

                    foliage_agg_sig = AugSchemeMPL.aggregate(
                        [foliage_sig_harvester, foliage_sig_farmer, foliage_sig_taproot]
                    )
                    foliage_block_agg_sig = AugSchemeMPL.aggregate(
                        [
                            foliage_transaction_block_sig_harvester,
                            foliage_transaction_block_sig_farmer,
                            foliage_transaction_block_sig_taproot,
                        ]
                    )
                    assert AugSchemeMPL.verify(agg_pk, foliage_block_data_hash, foliage_agg_sig)
                    assert AugSchemeMPL.verify(agg_pk, foliage_transaction_block_hash, foliage_block_agg_sig)

                    request_to_nodes = farmer_protocol.SignedValues(
                        computed_quality_string,
                        foliage_agg_sig,
                        foliage_block_agg_sig,
                    )

                    msg = make_msg(ProtocolMessageTypes.signed_values, request_to_nodes)
                    await self.farmer.server.send_to_all([msg], NodeType.FULL_NODE)

    """
    FARMER PROTOCOL (FARMER <-> FULL NODE)
    """

    @api_request
    async def new_signage_point(self, new_signage_point: farmer_protocol.NewSignagePoint):
        pool_difficulties: List[PoolDifficulty] = []
        for p2_singleton_puzzle_hash, pool_dict in self.farmer.pool_state.items():
            if pool_dict["pool_config"].pool_url == "":
                # Self pooling
                continue

            if pool_dict["current_difficulty"] is None:
                self.farmer.log.warning(
                    f"No pool specific difficulty has been set for {p2_singleton_puzzle_hash}, "
                    f"check communication with the pool, skipping this signage point, pool: "
                    f"{pool_dict['pool_config'].pool_url} "
                )
                continue
            pool_difficulties.append(
                PoolDifficulty(
                    pool_dict["current_difficulty"],
                    self.farmer.constants.POOL_SUB_SLOT_ITERS,
                    p2_singleton_puzzle_hash,
                )
            )
        message = harvester_protocol.NewSignagePointHarvester(
            new_signage_point.challenge_hash,
            new_signage_point.difficulty,
            new_signage_point.sub_slot_iters,
            new_signage_point.signage_point_index,
            new_signage_point.challenge_chain_sp,
            pool_difficulties,
        )

        msg = make_msg(ProtocolMessageTypes.new_signage_point_harvester, message)
        await self.farmer.server.send_to_all([msg], NodeType.HARVESTER)
        if new_signage_point.challenge_chain_sp not in self.farmer.sps:
            self.farmer.sps[new_signage_point.challenge_chain_sp] = []
        if new_signage_point in self.farmer.sps[new_signage_point.challenge_chain_sp]:
            self.farmer.log.debug(f"Duplicate signage point {new_signage_point.signage_point_index}")
            return

        self.farmer.sps[new_signage_point.challenge_chain_sp].append(new_signage_point)
        self.farmer.cache_add_time[new_signage_point.challenge_chain_sp] = uint64(int(time.time()))
        self.farmer.state_changed("new_signage_point", {"sp_hash": new_signage_point.challenge_chain_sp})

    @api_request
    async def request_signed_values(self, full_node_request: farmer_protocol.RequestSignedValues):
        if full_node_request.quality_string not in self.farmer.quality_str_to_identifiers:
            self.farmer.log.error(f"Do not have quality string {full_node_request.quality_string}")
            return None

        (plot_identifier, challenge_hash, sp_hash, node_id) = self.farmer.quality_str_to_identifiers[
            full_node_request.quality_string
        ]
        request = harvester_protocol.RequestSignatures(
            plot_identifier,
            challenge_hash,
            sp_hash,
            [full_node_request.foliage_block_data_hash, full_node_request.foliage_transaction_block_hash],
        )

        msg = make_msg(ProtocolMessageTypes.request_signatures, request)
        await self.farmer.server.send_to_specific([msg], node_id)

    @api_request
    async def farming_info(self, request: farmer_protocol.FarmingInfo):
        self.farmer.state_changed(
            "new_farming_info",
            {
                "farming_info": {
                    "challenge_hash": request.challenge_hash,
                    "signage_point": request.sp_hash,
                    "passed_filter": request.passed,
                    "proofs": request.proofs,
                    "total_plots": request.total_plots,
                    "timestamp": request.timestamp,
                }
            },
        )

    @api_request
    async def respond_plots(self, _: harvester_protocol.RespondPlots):
        self.farmer.log.warning("Respond plots came too late")
