import asyncio
import logging
from concurrent.futures.process import ProcessPoolExecutor
from enum import Enum
import multiprocessing
from typing import Dict, List, Optional, Tuple, Callable, Any

from src.consensus.constants import ConsensusConstants
from src.consensus.difficulty_adjustment import (
    get_next_difficulty,
    get_next_sub_slot_iters,
    get_sub_slot_iters_and_difficulty,
)
from src.consensus.full_block_to_sub_block_record import block_to_sub_block_record
from src.types.end_of_slot_bundle import EndOfSubSlotBundle
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.consensus.sub_block_record import SubBlockRecord
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.unfinished_block import UnfinishedBlock
from src.util.errors import Err
from src.util.ints import uint32, uint64
from src.consensus.find_fork_point import find_fork_point_in_chain
from src.consensus.block_header_validation import validate_finished_header_block
from src.wallet.block_record import HeaderBlockRecord
from src.wallet.wallet_coin_store import WalletCoinStore
from src.wallet.wallet_block_store import WalletBlockStore

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


class WalletBlockchain:
    constants: ConsensusConstants
    # peak of the blockchain
    peak_sub_height: Optional[uint32]
    # All sub blocks in peak path are guaranteed to be included, can include orphan sub-blocks
    sub_blocks: Dict[bytes32, SubBlockRecord]
    # Defines the path from genesis to the peak, no orphan sub-blocks
    sub_height_to_hash: Dict[uint32, bytes32]
    # All sub-epoch summaries that have been included in the blockchain from the beginning until and including the peak
    # (height_included, SubEpochSummary). Note: ONLY for the sub-blocks in the path to the peak
    sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}
    # Unspent Store
    coin_store: WalletCoinStore
    # Store
    block_store: WalletBlockStore
    # Used to verify blocks in parallel
    pool: ProcessPoolExecutor

    coins_of_interest_received: Any
    reorg_rollback: Any

    # Whether blockchain is shut down or not
    _shut_down: bool

    # Lock to prevent simultaneous reads and writes
    lock: asyncio.Lock
    log: logging.Logger

    @staticmethod
    async def create(
        block_store: WalletBlockStore,
        consensus_constants: ConsensusConstants,
        coins_of_interest_received: Callable,  # f(removals: List[Coin], additions: List[Coin], height: uint32)
        reorg_rollback: Callable,
    ):
        """
        Initializes a blockchain with the SubBlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = WalletBlockchain()
        self.lock = asyncio.Lock()  # External lock handled by full node
        cpu_count = multiprocessing.cpu_count()
        if cpu_count > 61:
            cpu_count = 61  # Windows Server 2016 has an issue https://bugs.python.org/issue26903
        self.pool = ProcessPoolExecutor(max_workers=max(cpu_count - 2, 1))
        self.constants = consensus_constants
        self.block_store = block_store
        self._shut_down = False
        self.coins_of_interest_received = coins_of_interest_received
        self.reorg_rollback = reorg_rollback
        self.log = logging.getLogger(__name__)
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
            log.info("Initializing empty blockchain")
            self.peak_sub_height = None
            return

        assert peak is not None
        self.peak_sub_height = self.sub_blocks[peak].sub_block_height

        # Sets the other state variables (peak_height and height_to_hash)
        curr: SubBlockRecord = self.sub_blocks[peak]
        while True:
            self.sub_height_to_hash[curr.sub_block_height] = curr.header_hash
            if curr.sub_epoch_summary_included is not None:
                self.sub_epoch_summaries[curr.sub_block_height] = curr.sub_epoch_summary_included
            if curr.height == 0:
                break
            curr = self.sub_blocks[curr.prev_hash]

        assert len(self.sub_height_to_hash) == self.peak_sub_height + 1

    def get_peak(self) -> Optional[SubBlockRecord]:
        """
        Return the peak of the blockchain
        """
        if self.peak_sub_height is None:
            return None
        return self.sub_blocks[self.sub_height_to_hash[self.peak_sub_height]]

    async def get_full_peak(self) -> Optional[HeaderBlock]:
        """ Return a peak transaction block"""
        if self.peak_sub_height is None:
            return None
        curr: Optional[SubBlockRecord] = self.sub_blocks[self.sub_height_to_hash[self.peak_sub_height]]
        while curr is not None and not curr.is_block:
            curr = self.sub_blocks.get(curr.prev_hash, None)
        if curr is None:
            return None
        block = await self.block_store.get_header_block(curr.header_hash)
        assert block is not None
        return block

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

    async def get_full_block(self, header_hash: bytes32) -> Optional[HeaderBlock]:
        return await self.block_store.get_header_block(header_hash)

    async def receive_block(
        self,
        block_record: HeaderBlockRecord,
        pre_validated: bool = False,
    ) -> Tuple[ReceiveBlockResult, Optional[Err], Optional[uint32]]:
        """
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        Returns a header if block is added to head. Returns an error if the block is
        invalid. Also returns the fork height, in the case of a new peak.
        """
        block = block_record.header
        genesis: bool = block.sub_block_height == 0

        if block.header_hash in self.sub_blocks:
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None, None

        if block.prev_header_hash not in self.sub_blocks and not genesis:
            return (
                ReceiveBlockResult.DISCONNECTED_BLOCK,
                Err.INVALID_PREV_BLOCK_HASH,
                None,
            )

        if block.sub_block_height == 0:
            prev_sb: Optional[SubBlockRecord] = None
        else:
            prev_sb = self.sub_blocks[block.prev_header_hash]
        sub_slot_iters, difficulty = get_sub_slot_iters_and_difficulty(
            self.constants, block, self.sub_height_to_hash, prev_sb, self.sub_blocks
        )
        required_iters, error = validate_finished_header_block(
            self.constants, self.sub_blocks, block, False, difficulty, sub_slot_iters
        )

        if error is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error.code, None
        assert required_iters is not None

        sub_block = block_to_sub_block_record(
            self.constants,
            self.sub_blocks,
            self.sub_height_to_hash,
            required_iters,
            None,
            block,
        )

        # Always add the block to the database

        await self.block_store.add_block_record(block_record, sub_block)
        self.sub_blocks[sub_block.header_hash] = sub_block

        fork_height: Optional[uint32] = await self._reconsider_peak(sub_block, genesis)
        if fork_height is not None:
            self.log.info(f"💰💰💰 Updated peak to sub height {sub_block.sub_block_height}, weight {sub_block.weight}, ")
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
                block: Optional[HeaderBlockRecord] = await self.block_store.get_header_block_record(
                    sub_block.header_hash
                )
                assert block is not None
                self.sub_height_to_hash[uint32(0)] = block.header_hash
                for removed in block.removals:
                    self.log.info(f"Removed: {removed.name()}")
                await self.coins_of_interest_received(
                    block.removals, block.additions, block.height, block.sub_block_height
                )
                self.peak_sub_height = uint32(0)
                return uint32(0)
            return None

        assert peak is not None
        if sub_block.weight > peak.weight:
            # Find the fork. if the block is just being appended, it will return the peak
            # If no blocks in common, returns -1, and reverts all blocks
            fork_h: int = find_fork_point_in_chain(self.sub_blocks, sub_block, peak)

            # Rollback to fork
            # TODO(straya): reorg coins based on height not sub-block height
            if fork_h == -1:
                await self.reorg_rollback(-1)
            else:
                fork_hash = self.sub_height_to_hash[uint32(fork_h)]
                fork_block = self.sub_blocks[fork_hash]
                await self.reorg_rollback(fork_block.sub_block_height)

            # Rollback sub_epoch_summaries
            heights_to_delete = []
            for ses_included_height in self.sub_epoch_summaries.keys():
                if ses_included_height > fork_h:
                    heights_to_delete.append(ses_included_height)
            for height in heights_to_delete:
                del self.sub_epoch_summaries[height]

            # Collect all blocks from fork point to new peak
            blocks_to_add: List[Tuple[HeaderBlockRecord, SubBlockRecord]] = []
            curr = sub_block.header_hash
            while fork_h < 0 or curr != self.sub_height_to_hash[uint32(fork_h)]:
                fetched_block: Optional[HeaderBlockRecord] = await self.block_store.get_header_block_record(curr)
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
                    await self.coins_of_interest_received(
                        fetched_block.removals,
                        fetched_block.additions,
                        fetched_block.height,
                        fetched_block.sub_block_height,
                    )
                if fetched_sub_block.sub_epoch_summary_included is not None:
                    self.sub_epoch_summaries[
                        fetched_sub_block.sub_block_height
                    ] = fetched_sub_block.sub_epoch_summary_included

            # Changes the peak to be the new peak
            await self.block_store.set_peak(sub_block.header_hash)
            self.peak_sub_height = sub_block.sub_block_height
            return uint32(min(fork_h, 0))

        # This is not a heavier block than the heaviest we have seen, so we don't change the coin set
        return None

    def get_next_difficulty(self, header_hash: bytes32, new_slot: bool) -> uint64:
        assert header_hash in self.sub_blocks
        curr = self.sub_blocks[header_hash]
        if curr.height <= 2:
            return self.constants.DIFFICULTY_STARTING
        return get_next_difficulty(
            self.constants,
            self.sub_blocks,
            self.sub_height_to_hash,
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
        if curr.height <= 2:
            return self.constants.SUB_SLOT_ITERS_STARTING
        return get_next_sub_slot_iters(
            self.constants,
            self.sub_blocks,
            self.sub_height_to_hash,
            header_hash,
            curr.height,
            curr.sub_slot_iters,
            curr.deficit,
            new_slot,
            curr.sp_total_iters(self.constants),
        )

    async def get_sp_and_ip_sub_slots(
        self, header_hash: bytes32
    ) -> Optional[Tuple[Optional[EndOfSubSlotBundle], Optional[EndOfSubSlotBundle]]]:
        block: Optional[HeaderBlock] = await self.block_store.get_header_block(header_hash)
        if block is None:
            return None
        is_overflow = self.sub_blocks[block.header_hash].overflow

        curr: Optional[HeaderBlock] = block
        assert curr is not None
        while len(curr.finished_sub_slots) == 0 and curr.height > 0:
            curr = await self.block_store.get_header_block(curr.prev_header_hash)
            assert curr is not None

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

        curr = await self.block_store.get_header_block(curr.prev_header_hash)
        assert curr is not None
        while len(curr.finished_sub_slots) == 0 and curr.height > 0:
            curr = await self.block_store.get_header_block(curr.prev_header_hash)
            assert curr is not None

        if len(curr.finished_sub_slots) == 0:
            return None, ip_sub_slot
        return curr.finished_sub_slots[-1], ip_sub_slot
