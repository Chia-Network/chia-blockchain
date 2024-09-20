from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from typing import Dict, List, Optional, Set, Tuple

from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockRecordsProtocol
from chia.consensus.constants import ConsensusConstants
from chia.consensus.difficulty_adjustment import can_finish_sub_and_full_epoch
from chia.consensus.make_sub_epoch_summary import make_sub_epoch_summary
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.consensus.pot_iterations import calculate_sp_interval_iters
from chia.full_node.signage_point import SignagePoint
from chia.protocols import timelord_protocol
from chia.server.outbound_message import Message
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.vdf import VDFInfo, validate_vdf
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.lru_cache import LRUCache
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclasses.dataclass(frozen=True)
class FullNodeStorePeakResult(Streamable):
    added_eos: Optional[EndOfSubSlotBundle]
    new_signage_points: List[Tuple[uint8, SignagePoint]]
    new_infusion_points: List[timelord_protocol.NewInfusionPointVDF]


@dataclasses.dataclass
class UnfinishedBlockEntry:
    # if this is None, it means we've requested this block but not yet received
    # it
    unfinished_block: Optional[UnfinishedBlock]
    # If this is None, it means we've initiated validation of this block, but it
    # hasn't completed yet
    result: Optional[PreValidationResult]
    height: uint32


def find_best_block(
    result: Dict[Optional[bytes32], UnfinishedBlockEntry]
) -> Tuple[Optional[bytes32], Optional[UnfinishedBlock]]:
    """
    Given a collection of UnfinishedBlocks (all with the same reward block
    hash), return the "best" one. i.e. the one with the smallest foliage hash.
    """
    if len(result) == 0:
        return None, None

    all_blocks = list(result.items())
    if len(all_blocks) == 1:
        foliage_hash, entry = all_blocks[0]
        # this means we don't have the block yet
        if entry.unfinished_block is None:
            return None, None
        else:
            return foliage_hash, entry.unfinished_block

    def include_block(item: Tuple[Optional[bytes32], UnfinishedBlockEntry]) -> bool:
        foliage_hash, entry = item
        return foliage_hash is not None and entry.unfinished_block is not None

    # if there are unfinished blocks with foliage (i.e. not None) we prefer
    # those, so drop the first element
    all_blocks = [e for e in all_blocks if include_block(e)]
    all_blocks = sorted(all_blocks)

    # we may have filtered out some blocks that we have only requested, but not
    # yet received.
    if len(all_blocks) == 0:
        return None, None

    return all_blocks[0][0], all_blocks[0][1].unfinished_block


