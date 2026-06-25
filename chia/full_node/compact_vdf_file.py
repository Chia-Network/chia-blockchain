"""
Compact VDF proof helpers.

Used when applying compact VDF proofs from remote compactvdf files during block
validation, and when replacing proofs on stored blocks (e.g. from the timelord).

Each compact proof record contains: header_hash, field_vdf, witness (witness_type 0
and normalized_to_identity true). vdf_info is recovered from the block at apply time
via find_vdf_info_for_proof().
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from chia_rs import ConsensusConstants, FullBlock, HeaderBlock, VDFInfo, VDFProof
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8

from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.vdf import CompressibleVDFField, validate_vdf
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)

COMPACT_VDF_HEIGHT_CHUNK_SIZE = 10000


@streamable
@dataclass(frozen=True)
class CompactVdfEntry(Streamable):
    header_hash: bytes32
    field_vdf: uint8
    witness: bytes


def compact_vdf_proof(witness: bytes) -> VDFProof:
    return VDFProof(uint8(0), witness, True)


def _vdf_info_candidates(block: FullBlock | HeaderBlock, field_vdf: CompressibleVDFField) -> list[VDFInfo]:
    if field_vdf == CompressibleVDFField.CC_EOS_VDF:
        return [sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf for sub_slot in block.finished_sub_slots]
    if field_vdf == CompressibleVDFField.ICC_EOS_VDF:
        return [
            sub_slot.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf
            for sub_slot in block.finished_sub_slots
            if sub_slot.infused_challenge_chain is not None
        ]
    if field_vdf == CompressibleVDFField.CC_SP_VDF:
        if block.reward_chain_block.challenge_chain_sp_vdf is None:
            return []
        return [block.reward_chain_block.challenge_chain_sp_vdf]
    if field_vdf == CompressibleVDFField.CC_IP_VDF:
        return [block.reward_chain_block.challenge_chain_ip_vdf]
    return []


def find_vdf_info_for_proof(
    block: FullBlock | HeaderBlock,
    field_vdf: CompressibleVDFField,
    vdf_proof: VDFProof,
    constants: ConsensusConstants,
) -> VDFInfo | None:
    for vdf_info in _vdf_info_candidates(block, field_vdf):
        if validate_vdf(vdf_proof, constants, ClassgroupElement.get_default_element(), vdf_info):
            return vdf_info
    return None


def needs_compact_proof(vdf_info: VDFInfo, header_block: HeaderBlock, field_vdf: CompressibleVDFField) -> bool:
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


def apply_compact_proof_to_block(
    block: FullBlock,
    vdf_info: VDFInfo,
    vdf_proof: VDFProof,
    field_vdf: CompressibleVDFField,
) -> FullBlock | None:
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
    if new_block is not None:
        log.info(
            "Replaced uncompacted VDF with compact proof for block %s height %s field_vdf %s",
            block.header_hash,
            block.height,
            field_vdf.name,
        )
    return new_block


def _entry_from_json_dict(data: dict[str, object]) -> CompactVdfEntry:
    if "witness" in data:
        return CompactVdfEntry.from_json_dict(data)
    vdf_proof = data.get("vdf_proof")
    if isinstance(vdf_proof, dict) and "witness" in vdf_proof:
        return CompactVdfEntry.from_json_dict(
            {
                "header_hash": data["header_hash"],
                "field_vdf": data["field_vdf"],
                "witness": vdf_proof["witness"],
            }
        )
    raise ValueError("missing witness")


def _parse_entries(text: str) -> list[CompactVdfEntry]:
    entries: list[CompactVdfEntry] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if len(stripped) == 0:
            continue
        try:
            entries.append(_entry_from_json_dict(json.loads(stripped)))
        except Exception as e:
            log.warning(f"Skipping invalid compactvdf line {line_no}: {e}")
    return entries


def parse_compact_vdf_entries(text: str) -> list[CompactVdfEntry]:
    return _parse_entries(text)
