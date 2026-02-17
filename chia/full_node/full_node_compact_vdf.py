from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING

from chia_rs.sized_ints import uint8

from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import full_node_protocol, timelord_protocol
from chia.protocols.outbound_message import NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.vdf import CompressibleVDFField, VDFInfo, VDFProof, validate_vdf

if TYPE_CHECKING:
    from chia_rs import BlockRecord, HeaderBlock
    from chia_rs.sized_bytes import bytes32
    from chia_rs.sized_ints import uint32

    from chia.full_node.full_node import FullNode
    from chia.server.ws_connection import WSChiaConnection
    from chia.types.weight_proof import WeightProof


async def _needs_compact_proof(
    self: FullNode, vdf_info: VDFInfo, header_block: HeaderBlock, field_vdf: CompressibleVDFField
) -> bool:
    if field_vdf == CompressibleVDFField.CC_EOS_VDF:
        for sub_slot in header_block.finished_sub_slots:
            if sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf == vdf_info:
                if (
                    sub_slot.proofs.challenge_chain_slot_proof.witness_type == 0
                    and sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity
                ):
                    return False
                return True
    if field_vdf == CompressibleVDFField.ICC_EOS_VDF:
        for sub_slot in header_block.finished_sub_slots:
            if (
                sub_slot.infused_challenge_chain is not None
                and sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf == vdf_info
            ):
                assert sub_slot.proofs.infused_challenge_chain_slot_proof is not None
                if (
                    sub_slot.proofs.infused_challenge_chain_slot_proof.witness_type == 0
                    and sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
                ):
                    return False
                return True
    if field_vdf == CompressibleVDFField.CC_SP_VDF:
        if header_block.reward_chain_block.challenge_chain_sp_vdf is None:
            return False
        if vdf_info == header_block.reward_chain_block.challenge_chain_sp_vdf:
            assert header_block.challenge_chain_sp_proof is not None
            if (
                header_block.challenge_chain_sp_proof.witness_type == 0
                and header_block.challenge_chain_sp_proof.normalized_to_identity
            ):
                return False
            return True
    if field_vdf == CompressibleVDFField.CC_IP_VDF:
        if vdf_info == header_block.reward_chain_block.challenge_chain_ip_vdf:
            if (
                header_block.challenge_chain_ip_proof.witness_type == 0
                and header_block.challenge_chain_ip_proof.normalized_to_identity
            ):
                return False
            return True
    return False


async def _can_accept_compact_proof(
    self: FullNode,
    vdf_info: VDFInfo,
    vdf_proof: VDFProof,
    height: uint32,
    header_hash: bytes32,
    field_vdf: CompressibleVDFField,
) -> bool:
    """
    - Checks if the provided proof is indeed compact.
    - Checks if proof verifies given the vdf_info from the start of sub-slot.
    - Checks if the provided vdf_info is correct, assuming it refers to the start of sub-slot.
    - Checks if the existing proof was non-compact. Ignore this proof if we already have a compact proof.
    """
    is_fully_compactified = await self.block_store.is_fully_compactified(header_hash)
    if is_fully_compactified is None or is_fully_compactified:
        self.log.info(f"Already compactified block: {header_hash}. Ignoring.")
        return False
    peak = self.blockchain.get_peak()
    if peak is None or peak.height - height < 5:
        self.log.debug("Will not compactify recent block")
        return False
    if vdf_proof.witness_type > 0 or not vdf_proof.normalized_to_identity:
        self.log.error(f"Received vdf proof is not compact: {vdf_proof}.")
        return False
    if not validate_vdf(vdf_proof, self.constants, ClassgroupElement.get_default_element(), vdf_info):
        self.log.error(f"Received compact vdf proof is not valid: {vdf_proof}.")
        return False
    header_block = await self.blockchain.get_header_block_by_height(height, header_hash, tx_filter=False)
    if header_block is None:
        self.log.error(f"Can't find block for given compact vdf. Height: {height} Header hash: {header_hash}")
        return False
    is_new_proof = await self._needs_compact_proof(vdf_info, header_block, field_vdf)
    if not is_new_proof:
        self.log.info(f"Duplicate compact proof. Height: {height}. Header hash: {header_hash}.")
    return is_new_proof