class FullNodeStore:
    constants: ConsensusConstants

    # Blocks which we have created, but don't have plot signatures yet, so not yet "unfinished blocks"
    candidate_blocks: Dict[bytes32, Tuple[uint32, UnfinishedBlock]]
    candidate_backup_blocks: Dict[bytes32, Tuple[uint32, UnfinishedBlock]]

    # Block hashes of unfinished blocks that we have seen recently. This is
    # effectively a Set[bytes32] but in order to evict the oldest items first,
    # we use a Dict that preserves insertion order, and remove from the
    # beginning
    seen_unfinished_blocks: Dict[bytes32, None]

    # Unfinished blocks, keyed from reward hash
    # There may be multiple different unfinished blocks with the same partial
    # hash (reward chain block hash). They are stored under their partial hash
    # though. The inner dictionary uses the foliage hash as the key
    # The UnfinishedBlockEntry is a placeholder for UnfinishedBlocks we have
    # requested (but don't have yet) or that we have but haven't completed
    # validation of (yet).
    # The inner key (the foliage hash) is Optional, where None either means
    # it's not a transaction block, or it's a block we learned about via the old
    # protocol, where all we get is the reward block hash.
    _unfinished_blocks: Dict[bytes32, Dict[Optional[bytes32], UnfinishedBlockEntry]]

    # Finished slots and sps from the peak's slot onwards
    # We store all 32 SPs for each slot, starting as 32 Nones and filling them as we go
    # Also stores the total iters at the end of slot
    # For the first sub-slot, EndOfSlotBundle is None
    finished_sub_slots: List[Tuple[Optional[EndOfSubSlotBundle], List[Optional[SignagePoint]], uint128]]

    # These caches maintain objects which depend on infused blocks in the reward chain, that we
    # might receive before the blocks themselves. The dict keys are the reward chain challenge hashes.

    # End of slots which depend on infusions that we don't have
    future_eos_cache: Dict[bytes32, List[EndOfSubSlotBundle]]

    # Signage points which depend on infusions that we don't have
    future_sp_cache: Dict[bytes32, List[Tuple[uint8, SignagePoint]]]

    # Infusion point VDFs which depend on infusions that we don't have
    future_ip_cache: Dict[bytes32, List[timelord_protocol.NewInfusionPointVDF]]

    # This stores the time that each key was added to the future cache, so we can clear old keys
    future_cache_key_times: Dict[bytes32, int]

    # These recent caches are for pooling support
    recent_signage_points: LRUCache[bytes32, Tuple[SignagePoint, float]]
    recent_eos: LRUCache[bytes32, Tuple[EndOfSubSlotBundle, float]]

    pending_tx_request: Dict[bytes32, bytes32]  # tx_id: peer_id
    peers_with_tx: Dict[bytes32, Set[bytes32]]  # tx_id: Set[peer_ids}
    tx_fetch_tasks: Dict[bytes32, asyncio.Task[None]]  # Task id: task
    serialized_wp_message: Optional[Message]
    serialized_wp_message_tip: Optional[bytes32]

    max_seen_unfinished_blocks: int

    def __init__(self, constants: ConsensusConstants):
        self.candidate_blocks = {}
        self.candidate_backup_blocks = {}
        self.seen_unfinished_blocks = {}
        self._unfinished_blocks = {}
        self.finished_sub_slots = []
        self.future_eos_cache = {}
        self.future_sp_cache = {}
        self.future_ip_cache = {}
        self.recent_signage_points = LRUCache(500)
        self.recent_eos = LRUCache(50)
        self.future_cache_key_times = {}
        self.constants = constants
        self.clear_slots()
        self.initialize_genesis_sub_slot()
        self.pending_tx_request = {}
        self.peers_with_tx = {}
        self.tx_fetch_tasks = {}
        self.serialized_wp_message = None
        self.serialized_wp_message_tip = None
        self.max_seen_unfinished_blocks = 1000

    def is_requesting_unfinished_block(
        self, reward_block_hash: bytes32, foliage_hash: Optional[bytes32]
    ) -> Tuple[bool, int]:
        """
        Asks if we are already requesting this specific unfinished block (given
        the reward block hash and foliage hash). The returned bool is true if we
        are and false otherwise. The function also returns the number of
        variants of an unfinished block with this reward block hash we are
        currently requesting. This is useful to ensure we limit the number of
        variants we request.
        """
        ents = self._unfinished_blocks.get(reward_block_hash)
        if ents is None:
            return (False, 0)
        elif foliage_hash is None:
            return (len(ents) > 0, len(ents))
        else:
            return (foliage_hash in ents, len(ents))

    def mark_requesting_unfinished_block(self, reward_block_hash: bytes32, foliage_hash: Optional[bytes32]) -> None:
        ents = self._unfinished_blocks.setdefault(reward_block_hash, {})
        ents.setdefault(foliage_hash, UnfinishedBlockEntry(None, None, uint32(0)))

    def remove_requesting_unfinished_block(self, reward_block_hash: bytes32, foliage_hash: Optional[bytes32]) -> None:
        reward_ents = self._unfinished_blocks.get(reward_block_hash)
        if reward_ents is None:
            return
        foliage_ent = reward_ents.get(foliage_hash)
        if foliage_ent is None:
            return
        if foliage_ent.unfinished_block is not None:
            # in this case we've successfully received the unfinished block,
            # it's already considered "not requesting", but actually downloaded
            return
        del reward_ents[foliage_hash]
        if len(reward_ents) == 0:
            del self._unfinished_blocks[reward_block_hash]

    def add_candidate_block(
        self, quality_string: bytes32, height: uint32, unfinished_block: UnfinishedBlock, backup: bool = False
    ) -> None:
        if backup:
            self.candidate_backup_blocks[quality_string] = (height, unfinished_block)
        else:
            self.candidate_blocks[quality_string] = (height, unfinished_block)

    def get_candidate_block(
        self, quality_string: bytes32, backup: bool = False
    ) -> Optional[Tuple[uint32, UnfinishedBlock]]:
        if backup:
            return self.candidate_backup_blocks.get(quality_string, None)
        else:
            return self.candidate_blocks.get(quality_string, None)

    def clear_candidate_blocks_below(self, height: uint32) -> None:
        del_keys = []
        for key, value in self.candidate_blocks.items():
            if value[0] < height:
                del_keys.append(key)
        for key in del_keys:
            try:
                del self.candidate_blocks[key]
            except KeyError:
                pass
        del_keys = []
        for key, value in self.candidate_backup_blocks.items():
            if value[0] < height:
                del_keys.append(key)
        for key in del_keys:
            try:
                del self.candidate_backup_blocks[key]
            except KeyError:
                pass

    def seen_unfinished_block(self, object_hash: bytes32) -> bool:
        if object_hash in self.seen_unfinished_blocks:
            return True
        self.seen_unfinished_blocks[object_hash] = None
        if len(self.seen_unfinished_blocks) > self.max_seen_unfinished_blocks:
            # remove the least recently added hash
            to_remove = next(iter(self.seen_unfinished_blocks))
            del self.seen_unfinished_blocks[to_remove]
        return False

    def add_unfinished_block(
        self, height: uint32, unfinished_block: UnfinishedBlock, result: PreValidationResult
    ) -> None:
        partial_hash = unfinished_block.partial_hash
        entry = self._unfinished_blocks.setdefault(partial_hash, {})
        entry[unfinished_block.foliage.foliage_transaction_block_hash] = UnfinishedBlockEntry(
            unfinished_block, result, height
        )

    def get_unfinished_block(self, unfinished_reward_hash: bytes32) -> Optional[UnfinishedBlock]:
        result = self._unfinished_blocks.get(unfinished_reward_hash, None)
        if result is None:
            return None
        # The old API doesn't distinguish between duplicate UnfinishedBlocks,
        # return the *best* UnfinishedBlock. This is the path taken when the
        # timelord sends us an infusion point with this specific reward block
        # hash. We pick one of the unfinished blocks based on an arbitrary but
        # deterministic property.
        # this sorts the UnfinishedBlocks by the foliage hash, and picks the
        # smallest hash
        foliage_hash, block = find_best_block(result)
        return block

    def get_unfinished_block2(
        self, unfinished_reward_hash: bytes32, unfinished_foliage_hash: Optional[bytes32]
    ) -> Tuple[Optional[UnfinishedBlock], int, bool]:
        """
        Looks up an UnfinishedBlock by its reward block hash and foliage hash.
        If the foliage hash is None (e.g. it's not a transaction block), we fall
        back to the original function that looks up unfinished blocks just by
        their reward block hash.
        Returns:
            1. the (optional) UnfinishedBlock
            2. the number of other candidate blocks we know of with the same
               reward block hash
            3. whether we already have a "better" UnfinishedBlock candidate than
               this
        """
        result = self._unfinished_blocks.get(unfinished_reward_hash, None)
        if result is None:
            return None, 0, False
        if unfinished_foliage_hash is None:
            foliage_hash, block = find_best_block(result)
            return block, len(result), False

        foliage_hash, block = find_best_block(result)
        has_better: bool = foliage_hash is not None and foliage_hash < unfinished_foliage_hash

        entry = result.get(unfinished_foliage_hash)

        if entry is None:
            return None, len(result), has_better
        else:
            return entry.unfinished_block, len(result), has_better

    # we only have PreValidationResults for transaction blocks, and they all
    # have a foliage hash. That's why unfinished_foliage_hash is not Optional.
    def get_unfinished_block_result(
        self, unfinished_reward_hash: bytes32, unfinished_foliage_hash: bytes32
    ) -> Optional[UnfinishedBlockEntry]:
        result = self._unfinished_blocks.get(unfinished_reward_hash, None)
        if result is None:
            return None
        else:
            return result.get(unfinished_foliage_hash)

    # returns all unfinished blocks for the specified height
    def get_unfinished_blocks(self, height: uint32) -> List[UnfinishedBlock]:
        ret: List[UnfinishedBlock] = []
        for entry in self._unfinished_blocks.values():
            for ube in entry.values():
                if ube.height == height and ube.unfinished_block is not None:
                    ret.append(ube.unfinished_block)
        return ret

    def clear_unfinished_blocks_below(self, height: uint32) -> None:
        del_partial: List[bytes32] = []
        for partial_hash, entry in self._unfinished_blocks.items():
            del_foliage: List[Optional[bytes32]] = []
            for foliage_hash, ube in entry.items():
                if ube.height < height:
                    del_foliage.append(foliage_hash)
            for fh in del_foliage:
                del entry[fh]
            if len(entry) == 0:
                del_partial.append(partial_hash)
        for ph in del_partial:
            del self._unfinished_blocks[ph]

    # TODO: this should be removed. It's only used by a test
    def remove_unfinished_block(self, partial_reward_hash: bytes32) -> None:
        if partial_reward_hash in self._unfinished_blocks:
            del self._unfinished_blocks[partial_reward_hash]

    def add_to_future_ip(self, infusion_point: timelord_protocol.NewInfusionPointVDF) -> None:
        ch: bytes32 = infusion_point.reward_chain_ip_vdf.challenge
        if ch not in self.future_ip_cache:
            self.future_ip_cache[ch] = []
        self.future_ip_cache[ch].append(infusion_point)

    def in_future_sp_cache(self, signage_point: SignagePoint, index: uint8) -> bool:
        if signage_point.rc_vdf is None:
            return False

        if signage_point.rc_vdf.challenge not in self.future_sp_cache:
            return False
        for cache_index, cache_sp in self.future_sp_cache[signage_point.rc_vdf.challenge]:
            if cache_index == index and cache_sp.rc_vdf == signage_point.rc_vdf:
                return True
        return False

    def add_to_future_sp(self, signage_point: SignagePoint, index: uint8) -> None:
        # We are missing a block here
        if (
            signage_point.cc_vdf is None
            or signage_point.rc_vdf is None
            or signage_point.cc_proof is None
            or signage_point.rc_proof is None
        ):
            return None
        if signage_point.rc_vdf.challenge not in self.future_sp_cache:
            self.future_sp_cache[signage_point.rc_vdf.challenge] = []
        if self.in_future_sp_cache(signage_point, index):
            return None

        self.future_cache_key_times[signage_point.rc_vdf.challenge] = int(time.time())
        self.future_sp_cache[signage_point.rc_vdf.challenge].append((index, signage_point))
        log.info(f"Don't have rc hash {signage_point.rc_vdf.challenge.hex()}. caching signage point {index}.")

    def get_future_ip(self, rc_challenge_hash: bytes32) -> List[timelord_protocol.NewInfusionPointVDF]:
        return self.future_ip_cache.get(rc_challenge_hash, [])

    def clear_old_cache_entries(self) -> None:
        current_time: int = int(time.time())
        remove_keys: List[bytes32] = []
        for rc_hash, time_added in self.future_cache_key_times.items():
            if current_time - time_added > 3600:
                remove_keys.append(rc_hash)
        for k in remove_keys:
            self.future_cache_key_times.pop(k, None)
            self.future_ip_cache.pop(k, [])
            self.future_eos_cache.pop(k, [])
            self.future_sp_cache.pop(k, [])

    def clear_slots(self) -> None:
        self.finished_sub_slots.clear()

    def get_sub_slot(self, challenge_hash: bytes32) -> Optional[Tuple[EndOfSubSlotBundle, int, uint128]]:
        assert len(self.finished_sub_slots) >= 1
        for index, (sub_slot, _, total_iters) in enumerate(self.finished_sub_slots):
            if sub_slot is not None and sub_slot.challenge_chain.get_hash() == challenge_hash:
                return sub_slot, index, total_iters
        return None

    def initialize_genesis_sub_slot(self) -> None:
        self.clear_slots()
        self.finished_sub_slots = [(None, [None] * self.constants.NUM_SPS_SUB_SLOT, uint128(0))]

    def new_finished_sub_slot(
        self,
        eos: EndOfSubSlotBundle,
        blocks: BlockRecordsProtocol,
        peak: Optional[BlockRecord],
        next_sub_slot_iters: uint64,
        next_difficulty: uint64,
        peak_full_block: Optional[FullBlock],
    ) -> Optional[List[timelord_protocol.NewInfusionPointVDF]]:
        """
        Returns false if not added. Returns a list if added. The list contains all infusion points that depended
        on this sub slot
        """
        assert len(self.finished_sub_slots) >= 1
        assert (peak is None) == (peak_full_block is None)

        last_slot, _, last_slot_iters = self.finished_sub_slots[-1]

        cc_challenge: bytes32 = (
            last_slot.challenge_chain.get_hash() if last_slot is not None else self.constants.GENESIS_CHALLENGE
        )
        rc_challenge: bytes32 = (
            last_slot.reward_chain.get_hash() if last_slot is not None else self.constants.GENESIS_CHALLENGE
        )
        icc_challenge: Optional[bytes32] = None
        icc_iters: Optional[uint64] = None

        # Skip if already present
        for slot, _, _ in self.finished_sub_slots:
            if slot == eos:
                return []

        if eos.challenge_chain.challenge_chain_end_of_slot_vdf.challenge != cc_challenge:
            # This slot does not append to our next slot
            # This prevent other peers from appending fake VDFs to our cache
            log.error(
                f"bad cc_challenge in new_finished_sub_slot, "
                f"got {eos.challenge_chain.challenge_chain_end_of_slot_vdf.challenge.hex()}"
                f"expected {cc_challenge}"
            )
            return None

        if peak is None:
            sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING
        else:
            sub_slot_iters = peak.sub_slot_iters

        total_iters = uint128(last_slot_iters + sub_slot_iters)

        if peak is not None and peak.total_iters > last_slot_iters:
            # Peak is in this slot

            # Note: Adding an end of subslot does not lock the blockchain, for performance reasons. Only the
            # timelord_lock is used. Therefore, it's possible that we add a new peak at the same time as seeing
            # the finished subslot, and the peak is not fully added yet, so it looks like we still need the subslot.
            # In that case, we will exit here and let the new_peak code add the subslot.
            if total_iters < peak.total_iters:
                log.debug("dont add slot, total_iters < peak.total_iters")
                return None

            rc_challenge = bytes32(eos.reward_chain.end_of_slot_vdf.challenge)
            cc_start_element = peak.challenge_vdf_output
            iters = uint64(total_iters - peak.total_iters)
            if peak.reward_infusion_new_challenge != rc_challenge:
                # We don't have this challenge hash yet
                if rc_challenge not in self.future_eos_cache:
                    self.future_eos_cache[rc_challenge] = []
                self.future_eos_cache[rc_challenge].append(eos)
                self.future_cache_key_times[rc_challenge] = int(time.time())
                log.info(f"Don't have challenge hash {rc_challenge}, caching EOS")
                return None

            if peak.deficit == 0:
                if eos.reward_chain.deficit != self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                    log.error(
                        f"eos reward_chain deficit got {eos.reward_chain.deficit} "
                        f"expected {self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK}"
                    )
                    return None
            elif eos.reward_chain.deficit != peak.deficit:
                log.error(f"wrong eos reward_chain deficit got {eos.reward_chain.deficit} expected {peak.deficit}")
                return None

            if peak.deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                icc_start_element = None
            elif peak.deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1:
                icc_start_element = ClassgroupElement.get_default_element()
            else:
                icc_start_element = peak.infused_challenge_vdf_output

            if peak.deficit < self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                curr = peak
                while not curr.first_in_sub_slot and not curr.is_challenge_block(self.constants):
                    curr = blocks.block_record(curr.prev_hash)
                if curr.is_challenge_block(self.constants):
                    icc_challenge = curr.challenge_block_info_hash
                    icc_iters = uint64(total_iters - curr.total_iters)
                else:
                    assert curr.finished_infused_challenge_slot_hashes is not None
                    icc_challenge = curr.finished_infused_challenge_slot_hashes[-1]
                    icc_iters = sub_slot_iters
                assert icc_challenge is not None

            finish_se, finish_epoch = can_finish_sub_and_full_epoch(
                self.constants,
                blocks,
                peak.height,
                peak.prev_hash,
                peak.deficit,
                peak.sub_epoch_summary_included is not None,
            )
            if finish_se:
                # this is the first slot in a new sub epoch, should include SES
                expected_sub_epoch_summary = make_sub_epoch_summary(
                    self.constants,
                    blocks,
                    peak.height,
                    blocks.block_record(blocks.block_record(peak.prev_hash).prev_hash),
                    next_difficulty if finish_epoch else None,
                    next_sub_slot_iters if finish_epoch else None,
                )

                if eos.challenge_chain.subepoch_summary_hash is None:
                    log.warning("SES should not be None")
                    return None

                if eos.challenge_chain.subepoch_summary_hash != expected_sub_epoch_summary.get_hash():
                    log.warning(
                        f"Bad SES, expected {expected_sub_epoch_summary} "
                        f"expected hash {expected_sub_epoch_summary.get_hash()}, got {eos.challenge_chain}"
                    )
                    return None

                if finish_epoch:
                    # this is the first slot in a new epoch check diff and iterations
                    if (
                        eos.challenge_chain.new_sub_slot_iters is None
                        or eos.challenge_chain.new_sub_slot_iters != next_sub_slot_iters
                    ):
                        log.error("wrong new iterations at end of slot bundle")
                        return None

                    if (
                        eos.challenge_chain.new_difficulty is None
                        or eos.challenge_chain.new_difficulty != next_difficulty
                    ):
                        log.info("wrong new difficulty at end of slot bundle")
                        return None

                else:
                    if eos.challenge_chain.new_sub_slot_iters is not None:
                        log.error("got new iterations at end of slot bundle when it should be None")
                        return None

                    if eos.challenge_chain.new_difficulty is not None:
                        log.info("got new difficulty at end of slot bundle when it should be None")
                        return None

        else:
            # empty slots dont have sub_epoch_summary
            if eos.challenge_chain.subepoch_summary_hash is not None:
                log.warning("SES not correct, should be None in an empty slot")
                return None

            # This is on an empty slot
            cc_start_element = ClassgroupElement.get_default_element()
            icc_start_element = ClassgroupElement.get_default_element()
            iters = sub_slot_iters
            icc_iters = sub_slot_iters

            # The icc should only be present if the previous slot had an icc too, and not deficit 0 (just finished slot)
            icc_challenge = (
                last_slot.infused_challenge_chain.get_hash()
                if last_slot is not None
                and last_slot.infused_challenge_chain is not None
                and last_slot.reward_chain.deficit != self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK
                else None
            )

        # Validate cc VDF
        partial_cc_vdf_info = VDFInfo(
            cc_challenge,
            iters,
            eos.challenge_chain.challenge_chain_end_of_slot_vdf.output,
        )
        # The EOS will have the whole sub-slot iters, but the proof is only the delta, from the last peak
        if eos.challenge_chain.challenge_chain_end_of_slot_vdf != partial_cc_vdf_info.replace(
            number_of_iterations=sub_slot_iters
        ):
            return None
        if not eos.proofs.challenge_chain_slot_proof.normalized_to_identity and not validate_vdf(
            eos.proofs.challenge_chain_slot_proof,
            self.constants,
            cc_start_element,
            partial_cc_vdf_info,
        ):
            return None
        if eos.proofs.challenge_chain_slot_proof.normalized_to_identity and not validate_vdf(
            eos.proofs.challenge_chain_slot_proof,
            self.constants,
            ClassgroupElement.get_default_element(),
            eos.challenge_chain.challenge_chain_end_of_slot_vdf,
        ):
            return None

        # Validate reward chain VDF
        if not validate_vdf(
            eos.proofs.reward_chain_slot_proof,
            self.constants,
            ClassgroupElement.get_default_element(),
            eos.reward_chain.end_of_slot_vdf,
            VDFInfo(rc_challenge, iters, eos.reward_chain.end_of_slot_vdf.output),
        ):
            return None

        if icc_challenge is not None:
            assert icc_start_element is not None
            assert icc_iters is not None
            assert eos.infused_challenge_chain is not None
            assert eos.infused_challenge_chain is not None
            assert eos.proofs.infused_challenge_chain_slot_proof is not None
            if eos.reward_chain.deficit == self.constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK:
                # only at the end of a challenge slot
                if eos.infused_challenge_chain.get_hash() != eos.challenge_chain.infused_challenge_chain_sub_slot_hash:
                    log.error("infused_challenge_chain mismatch in challenge_chain")
                    return None
            else:
                assert eos.challenge_chain.infused_challenge_chain_sub_slot_hash is None
            assert eos.infused_challenge_chain.get_hash() == eos.reward_chain.infused_challenge_chain_sub_slot_hash

            partial_icc_vdf_info = VDFInfo(
                icc_challenge,
                iters,
                eos.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf.output,
            )
            # The EOS will have the whole sub-slot iters, but the proof is only the delta, from the last peak
            if eos.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf != partial_icc_vdf_info.replace(
                number_of_iterations=icc_iters
            ):
                return None
            if not eos.proofs.infused_challenge_chain_slot_proof.normalized_to_identity and not validate_vdf(
                eos.proofs.infused_challenge_chain_slot_proof, self.constants, icc_start_element, partial_icc_vdf_info
            ):
                return None
            if eos.proofs.infused_challenge_chain_slot_proof.normalized_to_identity and not validate_vdf(
                eos.proofs.infused_challenge_chain_slot_proof,
                self.constants,
                ClassgroupElement.get_default_element(),
                eos.infused_challenge_chain.infused_challenge_chain_end_of_slot_vdf,
            ):
                return None
        else:
            # This is the first sub slot and it's empty, therefore there is no ICC
            if eos.infused_challenge_chain is not None or eos.proofs.infused_challenge_chain_slot_proof is not None:
                return None
            if eos.challenge_chain.infused_challenge_chain_sub_slot_hash is not None:
                return None
            if eos.reward_chain.infused_challenge_chain_sub_slot_hash is not None:
                return None

        self.finished_sub_slots.append((eos, [None] * self.constants.NUM_SPS_SUB_SLOT, total_iters))

        new_cc_hash = eos.challenge_chain.get_hash()
        self.recent_eos.put(new_cc_hash, (eos, time.time()))

        new_ips: List[timelord_protocol.NewInfusionPointVDF] = []
        for ip in self.future_ip_cache.get(eos.reward_chain.get_hash(), []):
            new_ips.append(ip)

        return new_ips

    def new_signage_point(
        self,
        index: uint8,
        blocks: BlockRecordsProtocol,
        peak: Optional[BlockRecord],
        next_sub_slot_iters: uint64,
        signage_point: SignagePoint,
        skip_vdf_validation: bool = False,
    ) -> bool:
        """
        Returns true if sp successfully added
        """
        assert len(self.finished_sub_slots) >= 1

        if peak is None or peak.height < 2:
            sub_slot_iters = self.constants.SUB_SLOT_ITERS_STARTING
        else:
            sub_slot_iters = peak.sub_slot_iters

        # If we don't have this slot, return False
        if index == 0 or index >= self.constants.NUM_SPS_SUB_SLOT:
            return False
        assert (
            signage_point.cc_vdf is not None
            and signage_point.cc_proof is not None
            and signage_point.rc_vdf is not None
            and signage_point.rc_proof is not None
        )
        for sub_slot, sp_arr, start_ss_total_iters in self.finished_sub_slots:
            if sub_slot is None:
                assert start_ss_total_iters == 0
                ss_challenge_hash = self.constants.GENESIS_CHALLENGE
                ss_reward_hash = self.constants.GENESIS_CHALLENGE
            else:
                ss_challenge_hash = sub_slot.challenge_chain.get_hash()
                ss_reward_hash = sub_slot.reward_chain.get_hash()
            if ss_challenge_hash == signage_point.cc_vdf.challenge:
                # If we do have this slot, find the Prev block from SP and validate SP
                if peak is not None and start_ss_total_iters > peak.total_iters:
                    # We are in a future sub slot from the peak, so maybe there is a new SSI
                    checkpoint_size: uint64 = uint64(next_sub_slot_iters // self.constants.NUM_SPS_SUB_SLOT)
                    delta_iters: uint64 = uint64(checkpoint_size * index)
                    future_sub_slot: bool = True
                else:
                    # We are not in a future sub slot from the peak, so there is no new SSI
                    checkpoint_size = uint64(sub_slot_iters // self.constants.NUM_SPS_SUB_SLOT)
                    delta_iters = uint64(checkpoint_size * index)
                    future_sub_slot = False
                sp_total_iters = start_ss_total_iters + delta_iters

                curr = peak
                if peak is None or future_sub_slot:
                    check_from_start_of_ss = True
                else:
                    check_from_start_of_ss = False
                    while (
                        curr is not None
                        and curr.total_iters > start_ss_total_iters
                        and curr.total_iters > sp_total_iters
                    ):
                        if curr.first_in_sub_slot:
                            # Did not find a block where it's iters are before our sp_total_iters, in this ss
                            check_from_start_of_ss = True
                            break
                        curr = blocks.block_record(curr.prev_hash)

                if check_from_start_of_ss:
                    # Check VDFs from start of sub slot
                    cc_vdf_info_expected = VDFInfo(
                        ss_challenge_hash,
                        delta_iters,
                        signage_point.cc_vdf.output,
                    )

                    rc_vdf_info_expected = VDFInfo(
                        ss_reward_hash,
                        delta_iters,
                        signage_point.rc_vdf.output,
                    )
                else:
                    # Check VDFs from curr
                    assert curr is not None
                    cc_vdf_info_expected = VDFInfo(
                        ss_challenge_hash,
                        uint64(sp_total_iters - curr.total_iters),
                        signage_point.cc_vdf.output,
                    )
                    rc_vdf_info_expected = VDFInfo(
                        curr.reward_infusion_new_challenge,
                        uint64(sp_total_iters - curr.total_iters),
                        signage_point.rc_vdf.output,
                    )
                if not signage_point.cc_vdf == cc_vdf_info_expected.replace(number_of_iterations=delta_iters):
                    self.add_to_future_sp(signage_point, index)
                    return False
                if check_from_start_of_ss:
                    start_ele = ClassgroupElement.get_default_element()
                else:
                    assert curr is not None
                    start_ele = curr.challenge_vdf_output
                if not skip_vdf_validation:
                    if not signage_point.cc_proof.normalized_to_identity and not validate_vdf(
                        signage_point.cc_proof,
                        self.constants,
                        start_ele,
                        cc_vdf_info_expected,
                    ):
                        self.add_to_future_sp(signage_point, index)
                        return False
                    if signage_point.cc_proof.normalized_to_identity and not validate_vdf(
                        signage_point.cc_proof,
                        self.constants,
                        ClassgroupElement.get_default_element(),
                        signage_point.cc_vdf,
                    ):
                        self.add_to_future_sp(signage_point, index)
                        return False

                if rc_vdf_info_expected.challenge != signage_point.rc_vdf.challenge:
                    # This signage point is probably outdated
                    self.add_to_future_sp(signage_point, index)
                    return False

                if not skip_vdf_validation:
                    if not validate_vdf(
                        signage_point.rc_proof,
                        self.constants,
                        ClassgroupElement.get_default_element(),
                        signage_point.rc_vdf,
                        rc_vdf_info_expected,
                    ):
                        self.add_to_future_sp(signage_point, index)
                        return False

                sp_arr[index] = signage_point
                self.recent_signage_points.put(signage_point.cc_vdf.output.get_hash(), (signage_point, time.time()))
                return True
        self.add_to_future_sp(signage_point, index)
        return False

    def get_signage_point(self, cc_signage_point: bytes32) -> Optional[SignagePoint]:
        assert len(self.finished_sub_slots) >= 1
        if cc_signage_point == self.constants.GENESIS_CHALLENGE:
            return SignagePoint(None, None, None, None)

        for sub_slot, sps, _ in self.finished_sub_slots:
            if sub_slot is not None and sub_slot.challenge_chain.get_hash() == cc_signage_point:
                return SignagePoint(None, None, None, None)
            for sp in sps:
                if sp is not None:
                    assert sp.cc_vdf is not None
                    if sp.cc_vdf.output.get_hash() == cc_signage_point:
                        return sp
        return None

    def get_signage_point_by_index(
        self, challenge_hash: bytes32, index: uint8, last_rc_infusion: bytes32
    ) -> Optional[SignagePoint]:
        assert len(self.finished_sub_slots) >= 1
        for sub_slot, sps, _ in self.finished_sub_slots:
            if sub_slot is not None:
                cc_hash = sub_slot.challenge_chain.get_hash()
            else:
                cc_hash = self.constants.GENESIS_CHALLENGE

            if cc_hash == challenge_hash:
                if index == 0:
                    return SignagePoint(None, None, None, None)
                sp: Optional[SignagePoint] = sps[index]
                if sp is not None:
                    assert sp.rc_vdf is not None
                    if sp.rc_vdf.challenge == last_rc_infusion:
                        return sp
                return None
        return None

    def have_newer_signage_point(self, challenge_hash: bytes32, index: uint8, last_rc_infusion: bytes32) -> bool:
        """
        Returns true if we have a signage point at this index which is based on a newer infusion.
        """
        assert len(self.finished_sub_slots) >= 1
        for sub_slot, sps, _ in self.finished_sub_slots:
            if sub_slot is not None:
                cc_hash = sub_slot.challenge_chain.get_hash()
            else:
                cc_hash = self.constants.GENESIS_CHALLENGE

            if cc_hash == challenge_hash:
                found_rc_hash = False
                for i in range(0, index):
                    sp: Optional[SignagePoint] = sps[i]
                    if sp is not None and sp.rc_vdf is not None and sp.rc_vdf.challenge == last_rc_infusion:
                        found_rc_hash = True
                sp = sps[index]
                if (
                    found_rc_hash
                    and sp is not None
                    and sp.rc_vdf is not None
                    and sp.rc_vdf.challenge != last_rc_infusion
                ):
                    return True
        return False

    def new_peak(
        self,
        peak: BlockRecord,
        peak_full_block: FullBlock,
        sp_sub_slot: Optional[EndOfSubSlotBundle],  # None if not overflow, or in first/second slot
        ip_sub_slot: Optional[EndOfSubSlotBundle],  # None if in first slot
        fork_block: Optional[BlockRecord],
        blocks: BlockRecordsProtocol,
        next_sub_slot_iters: uint64,
        next_difficulty: uint64,
    ) -> FullNodeStorePeakResult:
        """
        If the peak is an overflow block, must provide two sub-slots: one for the current sub-slot and one for
        the prev sub-slot (since we still might get more blocks with an sp in the previous sub-slot)

        Results in either one or two sub-slots in finished_sub_slots.
        """
        assert len(self.finished_sub_slots) >= 1

        if ip_sub_slot is None:
            # We are still in the first sub-slot, no new sub slots ey
            self.initialize_genesis_sub_slot()
        else:
            # This is not the first sub-slot in the chain
            sp_sub_slot_sps: List[Optional[SignagePoint]] = [None] * self.constants.NUM_SPS_SUB_SLOT
            ip_sub_slot_sps: List[Optional[SignagePoint]] = [None] * self.constants.NUM_SPS_SUB_SLOT

            if fork_block is not None and fork_block.sub_slot_iters != peak.sub_slot_iters:
                # If there was a reorg and a difficulty adjustment, just clear all the slots
                self.clear_slots()
            else:
                interval_iters = calculate_sp_interval_iters(self.constants, peak.sub_slot_iters)
                # If it's not a reorg, or there is a reorg on the same difficulty, we can keep signage points
                # that we had before, in the cache
                for index, (sub_slot, sps, total_iters) in enumerate(self.finished_sub_slots):
                    if sub_slot is None:
                        continue

                    if fork_block is None:
                        # If this is not a reorg, we still want to remove signage points after the new peak
                        fork_block = peak
                    replaced_sps: List[Optional[SignagePoint]] = []  # index 0 is the end of sub slot
                    for i, sp in enumerate(sps):
                        if (total_iters + i * interval_iters) < fork_block.total_iters:
                            # Sps before the fork point as still valid
                            replaced_sps.append(sp)
                        else:
                            if sp is not None:
                                log.debug(
                                    f"Reverting {i} {(total_iters + i * interval_iters)} {fork_block.total_iters}"
                                )
                            # Sps after the fork point should be removed
                            replaced_sps.append(None)
                    assert len(sps) == len(replaced_sps)

                    if sub_slot == sp_sub_slot:
                        sp_sub_slot_sps = replaced_sps
                    if sub_slot == ip_sub_slot:
                        ip_sub_slot_sps = replaced_sps

            self.clear_slots()

            prev_sub_slot_total_iters = peak.sp_sub_slot_total_iters(self.constants)
            if sp_sub_slot is not None or prev_sub_slot_total_iters == 0:
                assert peak.overflow or prev_sub_slot_total_iters
                self.finished_sub_slots.append((sp_sub_slot, sp_sub_slot_sps, prev_sub_slot_total_iters))

            ip_sub_slot_total_iters = peak.ip_sub_slot_total_iters(self.constants)
            self.finished_sub_slots.append((ip_sub_slot, ip_sub_slot_sps, ip_sub_slot_total_iters))

        new_eos: Optional[EndOfSubSlotBundle] = None
        new_sps: List[Tuple[uint8, SignagePoint]] = []
        new_ips: List[timelord_protocol.NewInfusionPointVDF] = []

        future_eos: List[EndOfSubSlotBundle] = self.future_eos_cache.get(peak.reward_infusion_new_challenge, []).copy()
        for eos in future_eos:
            if (
                self.new_finished_sub_slot(eos, blocks, peak, next_sub_slot_iters, next_difficulty, peak_full_block)
                is not None
            ):
                new_eos = eos
                break

        future_sps: List[Tuple[uint8, SignagePoint]] = self.future_sp_cache.get(
            peak.reward_infusion_new_challenge, []
        ).copy()
        for index, sp in future_sps:
            assert sp.cc_vdf is not None
            if self.new_signage_point(index, blocks, peak, peak.sub_slot_iters, sp):
                new_sps.append((index, sp))

        for ip in self.future_ip_cache.get(peak.reward_infusion_new_challenge, []):
            new_ips.append(ip)

        self.future_eos_cache.pop(peak.reward_infusion_new_challenge, [])
        self.future_sp_cache.pop(peak.reward_infusion_new_challenge, [])
        self.future_ip_cache.pop(peak.reward_infusion_new_challenge, [])

        for eos_op, _, _ in self.finished_sub_slots:
            if eos_op is not None:
                self.recent_eos.put(eos_op.challenge_chain.get_hash(), (eos_op, time.time()))

        # Only forward the last 4 SPs that we have cached, as others will be too old
        return FullNodeStorePeakResult(new_eos, sorted(new_sps)[-4:], new_ips)

    def get_finished_sub_slots(
        self,
        block_records: BlockRecordsProtocol,
        prev_b: Optional[BlockRecord],
        last_challenge_to_add: bytes32,
    ) -> Optional[List[EndOfSubSlotBundle]]:
        """
        Retrieves the EndOfSubSlotBundles that are in the store either:
        1. From the starting challenge if prev_b is None
        2. That are not included in the blockchain with peak of prev_b if prev_b is not None

        Stops at last_challenge
        """

        if prev_b is None:
            # The first sub slot must be None
            assert self.finished_sub_slots[0][0] is None
            challenge_in_chain: bytes32 = self.constants.GENESIS_CHALLENGE
        else:
            curr: BlockRecord = prev_b
            while not curr.first_in_sub_slot:
                curr = block_records.block_record(curr.prev_hash)
            assert curr is not None
            assert curr.finished_challenge_slot_hashes is not None
            challenge_in_chain = curr.finished_challenge_slot_hashes[-1]

        if last_challenge_to_add == challenge_in_chain:
            # No additional slots to add
            return []

        collected_sub_slots: List[EndOfSubSlotBundle] = []
        found_last_challenge = False
        found_connecting_challenge = False
        for sub_slot, sps, total_iters in self.finished_sub_slots[1:]:
            assert sub_slot is not None
            if sub_slot.challenge_chain.challenge_chain_end_of_slot_vdf.challenge == challenge_in_chain:
                found_connecting_challenge = True
            if found_connecting_challenge:
                collected_sub_slots.append(sub_slot)
            if found_connecting_challenge and sub_slot.challenge_chain.get_hash() == last_challenge_to_add:
                found_last_challenge = True
                break
        if not found_last_challenge:
            log.warning(f"Did not find hash {last_challenge_to_add} connected to {challenge_in_chain}")
            return None
        return collected_sub_slots
