import asyncio
import dataclasses
import logging
import multiprocessing
from concurrent.futures.process import ProcessPoolExecutor
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Union

from chia.consensus.block_body_validation import validate_block_body
from chia.consensus.block_header_validation import validate_finished_header_block, validate_unfinished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.find_fork_point import find_fork_point_in_chain
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.multiprocess_validation import PreValidationResult, pre_validate_blocks_multiprocessing
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.types.blockchain_format.vdf import VDFInfo
from chia.types.coin_record import CoinRecord
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.full_block import FullBlock
from chia.types.generator_types import BlockGenerator, GeneratorArg
from chia.types.header_block import HeaderBlock
from chia.types.unfinished_block import UnfinishedBlock
from chia.types.unfinished_header_block import UnfinishedHeaderBlock
from chia.types.weight_proof import SubEpochChallengeSegment
from chia.util.errors import Err
from chia.util.generator_tools import get_block_header, tx_removals_and_additions
from chia.util.ints import uint16, uint32, uint64, uint128
from chia.util.streamable import recurse_jsonify

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


class Blockchain(BlockchainInterface):
    constants: ConsensusConstants
    constants_json: Dict

    # peak of the blockchain
    _peak_height: Optional[uint32]
    # All blocks in peak path are guaranteed to be included, can include orphan blocks
    __block_records: Dict[bytes32, BlockRecord]
    # all hashes of blocks in block_record by height, used for garbage collection
    __heights_in_cache: Dict[uint32, Set[bytes32]]
    # Defines the path from genesis to the peak, no orphan blocks
    __height_to_hash: Dict[uint32, bytes32]
    # All sub-epoch summaries that have been included in the blockchain from the beginning until and including the peak
    # (height_included, SubEpochSummary). Note: ONLY for the blocks in the path to the peak
    __sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}
    # Unspent Store
    coin_store: CoinStore
    # Store
    block_store: BlockStore
    # Used to verify blocks in parallel
    pool: ProcessPoolExecutor
    # Set holding seen compact proofs, in order to avoid duplicates.
    _seen_compact_proofs: Set[Tuple[VDFInfo, uint32]]

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
        Initializes a blockchain with the BlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = Blockchain()
        self.lock = asyncio.Lock()  # External lock handled by full node
        cpu_count = multiprocessing.cpu_count()
        if cpu_count > 61:
            cpu_count = 61  # Windows Server 2016 has an issue https://bugs.python.org/issue26903
        num_workers = max(cpu_count - 2, 1)
        self.pool = ProcessPoolExecutor(max_workers=num_workers)
        log.info(f"Started {num_workers} processes for block validation")

        self.constants = consensus_constants
        self.coin_store = coin_store
        self.block_store = block_store
        self.constants_json = recurse_jsonify(dataclasses.asdict(self.constants))
        self._shut_down = False
        await self._load_chain_from_store()
        self._seen_compact_proofs = set()
        return self

    def shut_down(self):
        self._shut_down = True
        self.pool.shutdown(wait=True)

    async def _load_chain_from_store(self) -> None:
        """
        Initializes the state of the Blockchain class from the database.
        """
        height_to_hash, sub_epoch_summaries = await self.block_store.get_peak_height_dicts()
        self.__height_to_hash = height_to_hash
        self.__sub_epoch_summaries = sub_epoch_summaries
        self.__block_records = {}
        self.__heights_in_cache = {}
        block_records, peak = await self.block_store.get_block_records_close_to_peak(self.constants.BLOCKS_CACHE_SIZE)
        for block in block_records.values():
            self.add_block_record(block)

        if len(block_records) == 0:
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

    async def get_full_peak(self) -> Optional[FullBlock]:
        if self._peak_height is None:
            return None
        """ Return list of FullBlocks that are peaks"""
        block = await self.block_store.get_full_block(self.height_to_hash(self._peak_height))
        assert block is not None
        return block

    async def get_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return await self.block_store.get_full_block(header_hash)

    async def receive_block(
        self,
        block: FullBlock,
        pre_validation_result: Optional[PreValidationResult] = None,
        fork_point_with_peak: Optional[uint32] = None,
        summaries_to_check: List[SubEpochSummary] = None,  # passed only on long sync
    ) -> Tuple[ReceiveBlockResult, Optional[Err], Optional[uint32]]:
        """
        This method must be called under the blockchain lock
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        Returns a header if block is added to head. Returns an error if the block is
        invalid. Also returns the fork height, in the case of a new peak.
        """
        genesis: bool = block.height == 0

        if self.contains_block(block.header_hash):
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None, None

        if not self.contains_block(block.prev_header_hash) and not genesis:
            return (
                ReceiveBlockResult.DISCONNECTED_BLOCK,
                Err.INVALID_PREV_BLOCK_HASH,
                None,
            )

        if not genesis and (self.block_record(block.prev_header_hash).height + 1) != block.height:
            return ReceiveBlockResult.INVALID_BLOCK, Err.INVALID_HEIGHT, None

        npc_result: Optional[NPCResult] = None
        if pre_validation_result is None:
            if block.height == 0:
                prev_b: Optional[BlockRecord] = None
            else:
                prev_b = self.block_record(block.prev_header_hash)
            sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
                self.constants, len(block.finished_sub_slots) > 0, prev_b, self
            )

            if block.is_transaction_block():
                if block.transactions_generator is not None:
                    try:
                        block_generator: Optional[BlockGenerator] = await self.get_block_generator(block)
                    except ValueError:
                        return ReceiveBlockResult.INVALID_BLOCK, Err.GENERATOR_REF_HAS_NO_GENERATOR, None
                    assert block_generator is not None and block.transactions_info is not None
                    npc_result = get_name_puzzle_conditions(
                        block_generator, min(self.constants.MAX_BLOCK_COST_CLVM, block.transactions_info.cost), False
                    )
                    removals, tx_additions = tx_removals_and_additions(npc_result.npc_list)
                else:
                    removals, tx_additions = [], []
                header_block = get_block_header(block, tx_additions, removals)
            else:
                npc_result = None
                header_block = get_block_header(block, [], [])

            required_iters, error = validate_finished_header_block(
                self.constants,
                self,
                header_block,
                False,
                difficulty,
                sub_slot_iters,
            )

            if error is not None:
                return ReceiveBlockResult.INVALID_BLOCK, error.code, None
        else:
            npc_result = pre_validation_result.npc_result
            required_iters = pre_validation_result.required_iters
            assert pre_validation_result.error is None
        assert required_iters is not None
        error_code, _ = await validate_block_body(
            self.constants,
            self,
            self.block_store,
            self.coin_store,
            self.get_peak(),
            block,
            block.height,
            npc_result,
            fork_point_with_peak,
            self.get_block_generator,
        )
        if error_code is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error_code, None

        block_record = block_to_block_record(
            self.constants,
            self,
            required_iters,
            block,
            None,
        )
        # Always add the block to the database
        async with self.block_store.db_wrapper.lock:
            try:
                # Perform the DB operations to update the state, and rollback if something goes wrong
                await self.block_store.db_wrapper.begin_transaction()
                await self.block_store.add_full_block(block, block_record)
                fork_height, peak_height, records = await self._reconsider_peak(
                    block_record, genesis, fork_point_with_peak, npc_result
                )
                await self.block_store.db_wrapper.commit_transaction()

                # Then update the memory cache. It is important that this task is not cancelled and does not throw
                self.add_block_record(block_record)
                for fetched_block_record in records:
                    self.__height_to_hash[fetched_block_record.height] = fetched_block_record.header_hash
                    if fetched_block_record.sub_epoch_summary_included is not None:
                        self.__sub_epoch_summaries[
                            fetched_block_record.height
                        ] = fetched_block_record.sub_epoch_summary_included
                if peak_height is not None:
                    self._peak_height = peak_height
                self.block_store.cache_block(block)
            except BaseException:
                await self.block_store.db_wrapper.rollback_transaction()
                raise
        if fork_height is not None:
            return ReceiveBlockResult.NEW_PEAK, None, fork_height
        else:
            return ReceiveBlockResult.ADDED_AS_ORPHAN, None, None

    async def _reconsider_peak(
        self,
        block_record: BlockRecord,
        genesis: bool,
        fork_point_with_peak: Optional[uint32],
        npc_result: Optional[NPCResult],
    ) -> Tuple[Optional[uint32], Optional[uint32], List[BlockRecord]]:
        """
        When a new block is added, this is called, to check if the new block is the new peak of the chain.
        This also handles reorgs by reverting blocks which are not in the heaviest chain.
        It returns the height of the fork between the previous chain and the new chain, or returns
        None if there was no update to the heaviest chain.
        """
        peak = self.get_peak()
        if genesis:
            if peak is None:
                block: Optional[FullBlock] = await self.block_store.get_full_block(block_record.header_hash)
                assert block is not None

                if npc_result is not None:
                    tx_removals, tx_additions = tx_removals_and_additions(npc_result.npc_list)
                else:
                    tx_removals, tx_additions = [], []
                await self.coin_store.new_block(block, tx_additions, tx_removals)
                await self.block_store.set_peak(block.header_hash)
                return uint32(0), uint32(0), [block_record]
            return None, None, []

        assert peak is not None
        if block_record.weight > peak.weight:
            # Find the fork. if the block is just being appended, it will return the peak
            # If no blocks in common, returns -1, and reverts all blocks
            if block_record.prev_hash == peak.header_hash:
                fork_height: int = peak.height
            elif fork_point_with_peak is not None:
                fork_height = fork_point_with_peak
            else:
                fork_height = find_fork_point_in_chain(self, block_record, peak)

            if block_record.prev_hash != peak.header_hash:
                await self.coin_store.rollback_to_block(fork_height)
            # Rollback sub_epoch_summaries
            heights_to_delete = []
            for ses_included_height in self.__sub_epoch_summaries.keys():
                if ses_included_height > fork_height:
                    heights_to_delete.append(ses_included_height)
            for height in heights_to_delete:
                log.info(f"delete ses at height {height}")
                del self.__sub_epoch_summaries[height]

            # Collect all blocks from fork point to new peak
            blocks_to_add: List[Tuple[FullBlock, BlockRecord]] = []
            curr = block_record.header_hash

            while fork_height < 0 or curr != self.height_to_hash(uint32(fork_height)):
                fetched_full_block: Optional[FullBlock] = await self.block_store.get_full_block(curr)
                fetched_block_record: Optional[BlockRecord] = await self.block_store.get_block_record(curr)
                assert fetched_full_block is not None
                assert fetched_block_record is not None
                blocks_to_add.append((fetched_full_block, fetched_block_record))
                if fetched_full_block.height == 0:
                    # Doing a full reorg, starting at height 0
                    break
                curr = fetched_block_record.prev_hash

            records_to_add = []
            for fetched_full_block, fetched_block_record in reversed(blocks_to_add):
                records_to_add.append(fetched_block_record)
                if fetched_block_record.is_transaction_block:
                    if fetched_block_record.header_hash == block_record.header_hash:
                        tx_removals, tx_additions = await self.get_tx_removals_and_additions(
                            fetched_full_block, npc_result
                        )
                    else:
                        tx_removals, tx_additions = await self.get_tx_removals_and_additions(fetched_full_block, None)
                    await self.coin_store.new_block(fetched_full_block, tx_additions, tx_removals)

            # Changes the peak to be the new peak
            await self.block_store.set_peak(block_record.header_hash)
            return uint32(max(fork_height, 0)), block_record.height, records_to_add

        # This is not a heavier block than the heaviest we have seen, so we don't change the coin set
        return None, None, []

    async def get_tx_removals_and_additions(
        self, block: FullBlock, npc_result: Optional[NPCResult] = None
    ) -> Tuple[List[bytes32], List[Coin]]:
        if block.is_transaction_block():
            if block.transactions_generator is not None:
                if npc_result is None:
                    block_generator: Optional[BlockGenerator] = await self.get_block_generator(block)
                    assert block_generator is not None
                    npc_result = get_name_puzzle_conditions(block_generator, self.constants.MAX_BLOCK_COST_CLVM, False)
                tx_removals, tx_additions = tx_removals_and_additions(npc_result.npc_list)
                return tx_removals, tx_additions
            else:
                return [], []
        else:
            return [], []

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

    async def get_sp_and_ip_sub_slots(
        self, header_hash: bytes32
    ) -> Optional[Tuple[Optional[EndOfSubSlotBundle], Optional[EndOfSubSlotBundle]]]:
        block: Optional[FullBlock] = await self.block_store.get_full_block(header_hash)
        if block is None:
            return None
        curr_br: BlockRecord = self.block_record(block.header_hash)
        is_overflow = curr_br.overflow

        curr: Optional[FullBlock] = block
        assert curr is not None
        while True:
            if curr_br.first_in_sub_slot:
                curr = await self.block_store.get_full_block(curr_br.header_hash)
                assert curr is not None
                break
            if curr_br.height == 0:
                break
            curr_br = self.block_record(curr_br.prev_hash)

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
            assert curr.height == 0
            prev_curr = curr
            prev_curr_br = self.block_record(curr.header_hash)
        else:
            prev_curr_br = self.block_record(curr.prev_header_hash)
        assert prev_curr_br is not None
        while prev_curr_br.height > 0:
            if prev_curr_br.first_in_sub_slot:
                prev_curr = await self.block_store.get_full_block(prev_curr_br.header_hash)
                assert prev_curr is not None
                break
            prev_curr_br = self.block_record(prev_curr_br.prev_hash)

        if len(prev_curr.finished_sub_slots) == 0:
            return None, ip_sub_slot
        return prev_curr.finished_sub_slots[-1], ip_sub_slot

    def get_recent_reward_challenges(self) -> List[Tuple[bytes32, uint128]]:
        peak = self.get_peak()
        if peak is None:
            return []
        recent_rc: List[Tuple[bytes32, uint128]] = []
        curr: Optional[BlockRecord] = peak
        while curr is not None and len(recent_rc) < 2 * self.constants.MAX_SUB_SLOT_BLOCKS:
            if curr != peak:
                recent_rc.append((curr.reward_infusion_new_challenge, curr.total_iters))
            if curr.first_in_sub_slot:
                assert curr.finished_reward_slot_hashes is not None
                sub_slot_total_iters = curr.ip_sub_slot_total_iters(self.constants)
                # Start from the most recent
                for rc in reversed(curr.finished_reward_slot_hashes):
                    recent_rc.append((rc, sub_slot_total_iters))
                    sub_slot_total_iters = uint128(sub_slot_total_iters - curr.sub_slot_iters)
            curr = self.try_block_record(curr.prev_hash)
        return list(reversed(recent_rc))

    async def validate_unfinished_block(
        self, block: UnfinishedBlock, skip_overflow_ss_validation=True
    ) -> PreValidationResult:
        if (
            not self.contains_block(block.prev_header_hash)
            and not block.prev_header_hash == self.constants.GENESIS_CHALLENGE
        ):
            return PreValidationResult(uint16(Err.INVALID_PREV_BLOCK_HASH.value), None, None)

        unfinished_header_block = UnfinishedHeaderBlock(
            block.finished_sub_slots,
            block.reward_chain_block,
            block.challenge_chain_sp_proof,
            block.reward_chain_sp_proof,
            block.foliage,
            block.foliage_transaction_block,
            b"",
        )
        prev_b = self.try_block_record(unfinished_header_block.prev_header_hash)
        sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
            self.constants, len(unfinished_header_block.finished_sub_slots) > 0, prev_b, self
        )
        required_iters, error = validate_unfinished_header_block(
            self.constants,
            self,
            unfinished_header_block,
            False,
            difficulty,
            sub_slot_iters,
            skip_overflow_ss_validation,
        )

        if error is not None:
            return PreValidationResult(uint16(error.code.value), None, None)

        prev_height = (
            -1
            if block.prev_header_hash == self.constants.GENESIS_CHALLENGE
            else self.block_record(block.prev_header_hash).height
        )

        npc_result = None
        if block.transactions_generator is not None:
            assert block.transactions_info is not None
            try:
                block_generator: Optional[BlockGenerator] = await self.get_block_generator(block)
            except ValueError:
                return PreValidationResult(uint16(Err.GENERATOR_REF_HAS_NO_GENERATOR.value), None, None)
            if block_generator is None:
                return PreValidationResult(uint16(Err.GENERATOR_REF_HAS_NO_GENERATOR.value), None, None)
            npc_result = get_name_puzzle_conditions(
                block_generator, min(self.constants.MAX_BLOCK_COST_CLVM, block.transactions_info.cost), False
            )
        error_code, cost_result = await validate_block_body(
            self.constants,
            self,
            self.block_store,
            self.coin_store,
            self.get_peak(),
            block,
            uint32(prev_height + 1),
            npc_result,
            None,
            self.get_block_generator,
        )

        if error_code is not None:
            return PreValidationResult(uint16(error_code.value), None, None)

        return PreValidationResult(None, required_iters, cost_result)

    async def pre_validate_blocks_multiprocessing(
        self, blocks: List[FullBlock], npc_results: Dict[uint32, NPCResult], batch_size: int = 4
    ) -> Optional[List[PreValidationResult]]:
        return await pre_validate_blocks_multiprocessing(
            self.constants,
            self.constants_json,
            self,
            blocks,
            self.pool,
            True,
            npc_results,
            self.get_block_generator,
            batch_size,
        )

    def contains_block(self, header_hash: bytes32) -> bool:
        """
        True if we have already added this block to the chain. This may return false for orphan blocks
        that we have added but no longer keep in memory.
        """
        return header_hash in self.__block_records

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self.__block_records[header_hash]

    def height_to_block_record(self, height: uint32) -> BlockRecord:
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
        block_records = await self.block_store.get_block_records_in_range(
            max(fork_point - self.constants.BLOCKS_CACHE_SIZE, uint32(0)), fork_point
        )
        for block_record in block_records.values():
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
                del self.__block_records[header_hash]  # remove from blocks
            del self.__heights_in_cache[uint32(height)]  # remove height from heights in cache

            height = height - 1
            blocks_to_remove = self.__heights_in_cache.get(uint32(height), None)

    def clean_block_records(self):
        """
        Cleans the cache so that we only maintain relevant blocks. This removes
        block records that have height < peak - BLOCKS_CACHE_SIZE.
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
        hashes = []
        for height in range(start, stop + 1):
            if self.contains_height(uint32(height)):
                header_hash: bytes32 = self.height_to_hash(uint32(height))
                hashes.append(header_hash)

        blocks: List[FullBlock] = []
        for hash in hashes.copy():
            block = self.block_store.block_cache.get(hash)
            if block is not None:
                blocks.append(block)
                hashes.remove(hash)
        blocks_on_disk: List[FullBlock] = await self.block_store.get_blocks_by_hash(hashes)
        blocks.extend(blocks_on_disk)
        header_blocks: Dict[bytes32, HeaderBlock] = {}

        for block in blocks:
            if self.height_to_hash(block.height) != block.header_hash:
                raise ValueError(f"Block at {block.header_hash} is no longer in the blockchain (it's in a fork)")
            tx_additions: List[CoinRecord] = [
                c for c in (await self.coin_store.get_coins_added_at_height(block.height)) if not c.coinbase
            ]
            removed: List[CoinRecord] = await self.coin_store.get_coins_removed_at_height(block.height)
            header = get_block_header(
                block, [record.coin for record in tx_additions], [record.coin.name() for record in removed]
            )
            header_blocks[header.header_hash] = header

        return header_blocks

    async def get_header_block_by_height(self, height: int, header_hash: bytes32) -> Optional[HeaderBlock]:
        header_dict: Dict[bytes32, HeaderBlock] = await self.get_header_blocks_in_range(height, height)
        if len(header_dict) == 0:
            return None
        if header_hash not in header_dict:
            return None
        return header_dict[header_hash]

    async def get_block_records_at(self, heights: List[uint32]) -> List[BlockRecord]:
        """
        gets block records by height (only blocks that are part of the chain)
        """
        hashes = []
        for height in heights:
            hashes.append(self.height_to_hash(height))
        return await self.block_store.get_block_records_by_hash(hashes)

    async def get_block_record_from_db(self, header_hash: bytes32) -> Optional[BlockRecord]:
        if header_hash in self.__block_records:
            return self.__block_records[header_hash]
        return await self.block_store.get_block_record(header_hash)

    def remove_block_record(self, header_hash: bytes32):
        sbr = self.block_record(header_hash)
        del self.__block_records[header_hash]
        self.__heights_in_cache[sbr.height].remove(header_hash)

    def add_block_record(self, block_record: BlockRecord):
        """
        Adds a block record to the cache.
        """

        self.__block_records[block_record.header_hash] = block_record
        if block_record.height not in self.__heights_in_cache.keys():
            self.__heights_in_cache[block_record.height] = set()
        self.__heights_in_cache[block_record.height].add(block_record.header_hash)

    async def persist_sub_epoch_challenge_segments(
        self, ses_block_hash: bytes32, segments: List[SubEpochChallengeSegment]
    ):
        return await self.block_store.persist_sub_epoch_challenge_segments(ses_block_hash, segments)

    async def get_sub_epoch_challenge_segments(
        self,
        ses_block_hash: bytes32,
    ) -> Optional[List[SubEpochChallengeSegment]]:
        segments: Optional[List[SubEpochChallengeSegment]] = await self.block_store.get_sub_epoch_challenge_segments(
            ses_block_hash
        )
        if segments is None:
            return None
        return segments

    # Returns 'True' if the info is already in the set, otherwise returns 'False' and stores it.
    def seen_compact_proofs(self, vdf_info: VDFInfo, height: uint32) -> bool:
        pot_tuple = (vdf_info, height)
        if pot_tuple in self._seen_compact_proofs:
            return True
        # Periodically cleanup to keep size small. TODO: make this smarter, like FIFO.
        if len(self._seen_compact_proofs) > 10000:
            self._seen_compact_proofs.clear()
        self._seen_compact_proofs.add(pot_tuple)
        return False

    async def get_block_generator(
        self, block: Union[FullBlock, UnfinishedBlock], additional_blocks=None
    ) -> Optional[BlockGenerator]:
        if additional_blocks is None:
            additional_blocks = {}
        ref_list = block.transactions_generator_ref_list
        if block.transactions_generator is None:
            assert len(ref_list) == 0
            return None
        if len(ref_list) == 0:
            return BlockGenerator(block.transactions_generator, [])

        result: List[GeneratorArg] = []
        previous_block_hash = block.prev_header_hash
        if (
            self.try_block_record(previous_block_hash)
            and self.height_to_hash(self.block_record(previous_block_hash).height) == previous_block_hash
        ):
            # We are not in a reorg, no need to look up alternate header hashes (we can get them from height_to_hash)
            for ref_height in block.transactions_generator_ref_list:
                header_hash = self.height_to_hash(ref_height)
                ref_block = await self.get_full_block(header_hash)
                assert ref_block is not None
                if ref_block.transactions_generator is None:
                    raise ValueError(Err.GENERATOR_REF_HAS_NO_GENERATOR)
                result.append(GeneratorArg(ref_block.height, ref_block.transactions_generator))
        else:
            # First tries to find the blocks in additional_blocks
            reorg_chain: Dict[uint32, FullBlock] = {}
            curr: Union[FullBlock, UnfinishedBlock] = block
            additional_height_dict = {}
            while curr.prev_header_hash in additional_blocks:
                prev: FullBlock = additional_blocks[curr.prev_header_hash]
                additional_height_dict[prev.height] = prev
                if isinstance(curr, FullBlock):
                    assert curr.height == prev.height + 1
                reorg_chain[prev.height] = prev
                curr = prev

            peak: Optional[BlockRecord] = self.get_peak()
            if self.contains_block(curr.prev_header_hash) and peak is not None:
                # Then we look up blocks up to fork point one at a time, backtracking
                previous_block_hash = curr.prev_header_hash
                prev_block_record = await self.block_store.get_block_record(previous_block_hash)
                prev_block = await self.block_store.get_full_block(previous_block_hash)
                assert prev_block is not None
                assert prev_block_record is not None
                fork = find_fork_point_in_chain(self, peak, prev_block_record)
                curr_2: Optional[FullBlock] = prev_block
                assert curr_2 is not None and isinstance(curr_2, FullBlock)
                reorg_chain[curr_2.height] = curr_2
                while curr_2.height > fork and curr_2.height > 0:
                    curr_2 = await self.block_store.get_full_block(curr_2.prev_header_hash)
                    assert curr_2 is not None
                    reorg_chain[curr_2.height] = curr_2

            for ref_height in block.transactions_generator_ref_list:
                if ref_height in reorg_chain:
                    ref_block = reorg_chain[ref_height]
                    assert ref_block is not None
                    if ref_block.transactions_generator is None:
                        raise ValueError(Err.GENERATOR_REF_HAS_NO_GENERATOR)
                    result.append(GeneratorArg(ref_block.height, ref_block.transactions_generator))
                else:
                    if ref_height in additional_height_dict:
                        ref_block = additional_height_dict[ref_height]
                    else:
                        header_hash = self.height_to_hash(ref_height)
                        ref_block = await self.get_full_block(header_hash)
                    assert ref_block is not None
                    if ref_block.transactions_generator is None:
                        raise ValueError(Err.GENERATOR_REF_HAS_NO_GENERATOR)
                    result.append(GeneratorArg(ref_block.height, ref_block.transactions_generator))
        assert len(result) == len(ref_list)
        return BlockGenerator(block.transactions_generator, result)