# returns True if we ended up replacing the proof, and False otherwise
async def _replace_proof(
    self: FullNode,
    vdf_info: VDFInfo,
    vdf_proof: VDFProof,
    header_hash: bytes32,
    field_vdf: CompressibleVDFField,
) -> bool:
    block = await self.block_store.get_full_block(header_hash)
    if block is None:
        return False

    new_block = None

    if field_vdf == CompressibleVDFField.CC_EOS_VDF:
        for index, sub_slot in enumerate(block.finished_sub_slots):
            if sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf == vdf_info:
                new_proofs = sub_slot.proofs.replace(challenge_chain_slot_proof=vdf_proof)
                new_subslot = sub_slot.replace(proofs=new_proofs)
                new_finished_subslots = block.finished_sub_slots
                new_finished_subslots[index] = new_subslot
                new_block = block.replace(finished_sub_slots=new_finished_subslots)
                break
    if field_vdf == CompressibleVDFField.ICC_EOS_VDF:
        for index, sub_slot in enumerate(block.finished_sub_slots):
            if (
                sub_slot.infused_challenge_chain is not None
                and sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf == vdf_info
            ):
                new_proofs = sub_slot.proofs.replace(infused_challenge_chain_slot_proof=vdf_proof)
                new_subslot = sub_slot.replace(proofs=new_proofs)
                new_finished_subslots = block.finished_sub_slots
                new_finished_subslots[index] = new_subslot
                new_block = block.replace(finished_sub_slots=new_finished_subslots)
                break
    if field_vdf == CompressibleVDFField.CC_SP_VDF:
        if block.reward_chain_block.challenge_chain_sp_vdf == vdf_info:
            assert block.challenge_chain_sp_proof is not None
            new_block = block.replace(challenge_chain_sp_proof=vdf_proof)
    if field_vdf == CompressibleVDFField.CC_IP_VDF:
        if block.reward_chain_block.challenge_chain_ip_vdf == vdf_info:
            new_block = block.replace(challenge_chain_ip_proof=vdf_proof)
    if new_block is None:
        return False
    async with self.db_wrapper.writer():
        try:
            await self.block_store.replace_proof(header_hash, new_block)
            return True
        except BaseException as e:
            self.log.error(
                f"_replace_proof error while adding block {block.header_hash} height {block.height},"
                f" rolling back: {e} {traceback.format_exc()}"
            )
            raise


async def add_compact_proof_of_time(self: FullNode, request: timelord_protocol.RespondCompactProofOfTime) -> None:
    peak = self.blockchain.get_peak()
    if peak is None or peak.height - request.height < 5:
        self.log.info(f"Ignoring add_compact_proof_of_time, height {request.height} too recent.")
        return None

    field_vdf = CompressibleVDFField(int(request.field_vdf))
    if not await self._can_accept_compact_proof(
        request.vdf_info, request.vdf_proof, request.height, request.header_hash, field_vdf
    ):
        return None
    async with self.blockchain.compact_proof_lock:
        replaced = await self._replace_proof(request.vdf_info, request.vdf_proof, request.header_hash, field_vdf)
    if not replaced:
        self.log.error(f"Could not replace compact proof: {request.height}")
        return None
    self.log.info(f"Replaced compact proof at height {request.height}")
    msg = make_msg(
        ProtocolMessageTypes.new_compact_vdf,
        full_node_protocol.NewCompactVDF(request.height, request.header_hash, request.field_vdf, request.vdf_info),
    )
    if self._server is not None:
        await self.server.send_to_all([msg], NodeType.FULL_NODE)


async def new_compact_vdf(
    self: FullNode, request: full_node_protocol.NewCompactVDF, peer: WSChiaConnection
) -> None:
    peak = self.blockchain.get_peak()
    if peak is None or peak.height - request.height < 5:
        self.log.info(f"Ignoring new_compact_vdf, height {request.height} too recent.")
        return None
    is_fully_compactified = await self.block_store.is_fully_compactified(request.header_hash)
    if is_fully_compactified is None or is_fully_compactified:
        return None
    header_block = await self.blockchain.get_header_block_by_height(
        request.height, request.header_hash, tx_filter=False
    )
    if header_block is None:
        return None
    field_vdf = CompressibleVDFField(int(request.field_vdf))
    if await self._needs_compact_proof(request.vdf_info, header_block, field_vdf):
        peer_request = full_node_protocol.RequestCompactVDF(
            request.height, request.header_hash, request.field_vdf, request.vdf_info
        )
        response = await peer.call_api(FullNodeAPI.request_compact_vdf, peer_request, timeout=10)
        if response is not None and isinstance(response, full_node_protocol.RespondCompactVDF):
            await self.add_compact_vdf(response, peer)


