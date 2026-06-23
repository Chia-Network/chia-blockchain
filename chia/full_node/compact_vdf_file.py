"""
Deferred persistence for compact VDF proofs.

Database writes
---------------
Compact VDF handling does write to the DB, but only on startup — not when
proofs are received.

While the node is running (add_compact_vdf / add_compact_proof_of_time):
- Updates the block cache only (put_block_in_cache).
- Appends a line to compactvdf.
- Does not call replace_proof or touch SQLite.

On the next startup (process_compact_vdf_file):
- Reads compactvdf, validates and applies each proof.
- Flushes each block to the DB via block_store.replace_proof() (updates
  full_blocks.block and is_fully_compactified).
- Deletes compactvdf when done.

During a single run, callers that read blocks via the block cache (e.g.
get_all_full_blocks) see compactified proofs immediately. The DB still holds
the old proofs until restart processes the file.

Runtime (receiving compact VDFs)
--------------------------------
When a compact VDF is validated (via add_compact_vdf or add_compact_proof_of_time):

1. The proof is merged into the block in the block cache only (no DB write).
2. A record is appended to {db_folder}/compactvdf (with a network suffix on
   testnets, matching the height-to-hash file naming).

Each line is a JSON object with: header_hash, field_vdf, witness (compact proofs
always use witness_type 0 and normalized_to_identity true). vdf_info is not
stored; it is recovered from the block at import time.

Multiple VDFs per block
-----------------------
A block can have several CC_EOS_VDF or ICC_EOS_VDF entries (one per finished
sub-slot, and ICC only where infused_challenge_chain is present). CC_SP_VDF and
CC_IP_VDF are at most one per block.

The file does not use a sub-slot index or other explicit slot ID. Entries with
the same header_hash and field_vdf are distinguished by witness: each sub-slot
has a different proof, so each line has different witness bytes.

On import, find_vdf_info_for_proof loads all vdf_info candidates for that
field_vdf from the block, reconstructs VDFProof(uint8(0), witness, True), and
validates the witness against each candidate until one matches. That matched
vdf_info selects which sub-slot (or reward-chain field) apply_compact_proof_to_block
updates. Slot selection is implicit: the witness is cryptographically bound to
one sub-slot's vdf_info (challenge, iterations, output).

Startup (near height-to-hash processing)
----------------------------------------
Right after BlockHeightMap.create() in full_node.manage():

1. Read all entries from compactvdf.
2. Sort by block hash and group consecutive entries per block.
3. For each entry: validate the VDF and apply it to the in-memory block.
4. After all entries for a block are processed, flush that block to the DB
   once via replace_proof.
5. Delete the compactvdf file when done.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
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
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class CompactVdfEntry(Streamable):
    header_hash: bytes32
    field_vdf: uint8
    witness: bytes


def compact_vdf_proof(witness: bytes) -> VDFProof:
    return VDFProof(uint8(0), witness, True)


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


async def read_all_entries(path: Path) -> list[CompactVdfEntry]:
    try:
        async with aiofiles.open(path, encoding="utf-8") as f:
            text = await f.read()
    except FileNotFoundError:
        return []
    if len(text) == 0:
        return []
    return _parse_entries(text)


async def append_entry(path: Path, entry: CompactVdfEntry, lock: asyncio.Lock) -> None:
    line = json.dumps(entry.to_json_dict(), sort_keys=True) + "\n"
    async with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "a", encoding="utf-8") as f:
            await f.write(line)


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

    entries.sort(key=lambda entry: entry.header_hash)
    blocks_total = len({entry.header_hash for entry in entries})
    start_time = time.monotonic()
    log.info(
        f"Starting compact VDF file processing: {len(entries)} entries "
        f"across {blocks_total} blocks from {path}"
    )
    blocks_processed = 0
    entries_applied = 0

    for header_hash, group_iter in groupby(entries, key=lambda entry: entry.header_hash):
        block_entries = list(group_iter)
        block = await block_store.get_full_block(header_hash)
        if block is None:
            log.error(f"Can't find block for pending compact VDF. Header hash: {header_hash}")
            continue

        applied_for_block = 0
        for entry in block_entries:
            field_vdf = CompressibleVDFField(int(entry.field_vdf))
            vdf_proof = compact_vdf_proof(entry.witness)
            vdf_info = find_vdf_info_for_proof(block, field_vdf, vdf_proof, constants)
            if vdf_info is None:
                log.error(f"Pending compact VDF proof is not valid for block {header_hash}")
                continue
            if not needs_compact_proof(vdf_info, block, field_vdf):
                log.info(f"Duplicate pending compact proof for block {header_hash}")
                continue
            new_block = apply_compact_proof_to_block(block, vdf_info, vdf_proof, field_vdf)
            if new_block is None:
                log.error(f"Could not apply pending compact proof for block {header_hash}")
                continue
            block = new_block
            applied_for_block += 1
            entries_applied += 1

        blocks_processed += 1
        log.debug(
            f"Compact VDF progress: block {blocks_processed}/{blocks_total} "
            f"height {block.height} header_hash {header_hash} "
            f"applied {applied_for_block}/{len(block_entries)} proofs, flushing to DB"
        )
        async with block_store.db_wrapper.writer():
            await block_store.replace_proof(header_hash, block)

    path.unlink()
    elapsed = time.monotonic() - start_time
    log.info(
        f"Finished processing compact VDF file: {entries_applied} proofs applied "
        f"across {blocks_processed} blocks, time taken: {elapsed:.2f}s, removed {path}"
    )
