import asyncio
import dataclasses
import logging
from concurrent.futures.process import ProcessPoolExecutor
from src.util.streamable import recurse_jsonify
from enum import Enum
import multiprocessing
from typing import Dict, List, Optional, Tuple

from src.consensus.constants import ConsensusConstants
from src.consensus.block_body_validation import validate_block_body
from src.consensus.get_block_challenge import get_block_challenge
from src.consensus.pot_iterations import is_overflow_sub_block, calculate_iterations_quality
from src.full_node.block_store import BlockStore
from src.full_node.coin_store import CoinStore
from src.consensus.difficulty_adjustment import (
    get_next_difficulty,
    get_next_sub_slot_iters,
    get_sub_slot_iters_and_difficulty,
)
from src.consensus.full_block_to_sub_block_record import block_to_sub_block_record
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.full_block import FullBlock
from src.types.sized_bytes import bytes32
from src.consensus.sub_block_record import SubBlockRecord
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
from src.util.errors import Err
from src.util.ints import uint32, uint64, uint128
from src.consensus.find_fork_point import find_fork_point_in_chain
from src.consensus.block_header_validation import (
    validate_finished_header_block,
    validate_unfinished_header_block,
    batch_validate_finished_header_block_pickled,
)
from src.types.unfinished_header_block import UnfinishedHeaderBlock

log = logging.getLogger(__name__)


class ReceiveBlockResult(Enum):
    """
    When Blockchain.receive_block(b) is called, one of these results is returned,
    showing whether the block was added to the chain (extending the peak),
    and if not, why it was not added.
    """

    NEW_PEAK = 1  # Added to the peak of the blockchain
    ADDED_AS_ORPHAN = 2  # Added as an orphan/stale block (not a new peak of the chain)
    INVALID_BLOCK = 3  # Block was not added because it was invalid
    ALREADY_HAVE_BLOCK = 4  # Block is already present in this blockchain
    DISCONNECTED_BLOCK = 5  # Block's parent (previous pointer) is not in this blockchain