async def request_compact_vdf(
    self: FullNode, request: full_node_protocol.RequestCompactVDF, peer: WSChiaConnection
) -> None:
    header_block = await self.blockchain.get_header_block_by_height(
        request.height, request.header_hash, tx_filter=False
    )
    if header_block is None:
        return None
    vdf_proof: VDFProof | None = None
    field_vdf = CompressibleVDFField(int(request.field_vdf))
    if field_vdf == CompressibleVDFField.CC_EOS_VDF:
        for sub_slot in header_block.finished_sub_slots:
            if sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf == request.vdf_info:
                vdf_proof = sub_slot.proofs.challenge_chain_slot_proof
                break
    if field_vdf == CompressibleVDFField.ICC_EOS_VDF:
        for sub_slot in header_block.finished_sub_slots:
            if (
                sub_slot.infused_challenge_chain is not None
                and sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf == request.vdf_info
            ):
                vdf_proof = sub_slot.proofs.infused_challenge_chain_slot_proof
                break
    if (
        field_vdf == CompressibleVDFField.CC_SP_VDF
        and header_block.reward_chain_block.challenge_chain_sp_vdf == request.vdf_info
    ):
        vdf_proof = header_block.challenge_chain_sp_proof
    if (
        field_vdf == CompressibleVDFField.CC_IP_VDF
        and header_block.reward_chain_block.challenge_chain_ip_vdf == request.vdf_info
    ):
        vdf_proof = header_block.challenge_chain_ip_proof
    if vdf_proof is None or vdf_proof.witness_type > 0 or not vdf_proof.normalized_to_identity:
        self.log.error(f"{peer} requested compact vdf we don't have, height: {request.height}.")
        return None
    compact_vdf = full_node_protocol.RespondCompactVDF(
        request.height,
        request.header_hash,
        request.field_vdf,
        request.vdf_info,
        vdf_proof,
    )
    msg = make_msg(ProtocolMessageTypes.respond_compact_vdf, compact_vdf)
    await peer.send_message(msg)


async def add_compact_vdf(
    self: FullNode, request: full_node_protocol.RespondCompactVDF, peer: WSChiaConnection
) -> None:
    field_vdf = CompressibleVDFField(int(request.field_vdf))
    if not await self._can_accept_compact_proof(
        request.vdf_info, request.vdf_proof, request.height, request.header_hash, field_vdf
    ):
        return None
    async with self.blockchain.compact_proof_lock:
        if self.blockchain.seen_compact_proofs(request.vdf_info, request.height):
            return None
        replaced = await self._replace_proof(request.vdf_info, request.vdf_proof, request.header_hash, field_vdf)
    if not replaced:
        self.log.error(f"Could not replace compact proof: {request.height}")
        return None
    msg = make_msg(
        ProtocolMessageTypes.new_compact_vdf,
        full_node_protocol.NewCompactVDF(request.height, request.header_hash, request.field_vdf, request.vdf_info),
    )
    if self._server is not None:
        await self.server.send_to_all([msg], NodeType.FULL_NODE, peer.peer_node_id)


def in_bad_peak_cache(self: FullNode, wp: WeightProof) -> bool:
    for block in wp.recent_chain_data:
        if block.header_hash in self.bad_peak_cache.keys():
            return True
    return False


def add_to_bad_peak_cache(self: FullNode, peak_header_hash: bytes32, peak_height: uint32) -> None:
    curr_height = self.blockchain.get_peak_height()

    if curr_height is None:
        self.log.debug(f"add bad peak {peak_header_hash} to cache")
        self.bad_peak_cache[peak_header_hash] = peak_height
        return
    minimum_cache_height = curr_height - (2 * self.constants.SUB_EPOCH_BLOCKS)
    if peak_height < minimum_cache_height:
        return

    new_cache = {}
    self.log.info(f"add bad peak {peak_header_hash} to cache")
    new_cache[peak_header_hash] = peak_height
    min_height = peak_height
    min_block = peak_header_hash
    for header_hash, height in self.bad_peak_cache.items():
        if height < minimum_cache_height:
            self.log.debug(f"remove bad peak {peak_header_hash} from cache")
            continue
        if height < min_height:
            min_block = header_hash
        new_cache[header_hash] = height

    if len(new_cache) > self.config.get("bad_peak_cache_size", 100):
        del new_cache[min_block]

    self.bad_peak_cache = new_cache


