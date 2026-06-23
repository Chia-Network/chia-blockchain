"""
Deferred persistence for compact VDF proofs.

Runtime (receiving compact VDFs)
--------------------------------
When a compact VDF is validated (via add_compact_vdf or add_compact_proof_of_time):

1. The proof is merged into the block in the block cache only (no DB write).
2. A record is appended to {db_folder}/compactvdf (with a network suffix on
   testnets, matching the height-to-hash file naming).

Each file record is length-prefixed and contains: header_hash, field_vdf,
vdf_proof.

Startup (near height-to-hash processing)
----------------------------------------
Right after BlockHeightMap.create() in full_node.manage():

1. Read all entries from compactvdf.
2. Sort by block hash and group consecutive entries per block.
3. For each entry: validate the VDF and apply it to the in-memory block.
4. After all entries for a block are processed, flush that block to the DB
   once via replace_proof.
5. Delete the compactvdf file when done.

Within a single node run, callers that read blocks via the block cache (e.g.
get_all_full_blocks) see compactified proofs immediately. DB persistence
happens on the next node restart when the flat file is processed.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

import aiofiles
from chia_rs import ConsensusConstants, FullBlock, HeaderBlock, VDFInfo, VDFProof
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8

from chia.full_node.block_store import BlockStore
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.vdf import CompressibleVDFField, validate_vdf
from chia.util.streamable import streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class CompactVdfEntry:
    header_hash: bytes32
    field_vdf: uint8
    vdf_proof: VDFProof


def compact_vdf_filename(blockchain_dir: Path, selected_network: str | None = None) -> Path:
    suffix = "" if (selected_network is None or selected_network == "mainnet") else f"-{selected_network}"
    return blockchain_dir / f"compactvdf{suffix}"


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
    return new_block


def _parse_entries(data: bytes) -> list[CompactVdfEntry]:
    entries: list[CompactVdfEntry] = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError("truncated compactvdf file")
        size = int.from_bytes(data[offset : offset + 4], byteorder="big")
        offset += 4
        if offset + size > len(data):
            raise ValueError("truncated compactvdf entry in compactvdf file")
        entries.append(CompactVdfEntry.from_bytes(data[offset : offset + size]))
        offset += size
    return entries


async def read_all_entries(path: Path) -> list[CompactVdfEntry]:
    try:
        async with aiofiles.open(path, "rb") as f:
            data = await f.read()
    except FileNotFoundError:
        return []
    if len(data) == 0:
        return []
    return _parse_entries(data)


async def append_entry(path: Path, entry: CompactVdfEntry, lock: asyncio.Lock) -> None:
    entry_bytes = bytes(entry)
    record = len(entry_bytes).to_bytes(4, byteorder="big") + entry_bytes
    async with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "ab") as f:
            await f.write(record)


async def process_compact_vdf_file(
    path: Path,
    block_store: BlockStore,
    constants: ConsensusConstants,
) -> None:
    entries = await read_all_entries(path)
    if len(entries) == 0:
        if path.exists():
            path.unlink()
        return

    log.info(f"Processing {len(entries)} pending compact VDF entries from {path}")
    entries.sort(key=lambda entry: entry.header_hash)

    for header_hash, group_iter in groupby(entries, key=lambda entry: entry.header_hash):
        block = await block_store.get_full_block(header_hash)
        if block is None:
            log.error(f"Can't find block for pending compact VDF. Header hash: {header_hash}")
            continue

        for entry in group_iter:
            field_vdf = CompressibleVDFField(int(entry.field_vdf))
            if not entry.vdf_proof.normalized_to_identity or entry.vdf_proof.witness_type > 0:
                log.error(f"Pending compact VDF proof is not compact: {entry.vdf_proof}")
                continue
            vdf_info = find_vdf_info_for_proof(block, field_vdf, entry.vdf_proof, constants)
            if vdf_info is None:
                log.error(f"Pending compact VDF proof is not valid for block {header_hash}")
                continue
            if not needs_compact_proof(vdf_info, block, field_vdf):
                log.info(f"Duplicate pending compact proof for block {header_hash}")
                continue
            new_block = apply_compact_proof_to_block(block, vdf_info, entry.vdf_proof, field_vdf)
            if new_block is None:
                log.error(f"Could not apply pending compact proof for block {header_hash}")
                continue
            block = new_block

        async with block_store.db_wrapper.writer():
            await block_store.replace_proof(header_hash, block)

    path.unlink()
    log.info(f"Finished processing pending compact VDF entries, removed {path}")
