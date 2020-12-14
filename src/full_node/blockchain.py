import asyncio
import logging
from concurrent.futures.process import ProcessPoolExecutor
from enum import Enum
import multiprocessing
from typing import Dict, List, Optional, Tuple

from src.consensus.constants import ConsensusConstants
from src.full_node.block_body_validation import validate_block_body
from src.full_node.block_store import BlockStore
from src.full_node.coin_store import CoinStore
from src.full_node.difficulty_adjustment import get_next_difficulty, get_next_ips
from src.full_node.full_block_to_sub_block_record import full_block_to_sub_block_record
from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.unfinished_block import UnfinishedBlock
from src.types.sized_bytes import bytes32
from src.full_node.sub_block_record import SubBlockRecord
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
from src.util.errors import Err
from src.util.ints import uint32, uint64
from src.consensus.find_fork_point import find_fork_point_in_chain
from src.full_node.block_header_validation import (
    validate_finished_header_block,
    validate_unfinished_header_block,
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
    DISCONNECTED_BLOCK = (
        5  # Block's parent (previous pointer) is not in this blockchain
    )


class Blockchain:
    constants: ConsensusConstants
    # peak of the blockchain
    peak_height: Optional[uint32]
    # All sub blocks in peak path are guaranteed to be included, can include orphan sub-blocks
    sub_blocks: Dict[bytes32, SubBlockRecord]
    # Defines the path from genesis to the peak, no orphan sub-blocks
    height_to_hash: Dict[uint32, bytes32]
    # All sub-epoch summaries that have been included in the blockchain from the beginning until and including the peak
    # (height_included, SubEpochSummary). Note: ONLY for the sub-blocks in the path to the peak
    sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}
    # Unspent Store
    coin_store: CoinStore
    # Store
    block_store: BlockStore
    # Used to verify blocks in parallel
    pool: ProcessPoolExecutor

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
        self.pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=max(cpu_count - 2, 1)
        )
        self.constants = consensus_constants
        self.coin_store = coin_store
        self.block_store = block_store
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
        self.height_to_hash = {}
        self.sub_epoch_summaries = {}

        if len(self.sub_blocks) == 0:
            assert peak is None
            log.info("Initializing empty blockchain")
            self.peak_height = None
            return

        assert peak is not None
        self.peak_height = self.sub_blocks[peak].height

        # Sets the other state variables (peak_height and height_to_hash)
        curr: SubBlockRecord = self.sub_blocks[peak]
        while True:
            self.height_to_hash[curr.height] = curr.header_hash
            if curr.sub_epoch_summary_included is not None:
                self.sub_epoch_summaries[curr.height] = curr.sub_epoch_summary_included
            if curr.height == 0:
                break
            curr = self.sub_blocks[curr.prev_hash]
        assert len(self.sub_blocks) == len(self.height_to_hash) == self.peak_height + 1

    def get_peak(self) -> Optional[SubBlockRecord]:
        """
        Return the peak of the blockchain
        """
        if self.peak_height is None:
            return None
        return self.sub_blocks[self.height_to_hash[self.peak_height]]

    async def get_full_peak(self) -> Optional[FullBlock]:
        if self.peak_height is None:
            return None
        """ Return list of FullBlocks that are peaks"""
        block = await self.block_store.get_full_block(self.height_to_hash[self.peak_height])
        assert block is not None
        return block

    def is_child_of_peak(self, block: UnfinishedBlock) -> bool:
        """
        True iff the block is the direct ancestor of the peak
        """
        if self.peak_height is None:
            return False
        return block.prev_header_hash == self.get_peak().header_hash

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
    ) -> Tuple[ReceiveBlockResult, Optional[Err], Optional[uint32]]:
        """
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        Returns a header if block is added to head. Returns an error if the block is
        invalid. Also returns the fork height, in the case of a new peak.
        """
        genesis: bool = block.height == 0

        if block.header_hash in self.sub_blocks:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None, None

        if block.prev_header_hash not in self.sub_blocks and not genesis:
            return ReceiveBlockResult.DISCONNECTED_BLOCK, None, None

        curr_header_block = HeaderBlock(
            block.finished_sub_slots,
            block.reward_chain_sub_block,
            block.challenge_chain_sp_proof,
            block.challenge_chain_ip_proof,
            block.reward_chain_sp_proof,
            block.reward_chain_ip_proof,
            block.infused_challenge_chain_ip_proof,
            block.foliage_sub_block,
            block.foliage_block,
            b"",  # No filter
        )
        required_iters, error = await validate_finished_header_block(
            self.constants,
            self.sub_blocks,
            self.height_to_hash,
            curr_header_block,
            False,
        )

        if error is not None:
            log.error(f"block {curr_header_block.header_hash} failed validation " + error.error_msg)
            return ReceiveBlockResult.INVALID_BLOCK, error.code, None

        error_code = await validate_block_body(
            self.constants, self.sub_blocks, self.block_store, self.coin_store, self.get_peak(), block
        )

        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error_code, None

        sub_block = full_block_to_sub_block_record(
            self.constants,
            self.sub_blocks,
            self.height_to_hash,
            block,
            required_iters,
        )

        # Always add the block to the database
        await self.block_store.add_full_block(block, sub_block)
        self.sub_blocks[sub_block.header_hash] = sub_block

        fork_height: Optional[uint32] = await self._reconsider_peak(sub_block, genesis)
        if fork_height is not None:
            return ReceiveBlockResult.NEW_PEAK, None, fork_height
        else:
            return ReceiveBlockResult.ADDED_AS_ORPHAN, None, None

    async def _reconsider_peak(
        self, sub_block: SubBlockRecord, genesis: bool
    ) -> Optional[uint32]:
        """
        When a new block is added, this is called, to check if the new block is the new peak of the chain.
        This also handles reorgs by reverting blocks which are not in the heaviest chain.
        It returns the height of the fork between the previous chain and the new chain, or returns
        None if there was no update to the heaviest chain.
        """
        if genesis:
            block: Optional[FullBlock] = await self.block_store.get_full_block(sub_block.header_hash)
            assert block is not None
            await self.coin_store.new_block(block)
            self.height_to_hash[uint32(0)] = block.header_hash
            self.peak_height = uint32(0)
            return uint32(0)

        assert self.get_peak() is not None
        if sub_block.weight > self.get_peak().weight:
            # Find the fork. if the block is just being appended, it will return the peak
            # If no blocks in common, returns -1, and reverts all blocks
            fork_h: int = find_fork_point_in_chain(
                self.sub_blocks, sub_block, self.get_peak()
            )

            # Rollback to fork
            await self.coin_store.rollback_to_block(fork_h)

            # Rollback sub_epoch_summaries
            for ses_included_height in self.sub_epoch_summaries.keys():
                if ses_included_height > fork_h:
                    del self.sub_epoch_summaries[ses_included_height]

            # Collect all blocks from fork point to new peak
            blocks_to_add: List[Tuple[FullBlock, SubBlockRecord]] = []
            curr = sub_block.header_hash
            while fork_h < 0 or curr != self.height_to_hash[uint32(fork_h)]:
                fetched_block: Optional[FullBlock] = await self.block_store.get_full_block(curr)
                fetched_sub_block: Optional[SubBlockRecord] = await self.block_store.get_sub_block_record(curr)
                assert fetched_block is not None
                assert fetched_sub_block is not None
                blocks_to_add.append((fetched_block, fetched_sub_block))
                if fetched_block.height == 0:
                    # Doing a full reorg, starting at height 0
                    break
                curr = fetched_sub_block.prev_hash

            for fetched_block, fetched_sub_block in reversed(blocks_to_add):
                self.height_to_hash[fetched_sub_block.height] = fetched_sub_block.header_hash
                if fetched_sub_block.is_block:
                    await self.coin_store.new_block(fetched_block)
                if fetched_sub_block.sub_epoch_summary_included is not None:
                    self.sub_epoch_summaries[fetched_sub_block.height] = fetched_sub_block.sub_epoch_summary_included

            # Changes the peak to be the new peak
            await self.block_store.set_peak(sub_block.header_hash)
            self.peak_height = sub_block.height
            return uint32(min(fork_h, 0))

        # This is not a heavier block than the heaviest we have seen, so we don't change the coin set
        return None

    def get_next_difficulty(self, header_hash: bytes32, new_slot: bool) -> uint64:
        assert header_hash in self.sub_blocks
        curr = self.sub_blocks[header_hash]
        return get_next_difficulty(
            self.constants,
            self.sub_blocks,
            self.height_to_hash,
            header_hash,
            curr.height,
            uint64(curr.weight - self.sub_blocks[curr.prev_hash].weight),
            curr.deficit,
            new_slot,
            curr.sp_total_iters(self.constants),
        )

    def get_next_slot_iters(self, header_hash: bytes32, new_slot: bool) -> uint64:
        assert header_hash in self.sub_blocks
        curr = self.sub_blocks[header_hash]
        return (
            get_next_ips(
                self.constants,
                self.sub_blocks,
                self.height_to_hash,
                header_hash,
                curr.height,
                curr.ips,
                curr.deficit,
                new_slot,
                curr.sp_total_iters(self.constants),
            )
            * self.constants.SLOT_TIME_TARGET
        )

    async def pre_validate_blocks_mulpeakrocessing(
        self, blocks: List[FullBlock]
    ) -> List[Tuple[bool, Optional[bytes32]]]:
        # TODO(mariano): re-write
        # futures = []
        # # Pool of workers to validate blocks concurrently
        # for block in blocks:
        #     if self._shut_down:
        #         return [(False, None) for _ in range(len(blocks))]
        #     futures.append(
        #         asyncio.get_running_loop().run_in_executor(
        #             self.pool,
        #             pre_validate_finished_block_header,
        #             self.constants,
        #             bytes(block),
        #         )
        #     )
        # results = await asyncio.gather(*futures)
        #
        # for i, (val, pos) in enumerate(results):
        #     if pos is not None:
        #         pos = bytes32(pos)
        #     results[i] = val, pos
        # return results
        return []

    async def validate_unfinished_block(
        self, block: UnfinishedBlock
    ) -> Tuple[Optional[uint64], Optional[Err]]:
        if block.header_hash in self.sub_blocks:
            return (
                self.sub_blocks[block.header_hash].required_iters,
                None,
            )  # Already validated and added

        if block.prev_header_hash not in self.sub_blocks and not block.height == 0:
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

        required_iters, error_code = await validate_unfinished_header_block(
            self.constants,
            self.sub_blocks,
            self.height_to_hash,
            unfinished_header_block,
            False,
        )

        if error_code is not None:
            return None, error_code.code

        error_code = await validate_block_body(
            self.constants, self.sub_blocks, self.block_store, self.coin_store, self.get_peak(), block
        )

        if error_code is not None:
            return None, error_code

        return required_iters, None
