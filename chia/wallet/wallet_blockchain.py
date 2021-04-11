import asyncio
import dataclasses
import logging
import multiprocessing
from concurrent.futures.process import ProcessPoolExecutor
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from chia.consensus.block_header_validation import validate_finished_header_block, validate_unfinished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.find_fork_point import find_fork_point_in_chain
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.multiprocess_validation import PreValidationResult, pre_validate_blocks_multiprocessing
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.header_block import HeaderBlock
from chia.types.unfinished_block import UnfinishedBlock
from chia.types.unfinished_header_block import UnfinishedHeaderBlock
from chia.util.errors import Err, ValidationError
from chia.util.ints import uint32, uint64
from chia.util.streamable import recurse_jsonify
from chia.wallet.block_record import HeaderBlockRecord
from chia.wallet.wallet_block_store import WalletBlockStore
from chia.wallet.wallet_coin_store import WalletCoinStore

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


class WalletBlockchain(BlockchainInterface):
    constants: ConsensusConstants
    constants_json: Dict
    # peak of the blockchain
    _peak_height: Optional[uint32]
    # All blocks in peak path are guaranteed to be included, can include orphan blocks
    __block_records: Dict[bytes32, BlockRecord]
    # Defines the path from genesis to the peak, no orphan blocks
    __height_to_hash: Dict[uint32, bytes32]
    # all hashes of blocks in block_record by height, used for garbage collection
    __heights_in_cache: Dict[uint32, Set[bytes32]]
    # All sub-epoch summaries that have been included in the blockchain from the beginning until and including the peak
    # (height_included, SubEpochSummary). Note: ONLY for the blocks in the path to the peak
    __sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}
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
        Initializes a blockchain with the BlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = WalletBlockchain()
        self.lock = asyncio.Lock()  # External lock handled by full node
        cpu_count = multiprocessing.cpu_count()
        if cpu_count > 61:
            cpu_count = 61  # Windows Server 2016 has an issue https://bugs.python.org/issue26903
        num_workers = max(cpu_count - 2, 1)
        self.pool = ProcessPoolExecutor(max_workers=num_workers)
        log.info(f"Started {num_workers} processes for block validation")
        self.constants = consensus_constants
        self.constants_json = recurse_jsonify(dataclasses.asdict(self.constants))
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
        height_to_hash, sub_epoch_summaries = await self.block_store.get_peak_heights_dicts()
        self.__height_to_hash = height_to_hash
        self.__sub_epoch_summaries = sub_epoch_summaries
        self.__block_records = {}
        self.__heights_in_cache = {}
        blocks, peak = await self.block_store.get_block_records_close_to_peak(self.constants.BLOCKS_CACHE_SIZE)
        for block_record in blocks.values():
            self.add_block_record(block_record)

        if len(blocks) == 0:
            assert peak is None
            self._peak_height = None
            return

        assert peak is not None
        self._peak_height = self.block_record(peak).height
        assert len(self.__height_to_hash) == self._peak_height + 1

    def get_peak(self) -> Optional[BlockRecord]:
        """
        Return the peak of the blockchain
        """
        if self._peak_height is None:
            return None
        return self.height_to_block_record(self._peak_height)

    def is_child_of_peak(self, block: UnfinishedBlock) -> bool:
        """
        True iff the block is the direct ancestor of the peak
        """
        peak = self.get_peak()
        if peak is None:
            return False

        return block.prev_header_hash == peak.header_hash

    async def get_full_block(self, header_hash: bytes32) -> Optional[HeaderBlock]:
        return await self.block_store.get_header_block(header_hash)

    async def receive_block(
        self,
        header_block_record: HeaderBlockRecord,
        pre_validation_result: Optional[PreValidationResult] = None,
        trusted: bool = False,
        fork_point_with_peak: Optional[uint32] = None,
    ) -> Tuple[ReceiveBlockResult, Optional[Err], Optional[uint32]]:
        """
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        Returns a header if block is added to head. Returns an error if the block is
        invalid. Also returns the fork height, in the case of a new peak.
        """

        block = header_block_record.header
        genesis: bool = block.height == 0

        if self.contains_block(block.header_hash):
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None, None

        if not self.contains_block(block.prev_header_hash) and not genesis:
            return (
                ReceiveBlockResult.DISCONNECTED_BLOCK,
                Err.INVALID_PREV_BLOCK_HASH,
                None,
            )

        if block.height == 0:
            prev_b: Optional[BlockRecord] = None
        else:
            prev_b = self.block_record(block.prev_header_hash)
        sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
            self.constants, len(block.finished_sub_slots) > 0, prev_b, self
        )

        if trusted is False and pre_validation_result is None:
            required_iters, error = validate_finished_header_block(
                self.constants, self, block, False, difficulty, sub_slot_iters
            )
        elif trusted:
            unfinished_header_block = UnfinishedHeaderBlock(
                block.finished_sub_slots,
                block.reward_chain_block.get_unfinished(),
                block.challenge_chain_sp_proof,
                block.reward_chain_sp_proof,
                block.foliage,
                block.foliage_transaction_block,
                block.transactions_filter,
            )

            required_iters, val_error = validate_unfinished_header_block(
                self.constants, self, unfinished_header_block, False, difficulty, sub_slot_iters, False, True
            )
            error = ValidationError(Err(val_error)) if val_error is not None else None
        else:
            assert pre_validation_result is not None
            required_iters = pre_validation_result.required_iters
            error = (
                ValidationError(Err(pre_validation_result.error)) if pre_validation_result.error is not None else None
            )

        if error is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error.code, None
        assert required_iters is not None

        block_record = block_to_block_record(
            self.constants,
            self,
            required_iters,
            None,
            block,
        )

        # Always add the block to the database
        async with self.block_store.db_wrapper.lock:
            try:
                await self.block_store.db_wrapper.begin_transaction()
                await self.block_store.add_block_record(header_block_record, block_record)
                self.add_block_record(block_record)
                self.clean_block_record(block_record.height - self.constants.BLOCKS_CACHE_SIZE)

                fork_height: Optional[uint32] = await self._reconsider_peak(block_record, genesis, fork_point_with_peak)
                await self.block_store.db_wrapper.commit_transaction()
            except BaseException as e:
                self.log.error(f"Error during db transaction: {e}")
                await self.block_store.db_wrapper.rollback_transaction()
                raise
        if fork_height is not None:
            self.log.info(f"💰 Updated wallet peak to height {block_record.height}, weight {block_record.weight}, ")
            return ReceiveBlockResult.NEW_PEAK, None, fork_height
        else:
            return ReceiveBlockResult.ADDED_AS_ORPHAN, None, None

    async def _reconsider_peak(
        self, block_record: BlockRecord, genesis: bool, fork_point_with_peak: Optional[uint32]
    ) -> Optional[uint32]:
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
                    block_record.header_hash
                )
                assert block is not None
                self.__height_to_hash[uint32(0)] = block.header_hash
                for removed in block.removals:
                    self.log.debug(f"Removed: {removed.name()}")
                await self.coins_of_interest_received(block.removals, block.additions, block.height)
                self._peak_height = uint32(0)
                return uint32(0)
            return None

        assert peak is not None
        if block_record.weight > peak.weight:
            # Find the fork. if the block is just being appended, it will return the peak
            # If no blocks in common, returns -1, and reverts all blocks
            if fork_point_with_peak is not None:
                fork_h: int = fork_point_with_peak
            else:
                fork_h = find_fork_point_in_chain(self, block_record, peak)

            # Rollback to fork
            self.log.debug(f"fork_h: {fork_h}, SB: {block_record.height}, peak: {peak.height}")
            await self.reorg_rollback(fork_h)

            # Rollback sub_epoch_summaries
            heights_to_delete = []
            for ses_included_height in self.__sub_epoch_summaries.keys():
                if ses_included_height > fork_h:
                    heights_to_delete.append(ses_included_height)
            for height in heights_to_delete:
                del self.__sub_epoch_summaries[height]

            # Collect all blocks from fork point to new peak
            blocks_to_add: List[Tuple[HeaderBlockRecord, BlockRecord]] = []
            curr = block_record.header_hash
            while fork_h < 0 or curr != self.height_to_hash(uint32(fork_h)):
                fetched_header_block: Optional[HeaderBlockRecord] = await self.block_store.get_header_block_record(curr)
                fetched_block_record: Optional[BlockRecord] = await self.block_store.get_block_record(curr)
                assert fetched_header_block is not None
                assert fetched_block_record is not None
                blocks_to_add.append((fetched_header_block, fetched_block_record))
                if fetched_header_block.height == 0:
                    # Doing a full reorg, starting at height 0
                    break
                curr = fetched_block_record.prev_hash

            for fetched_header_block, fetched_block_record in reversed(blocks_to_add):
                self.__height_to_hash[fetched_block_record.height] = fetched_block_record.header_hash
                if fetched_block_record.is_transaction_block:
                    await self.coins_of_interest_received(
                        fetched_header_block.removals,
                        fetched_header_block.additions,
                        fetched_header_block.height,
                    )
                if fetched_block_record.sub_epoch_summary_included is not None:
                    self.__sub_epoch_summaries[
                        fetched_block_record.height
                    ] = fetched_block_record.sub_epoch_summary_included

            # Changes the peak to be the new peak
            await self.block_store.set_peak(block_record.header_hash)
            self._peak_height = block_record.height
            return uint32(min(fork_h, 0))

        # This is not a heavier block than the heaviest we have seen, so we don't change the coin set
        return None

    def get_next_difficulty(self, header_hash: bytes32, new_slot: bool) -> uint64:
        assert self.contains_block(header_hash)
        curr = self.block_record(header_hash)
        if curr.height <= 2:
            return self.constants.DIFFICULTY_STARTING
        return get_next_sub_slot_iters_and_difficulty(self.constants, new_slot, curr, self)[1]

    def get_next_slot_iters(self, header_hash: bytes32, new_slot: bool) -> uint64:
        assert self.contains_block(header_hash)
        curr = self.block_record(header_hash)
        if curr.height <= 2:
            return self.constants.SUB_SLOT_ITERS_STARTING
        return get_next_sub_slot_iters_and_difficulty(self.constants, new_slot, curr, self)[0]

    async def pre_validate_blocks_multiprocessing(
        self,
        blocks: List[HeaderBlock],
    ) -> Optional[List[PreValidationResult]]:
        return await pre_validate_blocks_multiprocessing(
            self.constants, self.constants_json, self, blocks, self.pool, True, True
        )

    def contains_block(self, header_hash: bytes32) -> bool:
        """
        True if we have already added this block to the chain. This may return false for orphan blocks
        that we have added but no longer keep in memory.
        """
        return header_hash in self.__block_records

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self.__block_records[header_hash]

    def height_to_block_record(self, height: uint32, check_db=False) -> BlockRecord:
        header_hash = self.height_to_hash(height)
        return self.block_record(header_hash)

    def get_ses_heights(self) -> List[uint32]:
        return sorted(self.__sub_epoch_summaries.keys())

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return self.__sub_epoch_summaries[height]

    def height_to_hash(self, height: uint32) -> Optional[bytes32]:
        return self.__height_to_hash[height]

    def contains_height(self, height: uint32) -> bool:
        return height in self.__height_to_hash

    def get_peak_height(self) -> Optional[uint32]:
        return self._peak_height

    async def warmup(self, fork_point: uint32):
        """
        Loads blocks into the cache. The blocks loaded include all blocks from
        fork point - BLOCKS_CACHE_SIZE up to and including the fork_point.

        Args:
            fork_point: the last block height to load in the cache

        """

        if self._peak_height is None:
            return
        blocks = await self.block_store.get_block_records_in_range(
            fork_point - self.constants.BLOCKS_CACHE_SIZE, self._peak_height
        )
        for block_record in blocks.values():
            self.add_block_record(block_record)

    def clean_block_record(self, height: int):
        """
        Clears all block records in the cache which have block_record < height.
        Args:
            height: Minimum height that we need to keep in the cache
        """

        if height < 0:
            return
        blocks_to_remove = self.__heights_in_cache.get(uint32(height), None)
        while blocks_to_remove is not None and height >= 0:
            for header_hash in blocks_to_remove:
                del self.__block_records[header_hash]
            del self.__heights_in_cache[uint32(height)]  # remove height from heights in cache

            height -= 1
            blocks_to_remove = self.__heights_in_cache.get(uint32(height), None)

    def clean_block_records(self):
        """
        Cleans the cache so that we only maintain relevant blocks.
        This removes block records that have height < peak - BLOCKS_CACHE_SIZE.
        These blocks are necessary for calculating future difficulty adjustments.
        """

        if len(self.__block_records) < self.constants.BLOCKS_CACHE_SIZE:
            return

        peak = self.get_peak()
        assert peak is not None
        if peak.height - self.constants.BLOCKS_CACHE_SIZE < 0:
            return
        self.clean_block_record(peak.height - self.constants.BLOCKS_CACHE_SIZE)

    async def get_block_records_in_range(self, start: int, stop: int) -> Dict[bytes32, BlockRecord]:
        return await self.block_store.get_block_records_in_range(start, stop)

    async def get_header_blocks_in_range(self, start: int, stop: int) -> Dict[bytes32, HeaderBlock]:
        return await self.block_store.get_header_blocks_in_range(start, stop)

    async def get_block_record_from_db(self, header_hash: bytes32) -> Optional[BlockRecord]:
        if header_hash in self.__block_records:
            return self.__block_records[header_hash]
        return await self.block_store.get_block_record(header_hash)

    def remove_block_record(self, header_hash: bytes32):
        sbr = self.block_record(header_hash)
        del self.__block_records[header_hash]
        self.__heights_in_cache[sbr.height].remove(header_hash)

    def add_block_record(self, block_record: BlockRecord):
        self.__block_records[block_record.header_hash] = block_record
        if block_record.height not in self.__heights_in_cache.keys():
            self.__heights_in_cache[block_record.height] = set()
        self.__heights_in_cache[block_record.height].add(block_record.header_hash)

    async def get_header_block(self, header_hash: bytes32) -> Optional[HeaderBlock]:
        return await self.block_store.get_header_block(header_hash)