async def broadcast_uncompact_blocks(
    self: FullNode, uncompact_interval_scan: int, target_uncompact_proofs: int, sanitize_weight_proof_only: bool
) -> None:
    try:
        while not self._shut_down:
            while self.sync_store.get_sync_mode() or self.sync_store.get_long_sync():
                if self._shut_down:
                    return None
                await asyncio.sleep(30)

            broadcast_list: list[timelord_protocol.RequestCompactProofOfTime] = []

            self.log.info("Getting random heights for bluebox to compact")

            if self._server is None:
                self.log.info("Not broadcasting uncompact blocks, no server found")
                await asyncio.sleep(uncompact_interval_scan)
                continue
            connected_timelords = self.server.get_connections(NodeType.TIMELORD)

            total_target_uncompact_proofs = target_uncompact_proofs * max(1, len(connected_timelords))
            heights = await self.block_store.get_random_not_compactified(total_target_uncompact_proofs)
            self.log.info("Heights found for bluebox to compact: [%s]", ", ".join(map(str, heights)))

            for h in heights:
                headers = await self.blockchain.get_header_blocks_in_range(h, h, tx_filter=False)
                records: dict[bytes32, BlockRecord] = {}
                if sanitize_weight_proof_only:
                    records = await self.blockchain.get_block_records_in_range(h, h)
                for header in headers.values():
                    expected_header_hash = self.blockchain.height_to_hash(header.height)
                    if header.header_hash != expected_header_hash:
                        continue
                    if sanitize_weight_proof_only:
                        assert header.header_hash in records
                        record = records[header.header_hash]
                    for sub_slot in header.finished_sub_slots:
                        if (
                            sub_slot.proofs.challenge_chain_slot_proof.witness_type > 0
                            or not sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity
                        ):
                            broadcast_list.append(
                                timelord_protocol.RequestCompactProofOfTime(
                                    sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf,
                                    header.header_hash,
                                    header.height,
                                    uint8(CompressibleVDFField.CC_EOS_VDF),
                                )
                            )
                        if sub_slot.proofs.infused_challenge_chain_slot_proof is not None and (
                            sub_slot.proofs.infused_challenge_chain_slot_proof.witness_type > 0
                            or not sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
                        ):
                            assert sub_slot.infused_challenge_chain is not None
                            broadcast_list.append(
                                timelord_protocol.RequestCompactProofOfTime(
                                    sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf,
                                    header.header_hash,
                                    header.height,
                                    uint8(CompressibleVDFField.ICC_EOS_VDF),
                                )
                            )
                    # Running in 'sanitize_weight_proof_only' ignores CC_SP_VDF and CC_IP_VDF
                    # unless this is a challenge block.
                    if sanitize_weight_proof_only:
                        if not record.is_challenge_block(self.constants):
                            continue
                    if header.challenge_chain_sp_proof is not None and (
                        header.challenge_chain_sp_proof.witness_type > 0
                        or not header.challenge_chain_sp_proof.normalized_to_identity
                    ):
                        assert header.reward_chain_block.challenge_chain_sp_vdf is not None
                        broadcast_list.append(
                            timelord_protocol.RequestCompactProofOfTime(
                                header.reward_chain_block.challenge_chain_sp_vdf,
                                header.header_hash,
                                header.height,
                                uint8(CompressibleVDFField.CC_SP_VDF),
                            )
                        )

                    if (
                        header.challenge_chain_ip_proof.witness_type > 0
                        or not header.challenge_chain_ip_proof.normalized_to_identity
                    ):
                        broadcast_list.append(
                            timelord_protocol.RequestCompactProofOfTime(
                                header.reward_chain_block.challenge_chain_ip_vdf,
                                header.header_hash,
                                header.height,
                                uint8(CompressibleVDFField.CC_IP_VDF),
                            )
                        )

                broadcast_list_chunks: list[list[timelord_protocol.RequestCompactProofOfTime]] = []
                for index in range(0, len(broadcast_list), target_uncompact_proofs):
                    broadcast_list_chunks.append(broadcast_list[index : index + target_uncompact_proofs])
                if len(broadcast_list_chunks) == 0:
                    self.log.info("Did not find any uncompact blocks.")
                    await asyncio.sleep(uncompact_interval_scan)
                    continue
                if self.sync_store.get_sync_mode() or self.sync_store.get_long_sync():
                    await asyncio.sleep(uncompact_interval_scan)
                    continue
                if self._server is not None:
                    self.log.info(f"Broadcasting {len(broadcast_list)} items to the bluebox")
                    connected_timelords = self.server.get_connections(NodeType.TIMELORD)
                    chunk_index = 0
                    for connection in connected_timelords:
                        peer_node_id = connection.peer_node_id
                        msgs = []
                        broadcast_list = broadcast_list_chunks[chunk_index]
                        chunk_index = (chunk_index + 1) % len(broadcast_list_chunks)
                        for new_pot in broadcast_list:
                            msg = make_msg(ProtocolMessageTypes.request_compact_proof_of_time, new_pot)
                            msgs.append(msg)
                        await self.server.send_to_specific(msgs, peer_node_id)
                await asyncio.sleep(uncompact_interval_scan)
    except Exception as e:
        error_stack = traceback.format_exc()
        self.log.error(f"Exception in broadcast_uncompact_blocks: {e}")
        self.log.error(f"Exception Stack: {error_stack}")