class Blockchain:
    constants: ConsensusConstants
    constants_json: Dict

    # peak of the blockchain
    peak_height: Optional[uint32]
    # All sub blocks in peak path are guaranteed to be included, can include orphan sub-blocks
    sub_blocks: Dict[bytes32, SubBlockRecord]
    # Defines the path from genesis to the peak, no orphan sub-blocks
    sub_height_to_hash: Dict[uint32, bytes32]
    # All sub-epoch summaries that have been included in the blockchain from the beginning until and including the peak
    # (height_included, SubEpochSummary). Note: ONLY for the sub-blocks in the path to the peak
    sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}
    # Unspent Store
    coin_store: CoinStore
    # Store
    block_store: BlockStore
    # Used to verify blocks in parallel
    pool: ProcessPoolExecutor
    batch_size: int

    # Whether blockchain is shut down or not
    _shut_down: bool

    # Lock to prevent simultaneous reads and writes
    lock: asyncio.Lock

    @staticmethod
    async def create(
        coin_store: CoinStore,
        block_store: BlockStore,
        consensus_constants: ConsensusConstants,
    ):
        """
        Initializes a blockchain with the SubBlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = Blockchain()
        self.lock = asyncio.Lock()  # External lock handled by full node
        cpu_count = multiprocessing.cpu_count()
        if cpu_count > 61:
            cpu_count = 61  # Windows Server 2016 has an issue https://bugs.python.org/issue26903
        self.pool = ProcessPoolExecutor(max_workers=max(cpu_count - 2, 1))
        log.info(f"Cpu count {cpu_count}")
        self.batch_size = 4
        self.pool = ProcessPoolExecutor(max_workers=max(cpu_count, 1))

        self.constants = consensus_constants
        self.coin_store = coin_store
        self.block_store = block_store
        self.constants_json = recurse_jsonify(dataclasses.asdict(self.constants))
        self._shut_down = False
        await self._load_chain_from_store()
        return self

    def shut_down(self):
        self._shut_down = True
        self.pool.shutdown(wait=True)

    async def _load_chain_from_store(self) -> None:
        """
        Initializes the state of the Blockchain class from the database.
        """
        self.sub_blocks, peak = await self.block_store.get_sub_block_records()
        self.sub_height_to_hash = {}
        self.sub_epoch_summaries = {}

        if len(self.sub_blocks) == 0:
            assert peak is None
            self.peak_height = None
            return

        assert peak is not None
        self.peak_height = self.sub_blocks[peak].sub_block_height

        # Sets the other state variables (peak_height and height_to_hash)
        curr: SubBlockRecord = self.sub_blocks[peak]
        while True:
            self.sub_height_to_hash[curr.sub_block_height] = curr.header_hash
            if curr.sub_epoch_summary_included is not None:
                self.sub_epoch_summaries[curr.sub_block_height] = curr.sub_epoch_summary_included
            if curr.sub_block_height == 0:
                break
            curr = self.sub_blocks[curr.prev_hash]
        assert len(self.sub_height_to_hash) == self.peak_height + 1

    def get_peak(self) -> Optional[SubBlockRecord]:
        """
        Return the peak of the blockchain
        """
        if self.peak_height is None:
            return None
        return self.sub_blocks[self.sub_height_to_hash[self.peak_height]]

    async def get_full_peak(self) -> Optional[FullBlock]:
        if self.peak_height is None:
            return None
        """ Return list of FullBlocks that are peaks"""
        block = await self.block_store.get_full_block(self.sub_height_to_hash[self.peak_height])
        assert block is not None
        return block

    async def get_block_peak(self) -> Optional[FullBlock]:
        """ Return peak block"""
        if self.peak_height is None:
            return None
        start = int(self.peak_height)
        peak = None
        while start >= 0:
            block = await self.block_store.get_full_block(self.sub_height_to_hash[uint32(start)])
            if block is not None and block.is_block():
                peak = block
                break
            start -= 1

        return peak

    def is_child_of_peak(self, block: UnfinishedBlock) -> bool:
        """
        True iff the block is the direct ancestor of the peak
        """
        peak = self.get_peak()
        if peak is None:
            return False

        return block.prev_header_hash == peak.header_hash

    def contains_sub_block(self, header_hash: bytes32) -> bool:
        """
        True if we have already added this block to the chain. This may return false for orphan sub-blocks
        that we have added but no longer keep in memory.
        """
        return header_hash in self.sub_blocks

    async def get_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return await self.block_store.get_full_block(header_hash)

    async def receive_block(
        self,
        block: FullBlock,
        pre_validated: bool = False,
        required_iters: Optional[uint64] = None,
    ) -> Tuple[ReceiveBlockResult, Optional[Err], Optional[uint32]]:
        """
        This method must be called under the blockchain lock
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        Returns a header if block is added to head. Returns an error if the block is
        invalid. Also returns the fork height, in the case of a new peak.
        """
        genesis: bool = block.sub_block_height == 0

        if block.header_hash in self.sub_blocks:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None, None

        if block.prev_header_hash not in self.sub_blocks and not genesis:
            return (
                ReceiveBlockResult.DISCONNECTED_BLOCK,
                Err.INVALID_PREV_BLOCK_HASH,
                None,
            )

        if not pre_validated:
            if block.sub_block_height == 0:
                prev_sb: Optional[SubBlockRecord] = None
            else:
                prev_sb = self.sub_blocks[block.prev_header_hash]
            sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
                self.constants, block, self.sub_height_to_hash, prev_sb, self.sub_blocks
            )
            required_iters, error = validate_finished_header_block(
                self.constants,
                self.sub_blocks,
                await block.get_block_header(),
                False,
                difficulty,
                sub_slot_iters,
            )

            if error is not None:
                return ReceiveBlockResult.INVALID_BLOCK, error.code, None
        assert required_iters is not None

        error_code = await validate_block_body(
            self.constants,
            self.sub_blocks,
            self.sub_height_to_hash,
            self.block_store,
            self.coin_store,
            self.get_peak(),
            block,
            block.sub_block_height,
            block.height if block.is_block() else None,
        )

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error_code, None

        sub_block = block_to_sub_block_record(
            self.constants,
            self.sub_blocks,
            self.sub_height_to_hash,
            required_iters,
            block,
            None,
        )

        # Always add the block to the database
        await self.block_store.add_full_block(block, sub_block)
        self.sub_blocks[sub_block.header_hash] = sub_block

        fork_height: Optional[uint32] = await self._reconsider_peak(sub_block, genesis)
        if fork_height is not None:
            return ReceiveBlockResult.NEW_PEAK, None, fork_height
        else:
            return ReceiveBlockResult.ADDED_AS_ORPHAN, None, None

    async def _reconsider_peak(self, sub_block: SubBlockRecord, genesis: bool) -> Optional[uint32]:
        """
        When a new block is added, this is called, to check if the new block is the new peak of the chain.
        This also handles reorgs by reverting blocks which are not in the heaviest chain.
        It returns the height of the fork between the previous chain and the new chain, or returns
        None if there was no update to the heaviest chain.
        """
        peak = self.get_peak()
        if genesis:
            if peak is None:
                block: Optional[FullBlock] = await self.block_store.get_full_block(sub_block.header_hash)
                assert block is not None
                await self.coin_store.new_block(block)
                self.sub_height_to_hash[uint32(0)] = block.header_hash
                self.peak_height = uint32(0)
                await self.block_store.set_peak(block.header_hash)
                return uint32(0)
            return None

        assert peak is not None
        if sub_block.weight > peak.weight:
            # Find the fork. if the block is just being appended, it will return the peak
            # If no blocks in common, returns -1, and reverts all blocks
            fork_sub_block_height: int = find_fork_point_in_chain(self.sub_blocks, sub_block, peak)
            if fork_sub_block_height == -1:
                coin_store_reorg_height = -1
            else:
                last_sb_in_common = self.sub_blocks[self.sub_height_to_hash[uint32(fork_sub_block_height)]]
                if last_sb_in_common.is_block:
                    coin_store_reorg_height = last_sb_in_common.height
                else:
                    coin_store_reorg_height = last_sb_in_common.height - 1

            # Rollback to fork
            await self.coin_store.rollback_to_block(coin_store_reorg_height)

            # Rollback sub_epoch_summaries
            heights_to_delete = []
            for ses_included_height in self.sub_epoch_summaries.keys():
                if ses_included_height > fork_sub_block_height:
                    heights_to_delete.append(ses_included_height)
            for sub_height in heights_to_delete:
                del self.sub_epoch_summaries[sub_height]

            # Collect all blocks from fork point to new peak
            blocks_to_add: List[Tuple[FullBlock, SubBlockRecord]] = []
            curr = sub_block.header_hash
            while fork_sub_block_height < 0 or curr != self.sub_height_to_hash[uint32(fork_sub_block_height)]:
                fetched_block: Optional[FullBlock] = await self.block_store.get_full_block(curr)
                fetched_sub_block: Optional[SubBlockRecord] = await self.block_store.get_sub_block_record(curr)
                assert fetched_block is not None
                assert fetched_sub_block is not None
                blocks_to_add.append((fetched_block, fetched_sub_block))
                if fetched_block.sub_block_height == 0:
                    # Doing a full reorg, starting at height 0
                    break
                curr = fetched_sub_block.prev_hash

            for fetched_block, fetched_sub_block in reversed(blocks_to_add):
                self.sub_height_to_hash[fetched_sub_block.sub_block_height] = fetched_sub_block.header_hash
                if fetched_sub_block.is_block:
                    await self.coin_store.new_block(fetched_block)
                if fetched_sub_block.sub_epoch_summary_included is not None:
                    self.sub_epoch_summaries[
                        fetched_sub_block.sub_block_height
                    ] = fetched_sub_block.sub_epoch_summary_included

            # Changes the peak to be the new peak
            await self.block_store.set_peak(sub_block.header_hash)
            self.peak_height = sub_block.sub_block_height
            return uint32(max(fork_sub_block_height, 0))

        # This is not a heavier block than the heaviest we have seen, so we don't change the coin set
        return None

    def get_next_difficulty(self, header_hash: bytes32, new_slot: bool) -> uint64:
        assert header_hash in self.sub_blocks
        curr = self.sub_blocks[header_hash]
        if curr.sub_block_height <= 2:
            return self.constants.DIFFICULTY_STARTING
        return get_next_difficulty(
            self.constants,
            self.sub_blocks,
            self.sub_height_to_hash,
            header_hash,
            curr.sub_block_height,
            uint64(curr.weight - self.sub_blocks[curr.prev_hash].weight),
            curr.deficit,
            new_slot,
            curr.sp_total_iters(self.constants),
        )

    def get_next_slot_iters(self, header_hash: bytes32, new_slot: bool) -> uint64:
        assert header_hash in self.sub_blocks
        curr = self.sub_blocks[header_hash]
        if curr.sub_block_height <= 2:
            return self.constants.SUB_SLOT_ITERS_STARTING
        return get_next_sub_slot_iters(
            self.constants,
            self.sub_blocks,
            self.sub_height_to_hash,
            header_hash,
            curr.sub_block_height,
            curr.sub_slot_iters,
            curr.deficit,
            new_slot,
            curr.sp_total_iters(self.constants),
        )

    async def get_sp_and_ip_sub_slots(
        self, header_hash: bytes32
    ) -> Optional[Tuple[Optional[EndOfSubSlotBundle], Optional[EndOfSubSlotBundle]]]:
        block: Optional[FullBlock] = await self.block_store.get_full_block(header_hash)
        if block is None:
            return None
        is_overflow = self.sub_blocks[block.header_hash].overflow

        curr_sbr: SubBlockRecord = self.sub_blocks[block.header_hash]
        curr: Optional[FullBlock] = block
        assert curr is not None
        while curr_sbr.sub_block_height > 0:
            if curr_sbr.first_in_sub_slot:
                curr = await self.block_store.get_full_block(curr_sbr.header_hash)
                assert curr is not None
                break
            curr_sbr = self.sub_blocks[curr_sbr.prev_hash]

        if len(curr.finished_sub_slots) == 0:
            # This means we got to genesis and still no sub-slots
            return None, None

        ip_sub_slot = curr.finished_sub_slots[-1]

        if not is_overflow:
            # Pos sub-slot is the same as infusion sub slot
            return None, ip_sub_slot

        if len(curr.finished_sub_slots) > 1:
            # Have both sub-slots
            return curr.finished_sub_slots[-2], ip_sub_slot

        prev_curr: Optional[FullBlock] = await self.block_store.get_full_block(curr.prev_header_hash)
        if prev_curr is None:
            assert curr.sub_block_height == 0
            prev_curr = curr
            prev_curr_sbr = self.sub_blocks[curr.header_hash]
        else:
            prev_curr_sbr = self.sub_blocks[curr.prev_header_hash]
        assert prev_curr_sbr is not None
        while prev_curr_sbr.sub_block_height > 0:
            if prev_curr_sbr.first_in_sub_slot:
                prev_curr = await self.block_store.get_full_block(prev_curr_sbr.header_hash)
                assert prev_curr is not None
                break
            prev_curr_sbr = self.sub_blocks[prev_curr_sbr.prev_hash]

        if len(prev_curr.finished_sub_slots) == 0:
            return None, ip_sub_slot
        return prev_curr.finished_sub_slots[-1], ip_sub_slot

    def get_recent_reward_challenges(self) -> List[Tuple[bytes32, uint128]]:
        peak = self.get_peak()
        if peak is None:
            return []
        recent_rc: List[Tuple[bytes32, uint128]] = []
        curr = self.sub_blocks.get(peak.prev_hash, None)
        while curr is not None and len(recent_rc) < 2 * self.constants.MAX_SUB_SLOT_SUB_BLOCKS:
            recent_rc.append((curr.reward_infusion_new_challenge, curr.total_iters))
            if curr.first_in_sub_slot:
                assert curr.finished_reward_slot_hashes is not None
                sub_slot_total_iters = curr.ip_sub_slot_total_iters(self.constants)
                # Start from the most recent
                for rc in reversed(curr.finished_reward_slot_hashes):
                    recent_rc.append((rc, sub_slot_total_iters))
                    sub_slot_total_iters = uint128(sub_slot_total_iters - curr.sub_slot_iters)
            curr = self.sub_blocks.get(curr.prev_hash, None)
        return list(reversed(recent_rc))

    async def pre_validate_blocks_multiprocessing(self, blocks: List[FullBlock]) -> Optional[List[uint64]]:
        """
        This method must be called under the blockchain lock
        If all the full blocks pass pre-validation, (only validates header), returns the list of required iters.
        if any validation issue occurs, returns False.

        Args:
            blocks: list of full blocks to validate (must be connected to current chain)
        """
        prev_sb: Optional[SubBlockRecord] = None
        # Collects all the recent sub-blocks (up to the previous sub-epoch)
        recent_sub_blocks: Dict[bytes32, SubBlockRecord] = {}
        recent_sub_blocks_compressed: Dict[bytes32, SubBlockRecord] = {}
        num_sub_slots_found = 0
        num_blocks_seen = 0
        if blocks[0].sub_block_height > 0:
            curr = self.sub_blocks[blocks[0].prev_header_hash]
            num_sub_slots_to_look_for = 3 if curr.overflow else 2
            while (
                curr.sub_epoch_summary_included is None
                or num_blocks_seen < self.constants.NUMBER_OF_TIMESTAMPS
                or num_sub_slots_found < num_sub_slots_to_look_for
            ) and curr.sub_block_height > 0:
                if (
                    num_blocks_seen < self.constants.NUMBER_OF_TIMESTAMPS
                    or num_sub_slots_found < num_sub_slots_to_look_for
                ):
                    recent_sub_blocks_compressed[curr.header_hash] = curr

                if curr.first_in_sub_slot:
                    assert curr.finished_challenge_slot_hashes is not None
                    num_sub_slots_found += len(curr.finished_challenge_slot_hashes)
                recent_sub_blocks[curr.header_hash] = curr
                if curr.is_block:
                    num_blocks_seen += 1
                curr = self.sub_blocks[curr.prev_hash]
            recent_sub_blocks[curr.header_hash] = curr
            recent_sub_blocks_compressed[curr.header_hash] = curr
        sub_block_was_present = []
        for block in blocks:
            sub_block_was_present.append(block.header_hash in self.sub_blocks)

        diff_ssis: List[Tuple[uint64, uint64]] = []
        for sub_block in blocks:
            if sub_block.sub_block_height != 0 and prev_sb is None:
                prev_sb = self.sub_blocks[sub_block.prev_header_hash]
            sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
                self.constants, sub_block, self.sub_height_to_hash, prev_sb, self.sub_blocks
            )
            overflow = is_overflow_sub_block(self.constants, sub_block.reward_chain_sub_block.signage_point_index)
            challenge = get_block_challenge(
                self.constants,
                sub_block,
                recent_sub_blocks,
                prev_sb is None,
                overflow,
                False,
            )
            if sub_block.reward_chain_sub_block.challenge_chain_sp_vdf is None:
                cc_sp_hash: bytes32 = challenge
            else:
                cc_sp_hash = sub_block.reward_chain_sub_block.challenge_chain_sp_vdf.output.get_hash()
            q_str: Optional[bytes32] = sub_block.reward_chain_sub_block.proof_of_space.verify_and_get_quality_string(
                self.constants, challenge, cc_sp_hash
            )
            if q_str is None:
                for i, block_i in enumerate(blocks):
                    if not sub_block_was_present[i] and block_i.header_hash in self.sub_blocks:
                        del self.sub_blocks[block_i.header_hash]
                return None

            required_iters: uint64 = calculate_iterations_quality(
                q_str,
                sub_block.reward_chain_sub_block.proof_of_space.size,
                difficulty,
                cc_sp_hash,
            )

            sub_block_rec = block_to_sub_block_record(
                self.constants,
                self.sub_blocks,
                self.sub_height_to_hash,
                required_iters,
                sub_block,
                None,
            )
            recent_sub_blocks[sub_block_rec.header_hash] = sub_block_rec
            recent_sub_blocks_compressed[sub_block_rec.header_hash] = sub_block_rec
            self.sub_blocks[sub_block_rec.header_hash] = sub_block_rec  # Temporarily add sub block to dict
            prev_sb = sub_block_rec
            diff_ssis.append((difficulty, sub_slot_iters))

        for i, block in enumerate(blocks):
            if not sub_block_was_present[i]:
                del self.sub_blocks[block.header_hash]

        recent_sb_compressed_pickled = {bytes(k): bytes(v) for k, v in recent_sub_blocks_compressed.items()}

        futures = []
        # Pool of workers to validate blocks concurrently
        for i in range(0, len(blocks), self.batch_size):
            end_i = min(i + self.batch_size, len(blocks))
            blocks_to_validate = blocks[i:end_i]
            if any([len(block.finished_sub_slots) > 0 for block in blocks_to_validate]):
                final_pickled = {bytes(k): bytes(v) for k, v in recent_sub_blocks.items()}
            else:
                final_pickled = recent_sb_compressed_pickled

            if self._shut_down:
                return None
            futures.append(
                asyncio.get_running_loop().run_in_executor(
                    self.pool,
                    batch_validate_finished_header_block_pickled,
                    self.constants_json,
                    final_pickled,
                    [bytes(await block.get_block_header()) for block in blocks_to_validate],
                    True,
                    [diff_ssis[j][0] for j in range(i, end_i)],
                    [diff_ssis[j][1] for j in range(i, end_i)],
                )
            )
        results = await asyncio.gather(*futures)
        returned_iters = []

        i = 0
        for block_batch in results:
            for it, error in block_batch:
                if error is not None:
                    log.error(f"Validation error on sb: {blocks[i].sub_block_height} {blocks[i].header_hash}, {error}")
                    return None
                returned_iters.append(it)
                i += 1
        assert len(blocks) == len(returned_iters)
        return returned_iters

    async def validate_unfinished_block(
        self, block: UnfinishedBlock, skip_overflow_ss_validation=True
    ) -> Tuple[Optional[uint64], Optional[Err]]:
        if (
            block.prev_header_hash not in self.sub_blocks
            and not block.prev_header_hash == self.constants.GENESIS_PREV_HASH
        ):
            return None, Err.INVALID_PREV_BLOCK_HASH

        unfinished_header_block = UnfinishedHeaderBlock(
            block.finished_sub_slots,
            block.reward_chain_sub_block,
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage_sub_block,
            block.foliage_block,
            b"",
        )
        prev_sb = self.sub_blocks.get(unfinished_header_block.prev_header_hash, None)
        sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
            self.constants, unfinished_header_block, self.sub_height_to_hash, prev_sb, self.sub_blocks
        )
        required_iters, error = validate_unfinished_header_block(
            self.constants,
            self.sub_blocks,
            unfinished_header_block,
            False,
            difficulty,
            sub_slot_iters,
            skip_overflow_ss_validation,
        )

        if error is not None:
            return None, error.code

        prev_sub_height = (
            -1
            if block.prev_header_hash == self.constants.GENESIS_PREV_HASH
            else self.sub_blocks[block.prev_header_hash].sub_block_height
        )

        if block.is_block():
            assert block.foliage_block is not None
            height: Optional[uint32] = block.foliage_block.height
        else:
            height = None
        error_code = await validate_block_body(
            self.constants,
            self.sub_blocks,
            self.sub_height_to_hash,
            self.block_store,
            self.coin_store,
            self.get_peak(),
            block,
            uint32(prev_sub_height + 1),
            height,
        )

        if error_code is not None:
            return None, error_code

        return required_iters, None
