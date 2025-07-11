from __future__ import annotations

import asyncio
import dataclasses
import enum
import logging
import traceback
from concurrent.futures import Executor, ThreadPoolExecutor
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Optional, cast

from chia_rs import (
    BlockRecord,
    ConsensusConstants,
    EndOfSubSlotBundle,
    FullBlock,
    HeaderBlock,
    SubEpochChallengeSegment,
    SubEpochSummary,
    UnfinishedBlock,
    additions_and_removals,
    get_flags_for_height_and_constants,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint32, uint64, uint128

from chia.consensus.block_body_validation import ForkInfo, validate_block_body
from chia.consensus.block_header_validation import validate_unfinished_header_block
from chia.consensus.coin_store_protocol import CoinStoreProtocol
from chia.consensus.cost_calculator import NPCResult
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.find_fork_point import lookup_fork_chain
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.consensus.generator_tools import get_block_header
from chia.consensus.get_block_generator import get_block_generator
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.full_node.block_height_map import BlockHeightMap
from chia.full_node.block_store import BlockStore
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.vdf import VDFInfo
from chia.types.coin_record import CoinRecord
from chia.types.generator_types import BlockGenerator
from chia.types.unfinished_header_block import UnfinishedHeaderBlock
from chia.types.validation_state import ValidationState
from chia.util.cpu import available_logical_cores
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.inline_executor import InlineExecutor
from chia.util.priority_mutex import PriorityMutex

log = logging.getLogger(__name__)


class AddBlockResult(Enum):
    """
    When Blockchain.add_block(b) is called, one of these results is returned,
    showing whether the block was added to the chain (extending the peak),
    and if not, why it was not added.
    """

    NEW_PEAK = 1  # Added to the peak of the blockchain
    ADDED_AS_ORPHAN = 2  # Added as an orphan/stale block (not a new peak of the chain)
    INVALID_BLOCK = 3  # Block was not added because it was invalid
    ALREADY_HAVE_BLOCK = 4  # Block is already present in this blockchain
    DISCONNECTED_BLOCK = 5  # Block's parent (previous pointer) is not in this blockchain


@dataclasses.dataclass
class StateChangeSummary:
    peak: BlockRecord
    fork_height: uint32
    rolled_back_records: list[CoinRecord]
    # list of coin-id, puzzle-hash pairs
    removals: list[tuple[bytes32, bytes32]]
    # new coin and hint
    additions: list[tuple[Coin, Optional[bytes]]]
    new_rewards: list[Coin]


class BlockchainMutexPriority(enum.IntEnum):
    # lower values are higher priority
    low = 1
    high = 0


# implements BlockchainInterface
class Blockchain:
    if TYPE_CHECKING:
        from chia.consensus.blockchain_interface import BlockchainInterface

        _protocol_check: ClassVar[BlockchainInterface] = cast("Blockchain", None)

    constants: ConsensusConstants

    # peak of the blockchain
    _peak_height: Optional[uint32]
    # All blocks in peak path are guaranteed to be included, can include orphan blocks
    __block_records: dict[bytes32, BlockRecord]
    # all hashes of blocks in block_record by height, used for garbage collection
    __heights_in_cache: dict[uint32, set[bytes32]]
    # maps block height (of the current heaviest chain) to block hash and sub
    # epoch summaries
    __height_map: BlockHeightMap
    # Unspent Store
    coin_store: CoinStoreProtocol
    # Store
    block_store: BlockStore
    # Used to verify blocks in parallel
    pool: Executor
    # Set holding seen compact proofs, in order to avoid duplicates.
    _seen_compact_proofs: set[tuple[VDFInfo, uint32]]

    # Whether blockchain is shut down or not
    _shut_down: bool

    # Lock to prevent simultaneous reads and writes
    priority_mutex: PriorityMutex[BlockchainMutexPriority]
    compact_proof_lock: asyncio.Lock

    _log_coins: bool

    @staticmethod
    async def create(
        coin_store: CoinStoreProtocol,
        block_store: BlockStore,
        height_map: BlockHeightMap,
        consensus_constants: ConsensusConstants,
        reserved_cores: int,
        *,
        single_threaded: bool = False,
        log_coins: bool = False,
    ) -> Blockchain:
        """
        Initializes a blockchain with the BlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = Blockchain()
        self._log_coins = log_coins
        # Blocks are validated under high priority, and transactions under low priority. This guarantees blocks will
        # be validated first.
        self.priority_mutex = PriorityMutex.create(priority_type=BlockchainMutexPriority)
        self.compact_proof_lock = asyncio.Lock()
        if single_threaded:
            self.pool = InlineExecutor()
        else:
            cpu_count = available_logical_cores()
            num_workers = max(cpu_count - reserved_cores, 1)
            self.pool = ThreadPoolExecutor(
                max_workers=num_workers,
                thread_name_prefix="block-validation-",
            )
            log.info(f"Started {num_workers} processes for block validation")

        self.constants = consensus_constants
        self.coin_store = coin_store
        self.block_store = block_store
        self._shut_down = False
        await self._load_chain_from_store(height_map)
        self._seen_compact_proofs = set()
        return self

    def shut_down(self) -> None:
        self._shut_down = True
        self.pool.shutdown(wait=True)

    async def _load_chain_from_store(self, height_map: BlockHeightMap) -> None:
        """
        Initializes the state of the Blockchain class from the database.
        """
        self.__height_map = height_map
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
        assert self.__height_map.contains_height(self._peak_height)
        assert not self.__height_map.contains_height(uint32(self._peak_height + 1))

    def get_peak(self) -> Optional[BlockRecord]:
        """
        Return the peak of the blockchain
        """
        if self._peak_height is None:
            return None
        return self.height_to_block_record(self._peak_height)

    def get_tx_peak(self) -> Optional[BlockRecord]:
        """
        Return the most recent transaction block. i.e. closest to the peak of the blockchain
        Requires the blockchain to be initialized and there to be a peak set
        """

        if self._peak_height is None:
            return None
        tx_height = self._peak_height
        tx_peak = self.height_to_block_record(tx_height)
        while not tx_peak.is_transaction_block:
            # it seems BlockTools only produce chains where the first block is a
            # transaction block, which makes it hard to test this case
            if tx_height == 0:  # pragma: no cover
                return None
            tx_height = uint32(tx_height - 1)
            tx_peak = self.height_to_block_record(tx_height)

        return tx_peak

    async def get_full_peak(self) -> Optional[FullBlock]:
        if self._peak_height is None:
            return None
        """ Return list of FullBlocks that are peaks"""
        peak_hash: Optional[bytes32] = self.height_to_hash(self._peak_height)
        assert peak_hash is not None  # Since we must have the peak block
        block = await self.block_store.get_full_block(peak_hash)
        assert block is not None
        return block

    async def get_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        return await self.block_store.get_full_block(header_hash)

    async def advance_fork_info(self, block: FullBlock, fork_info: ForkInfo) -> None:
        """
        This function is used to advance the peak_height of fork_info given the
        full block extending the chain. block is required to be the next block on
        top of fork_info.peak_height. If the block is part of the main chain,
        the fork_height will set to the same as the peak, making the fork_info
        represent an empty fork chain.
        If the block is part of a fork, we need to compute the additions and
        removals, to update the fork_info object. This is an expensive operation.
        """

        assert fork_info.peak_height <= block.height - 1
        assert fork_info.peak_hash != block.header_hash

        if fork_info.peak_hash == block.prev_header_hash:
            assert fork_info.peak_height == block.height - 1
            return

        # note that we're not technically finding a fork here, we just traverse
        # from the current block down to the fork's current peak
        chain, peak_hash = await lookup_fork_chain(
            self,
            (fork_info.peak_height, fork_info.peak_hash),
            (block.height - 1, block.prev_header_hash),
            self.constants,
        )
        # the ForkInfo object is expected to be valid, just having its peak
        # behind the current block
        assert peak_hash == fork_info.peak_hash
        assert len(chain) == block.height - fork_info.peak_height - 1

        for height in range(fork_info.peak_height + 1, block.height):
            fork_block: Optional[FullBlock] = await self.block_store.get_full_block(chain[uint32(height)])
            assert fork_block is not None
            await self.run_single_block(fork_block, fork_info)

    async def run_single_block(self, block: FullBlock, fork_info: ForkInfo) -> None:
        assert fork_info.peak_height == block.height - 1
        assert block.height == 0 or fork_info.peak_hash == block.prev_header_hash

        additions: list[tuple[Coin, Optional[bytes]]] = []
        removals: list[tuple[bytes32, Coin]] = []
        if block.transactions_generator is not None:
            block_generator: Optional[BlockGenerator] = await get_block_generator(self.lookup_block_generators, block)
            assert block_generator is not None
            assert block.transactions_info is not None
            assert block.foliage_transaction_block is not None
            flags = get_flags_for_height_and_constants(block.height, self.constants)
            additions, removals = additions_and_removals(
                bytes(block.transactions_generator),
                block_generator.generator_refs,
                flags,
                self.constants,
            )

        fork_info.include_block(additions, removals, block, block.header_hash)

    async def add_block(
        self,
        block: FullBlock,
        pre_validation_result: PreValidationResult,
        sub_slot_iters: uint64,
        fork_info: ForkInfo,
        prev_ses_block: Optional[BlockRecord] = None,
        block_record: Optional[BlockRecord] = None,
    ) -> tuple[AddBlockResult, Optional[Err], Optional[StateChangeSummary]]:
        """
        This method must be called under the blockchain lock
        Adds a new block into the blockchain, if it's valid and connected to the current
        blockchain, regardless of whether it is the child of a head, or another block.
        Returns a header if block is added to head. Returns an error if the block is
        invalid. Also returns the fork height, in the case of a new peak.

        Args:
            block: The FullBlock to be validated.
            pre_validation_result: A result of successful pre validation
            fork_info: Information about the fork chain this block is part of,
               to make validation more efficient. This is an in-out parameter.

        Returns:
            The result of adding the block to the blockchain (NEW_PEAK, ADDED_AS_ORPHAN, INVALID_BLOCK,
                DISCONNECTED_BLOCK, ALREDY_HAVE_BLOCK)
            An optional error if the result is not NEW_PEAK or ADDED_AS_ORPHAN
            A StateChangeSummary iff NEW_PEAK, with:
                - A fork point if the result is NEW_PEAK
                - A list of coin changes as a result of rollback
                - A list of NPCResult for any new transaction block added to the chain
        """

        if block.height == 0 and block.prev_header_hash != self.constants.GENESIS_CHALLENGE:
            return AddBlockResult.INVALID_BLOCK, Err.INVALID_PREV_BLOCK_HASH, None

        peak = self.get_peak()
        genesis: bool = block.height == 0
        extending_main_chain: bool = genesis or peak is None or (block.prev_header_hash == peak.header_hash)

        # first check if this block is disconnected from the currently known
        # blocks. We can only accept blocks that are connected to another block
        # we know of.
        prev_block: Optional[BlockRecord] = None
        if not extending_main_chain and not genesis:
            prev_block = self.try_block_record(block.prev_header_hash)
            if prev_block is None:
                return AddBlockResult.DISCONNECTED_BLOCK, Err.INVALID_PREV_BLOCK_HASH, None

            if prev_block.height + 1 != block.height:
                return AddBlockResult.INVALID_BLOCK, Err.INVALID_HEIGHT, None

        required_iters = pre_validation_result.required_iters
        if pre_validation_result.error is not None:
            return AddBlockResult.INVALID_BLOCK, Err(pre_validation_result.error), None
        assert required_iters is not None

        header_hash: bytes32 = block.header_hash

        # passing in correct fork_info is critical for performing reorgs
        # correctly, so we perform some validation of it here
        assert block.height - 1 == fork_info.peak_height
        assert len(fork_info.block_hashes) == fork_info.peak_height - fork_info.fork_height
        if fork_info.peak_height == fork_info.fork_height:
            # if fork_info is saying we're not on a fork, the previous block better
            # be part of the main chain
            assert block.prev_header_hash == fork_info.peak_hash
            if fork_info.fork_height == -1:
                assert fork_info.peak_hash == self.constants.GENESIS_CHALLENGE
            else:
                assert self.height_to_hash(uint32(fork_info.fork_height)) == block.prev_header_hash
        else:
            assert fork_info.peak_hash == block.prev_header_hash

        if extending_main_chain:
            fork_info.reset(block.height - 1, block.prev_header_hash)

        # we dont consider block_record passed in here since it might be from
        # a current sync process and not yet fully validated and committed to the DB
        block_rec_from_db = await self.get_block_record_from_db(header_hash)
        if block_rec_from_db is not None:
            # We have already validated the block, but if it's not part of the
            # main chain, we still need to re-run it to update the additions and
            # removals in fork_info.
            await self.advance_fork_info(block, fork_info)
            fork_info.include_spends(pre_validation_result.conds, block, header_hash)
            self.add_block_record(block_rec_from_db)
            return AddBlockResult.ALREADY_HAVE_BLOCK, None, None

        if fork_info.peak_hash != block.prev_header_hash:
            await self.advance_fork_info(block, fork_info)

        # if these prerequisites of the fork_info aren't met, the fork_info
        # object is invalid for this block. If the caller would have passed in
        # None, a valid fork_info would have been computed
        assert fork_info.peak_height == block.height - 1
        assert block.height == 0 or fork_info.peak_hash == block.prev_header_hash

        assert block.transactions_generator is None or pre_validation_result.validated_signature
        error_code = await validate_block_body(
            self.constants,
            self,
            self.coin_store.get_coin_records,
            block,
            block.height,
            pre_validation_result.conds,
            fork_info,
            log_coins=self._log_coins,
        )
        if error_code is not None:
            return AddBlockResult.INVALID_BLOCK, error_code, None

        # commit the additions and removals from this block into the ForkInfo, in
        # case we're validating blocks on a fork, the next block validation will
        # need to know of these additions and removals. Also, _reconsider_peak()
        # will need these results
        fork_info.include_spends(pre_validation_result.conds, block, header_hash)

        # block_to_block_record() require the previous block in the cache
        if not genesis and prev_block is not None:
            self.add_block_record(prev_block)

        if block_record is None:
            block_record = block_to_block_record(
                self.constants,
                self,
                required_iters,
                block,
                sub_slot_iters=sub_slot_iters,
                prev_ses_block=prev_ses_block,
            )

        # in case we fail and need to restore the blockchain state, remember the
        # peak height
        previous_peak_height = self._peak_height
        prev_fork_peak = (fork_info.peak_height, fork_info.peak_hash)

        try:
            # Always add the block to the database
            async with self.block_store.db_wrapper.writer():
                # Perform the DB operations to update the state, and rollback if something goes wrong
                await self.block_store.add_full_block(header_hash, block, block_record)
                records, state_change_summary = await self._reconsider_peak(block_record, genesis, fork_info)

                # Then update the memory cache. It is important that this is not cancelled and does not throw
                # This is done after all async/DB operations, so there is a decreased chance of failure.
                self.add_block_record(block_record)

            # there's a suspension point here, as we leave the async context
            # manager

            # make sure to update _peak_height after the transaction is committed,
            # otherwise other tasks may go look for this block before it's available
            if state_change_summary is not None:
                self.__height_map.rollback(state_change_summary.fork_height)
            for fetched_block_record in records:
                self.__height_map.update_height(
                    fetched_block_record.height,
                    fetched_block_record.header_hash,
                    fetched_block_record.sub_epoch_summary_included,
                )

            if state_change_summary is not None:
                self._peak_height = block_record.height

        except BaseException as e:
            # depending on exactly when the failure of adding the block
            # happened, we may not have added it to the block record cache
            try:
                self.remove_block_record(header_hash)
            except KeyError:
                pass
            # restore fork_info to the state before adding the block
            fork_info.rollback(prev_fork_peak[1], prev_fork_peak[0])
            self.block_store.rollback_cache_block(header_hash)
            self._peak_height = previous_peak_height
            log.error(
                f"Error while adding block {header_hash} height {block.height},"
                f" rolling back: {traceback.format_exc()} {e}"
            )
            raise

        # This is done outside the try-except in case it fails, since we do not want to revert anything if it does
        await self.__height_map.maybe_flush()

        if state_change_summary is not None:
            # new coin records added
            return AddBlockResult.NEW_PEAK, None, state_change_summary
        else:
            return AddBlockResult.ADDED_AS_ORPHAN, None, None

    # only to be called under short fork points
    # under deep reorgs this can cause OOM
    async def _reconsider_peak(
        self,
        block_record: BlockRecord,
        genesis: bool,
        fork_info: ForkInfo,
    ) -> tuple[list[BlockRecord], Optional[StateChangeSummary]]:
        """
        When a new block is added, this is called, to check if the new block is the new peak of the chain.
        This also handles reorgs by reverting blocks which are not in the heaviest chain.
        It returns the summary of the applied changes, including the height of the fork between the previous chain
        and the new chain, or returns None if there was no update to the heaviest chain.
        """

        peak = self.get_peak()
        rolled_back_state: dict[bytes32, CoinRecord] = {}

        if genesis and peak is not None:
            return [], None

        if peak is not None:
            if block_record.weight < peak.weight:
                # This is not a heavier block than the heaviest we have seen, so we don't change the coin set
                return [], None
            if block_record.weight == peak.weight and peak.total_iters <= block_record.total_iters:
                # this is an equal weight block but our peak has lower iterations, so we dont change the coin set
                return [], None
            if block_record.weight == peak.weight:
                log.info(
                    f"block has equal weight as our peak ({peak.weight}), but fewer "
                    f"total iterations {block_record.total_iters} "
                    f"peak: {peak.total_iters} "
                    f"peak-hash: {peak.header_hash}"
                )

            if block_record.prev_hash != peak.header_hash:
                rolled_back_state = await self.coin_store.rollback_to_block(fork_info.fork_height)
                if self._log_coins and len(rolled_back_state) > 0:
                    log.info(f"rolled back {len(rolled_back_state)} coins, to fork height {fork_info.fork_height}")
                    log.info(
                        "removed: %s",
                        ",".join(
                            [
                                name.hex()[0:6]
                                for name, state in rolled_back_state.items()
                                if state.confirmed_block_index == 0
                            ]
                        ),
                    )
                    log.info(
                        "unspent: %s",
                        ",".join(
                            [
                                name.hex()[0:6]
                                for name, state in rolled_back_state.items()
                                if state.confirmed_block_index != 0
                            ]
                        ),
                    )

        # Collects all blocks from fork point to new peak
        records_to_add: list[BlockRecord] = []

        if genesis:
            records_to_add = [block_record]
        elif fork_info.block_hashes == [block_record.header_hash]:
            # in the common case, we just add a block on top of the chain. Check
            # for that here to avoid an unnecessary database lookup.
            records_to_add = [block_record]
        else:
            records_to_add = await self.block_store.get_block_records_by_hash(fork_info.block_hashes)

        for fetched_block_record in records_to_add:
            if not fetched_block_record.is_transaction_block:
                # Coins are only created in TX blocks so there are no state updates for this block
                continue

            height = fetched_block_record.height
            # We need to recompute the additions and removals, since they are
            # not stored on DB. We have all the additions and removals in the
            # fork_info object, we just need to pick the ones belonging to each
            # individual block height

            # Apply the coin store changes for each block that is now in the blockchain
            included_reward_coins = [
                fork_add.coin
                for fork_add in fork_info.additions_since_fork.values()
                if fork_add.confirmed_height == height and fork_add.is_coinbase
            ]
            tx_additions = [
                (coin_id, fork_add.coin, fork_add.same_as_parent)
                for coin_id, fork_add in fork_info.additions_since_fork.items()
                if fork_add.confirmed_height == height and not fork_add.is_coinbase
            ]
            tx_removals = [
                coin_id for coin_id, fork_rem in fork_info.removals_since_fork.items() if fork_rem.height == height
            ]
            assert fetched_block_record.timestamp is not None
            await self.coin_store.new_block(
                height,
                fetched_block_record.timestamp,
                included_reward_coins,
                tx_additions,
                tx_removals,
            )
            if self._log_coins and (len(tx_removals) > 0 or len(tx_additions) > 0):
                log.info(
                    f"adding new block to coin_store "
                    f"(hh: {fetched_block_record.header_hash} "
                    f"height: {fetched_block_record.height}), {len(tx_removals)} spends"
                )
                log.info("rewards: %s", ",".join([add.name().hex()[0:6] for add in included_reward_coins]))
                log.info("additions: %s", ",".join([add[0].hex()[0:6] for add in tx_additions]))
                log.info("removals: %s", ",".join([f"{rem}"[0:6] for rem in tx_removals]))

        # we made it to the end successfully
        # Rollback sub_epoch_summaries
        await self.block_store.rollback(fork_info.fork_height)
        await self.block_store.set_in_chain([(br.header_hash,) for br in records_to_add])

        # Changes the peak to be the new peak
        await self.block_store.set_peak(block_record.header_hash)

        return records_to_add, StateChangeSummary(
            block_record,
            uint32(max(fork_info.fork_height, 0)),
            list(rolled_back_state.values()),
            [(coin_id, fork_rem.puzzle_hash) for coin_id, fork_rem in fork_info.removals_since_fork.items()],
            [
                (fork_add.coin, fork_add.hint)
                for fork_add in fork_info.additions_since_fork.values()
                if not fork_add.is_coinbase
            ],
            [fork_add.coin for fork_add in fork_info.additions_since_fork.values() if fork_add.is_coinbase],
        )

    def get_next_sub_slot_iters_and_difficulty(self, header_hash: bytes32, new_slot: bool) -> tuple[uint64, uint64]:
        curr = self.try_block_record(header_hash)
        assert curr is not None
        if curr.height <= 2:
            return self.constants.SUB_SLOT_ITERS_STARTING, self.constants.DIFFICULTY_STARTING

        return get_next_sub_slot_iters_and_difficulty(self.constants, new_slot, curr, self)

    async def get_sp_and_ip_sub_slots(
        self, header_hash: bytes32
    ) -> Optional[tuple[Optional[EndOfSubSlotBundle], Optional[EndOfSubSlotBundle]]]:
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

    def get_recent_reward_challenges(self) -> list[tuple[bytes32, uint128]]:
        peak = self.get_peak()
        if peak is None:
            return []
        recent_rc: list[tuple[bytes32, uint128]] = []
        curr: Optional[BlockRecord] = peak
        while curr is not None and len(recent_rc) < 2 * self.constants.MAX_SUB_SLOT_BLOCKS:
            if curr != peak:
                recent_rc.append((curr.reward_infusion_new_challenge, curr.total_iters))
            if curr.first_in_sub_slot:
                assert curr.finished_reward_slot_hashes is not None
                sub_slot_total_iters = curr.ip_sub_slot_total_iters(self.constants)
                # Start from the most recent
                for rc in reversed(curr.finished_reward_slot_hashes):
                    if sub_slot_total_iters < curr.sub_slot_iters:
                        break
                    recent_rc.append((rc, sub_slot_total_iters))
                    sub_slot_total_iters = uint128(sub_slot_total_iters - curr.sub_slot_iters)
            curr = self.try_block_record(curr.prev_hash)
        return list(reversed(recent_rc))

    async def validate_unfinished_block_header(
        self, block: UnfinishedBlock, skip_overflow_ss_validation: bool = True
    ) -> tuple[Optional[uint64], Optional[Err]]:
        if len(block.transactions_generator_ref_list) > self.constants.MAX_GENERATOR_REF_LIST_SIZE:
            return None, Err.TOO_MANY_GENERATOR_REFS

        if (
            self.try_block_record(block.prev_header_hash) is None
            and block.prev_header_hash != self.constants.GENESIS_CHALLENGE
        ):
            return None, Err.INVALID_PREV_BLOCK_HASH

        if block.transactions_info is not None:
            if block.transactions_generator is not None:
                if std_hash(bytes(block.transactions_generator)) != block.transactions_info.generator_root:
                    return None, Err.INVALID_TRANSACTIONS_GENERATOR_HASH
            else:
                if block.transactions_info.generator_root != bytes([0] * 32):
                    return None, Err.INVALID_TRANSACTIONS_GENERATOR_HASH

            if (
                block.foliage_transaction_block is None
                or block.foliage_transaction_block.transactions_info_hash != block.transactions_info.get_hash()
            ):
                return None, Err.INVALID_TRANSACTIONS_INFO_HASH
        else:
            # make sure non-tx blocks don't have these fields
            if block.transactions_generator is not None:
                return None, Err.INVALID_TRANSACTIONS_GENERATOR_HASH
            if block.foliage_transaction_block is not None:
                return None, Err.INVALID_TRANSACTIONS_INFO_HASH

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
        expected_vs = ValidationState(sub_slot_iters, difficulty, None)
        required_iters, error = validate_unfinished_header_block(
            self.constants,
            self,
            unfinished_header_block,
            False,
            expected_vs,
            skip_overflow_ss_validation,
        )
        if error is not None:
            return required_iters, error.code
        return required_iters, None

    async def validate_unfinished_block(
        self, block: UnfinishedBlock, npc_result: Optional[NPCResult], skip_overflow_ss_validation: bool = True
    ) -> PreValidationResult:
        required_iters, error = await self.validate_unfinished_block_header(block, skip_overflow_ss_validation)

        if error is not None:
            return PreValidationResult(uint16(error.value), None, None, uint32(0))

        prev_height = (
            -1
            if block.prev_header_hash == self.constants.GENESIS_CHALLENGE
            else self.block_record(block.prev_header_hash).height
        )

        fork_info = ForkInfo(prev_height, prev_height, block.prev_header_hash)

        conds = None if npc_result is None else npc_result.conds
        error_code = await validate_block_body(
            self.constants,
            self,
            self.coin_store.get_coin_records,
            block,
            uint32(prev_height + 1),
            conds,
            fork_info,
            log_coins=self._log_coins,
        )

        if error_code is not None:
            return PreValidationResult(uint16(error_code.value), None, None, uint32(0))

        return PreValidationResult(None, required_iters, conds, uint32(0))

    def contains_block(self, header_hash: bytes32, height: uint32) -> bool:
        block_hash_from_hh = self.height_to_hash(height)
        if block_hash_from_hh is None or block_hash_from_hh != header_hash:
            return False
        return True

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self.__block_records[header_hash]

    def height_to_block_record(self, height: uint32) -> BlockRecord:
        # Precondition: height is in the blockchain
        header_hash: Optional[bytes32] = self.height_to_hash(height)
        if header_hash is None:
            raise ValueError(f"Height is not in blockchain: {height}")
        return self.block_record(header_hash)

    def get_ses_heights(self) -> list[uint32]:
        return self.__height_map.get_ses_heights()

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return self.__height_map.get_ses(height)

    def height_to_hash(self, height: uint32) -> Optional[bytes32]:
        if not self.__height_map.contains_height(height):
            return None
        return self.__height_map.get_hash(height)

    def contains_height(self, height: uint32) -> bool:
        return self.__height_map.contains_height(height)

    def get_peak_height(self) -> Optional[uint32]:
        return self._peak_height

    async def warmup(self, fork_point: uint32) -> None:
        """
        Loads blocks into the cache. The blocks loaded include all blocks from
        fork point - BLOCKS_CACHE_SIZE up to and including the fork_point.

        Args:
            fork_point: the last block height to load in the cache

        """
        if self._peak_height is None:
            return None
        block_records = await self.block_store.get_block_records_in_range(
            max(fork_point - self.constants.BLOCKS_CACHE_SIZE, uint32(0)), fork_point
        )
        for block_record in block_records.values():
            self.add_block_record(block_record)

    def clean_block_record(self, height: int) -> None:
        """
        Clears all block records in the cache which have block_record < height.
        Args:
            height: Minimum height that we need to keep in the cache
        """
        if self._peak_height is not None and height > self._peak_height - self.constants.BLOCKS_CACHE_SIZE:
            height = self._peak_height - self.constants.BLOCKS_CACHE_SIZE
        if height < 0:
            return None
        blocks_to_remove = self.__heights_in_cache.get(uint32(height), None)
        while blocks_to_remove is not None and height >= 0:
            for header_hash in blocks_to_remove:
                del self.__block_records[header_hash]  # remove from blocks
            del self.__heights_in_cache[uint32(height)]  # remove height from heights in cache

            if height == 0:
                break
            height -= 1
            blocks_to_remove = self.__heights_in_cache.get(uint32(height), None)

    def clean_block_records(self) -> None:
        """
        Cleans the cache so that we only maintain relevant blocks. This removes
        block records that have height < peak - BLOCKS_CACHE_SIZE.
        These blocks are necessary for calculating future difficulty adjustments.
        """

        if len(self.__block_records) < self.constants.BLOCKS_CACHE_SIZE:
            return None

        assert self._peak_height is not None
        if self._peak_height - self.constants.BLOCKS_CACHE_SIZE < 0:
            return None
        self.clean_block_record(self._peak_height - self.constants.BLOCKS_CACHE_SIZE)

    async def get_block_records_in_range(self, start: int, stop: int) -> dict[bytes32, BlockRecord]:
        return await self.block_store.get_block_records_in_range(start, stop)

    async def get_header_blocks_in_range(
        self, start: int, stop: int, tx_filter: bool = True
    ) -> dict[bytes32, HeaderBlock]:
        hashes = []
        for height in range(start, stop + 1):
            header_hash: Optional[bytes32] = self.height_to_hash(uint32(height))
            if header_hash is not None:
                hashes.append(header_hash)

        blocks: list[FullBlock] = []
        for hash in hashes.copy():
            block = self.block_store.block_cache.get(hash)
            if block is not None:
                blocks.append(block)
                hashes.remove(hash)
        blocks_on_disk: list[FullBlock] = await self.block_store.get_blocks_by_hash(hashes)
        blocks.extend(blocks_on_disk)
        header_blocks: dict[bytes32, HeaderBlock] = {}

        for block in blocks:
            if self.height_to_hash(block.height) != block.header_hash:
                raise ValueError(f"Block at {block.header_hash} is no longer in the blockchain (it's in a fork)")
            if tx_filter is False:
                header = get_block_header(block)
            elif block.transactions_generator is not None:
                added_coins_records, removed_coins_records = await asyncio.gather(
                    self.coin_store.get_coins_added_at_height(block.height),
                    self.coin_store.get_coins_removed_at_height(block.height),
                )
                tx_additions = [cr.coin for cr in added_coins_records if not cr.coinbase]
                removed = [cr.coin.name() for cr in removed_coins_records]
                header = get_block_header(block, (removed, tx_additions))
            elif block.is_transaction_block():
                # This is a transaction block with just reward coins.
                # We're sending empty additions and removals to signal that we
                # want the transactions filter to be computed.
                header = get_block_header(block, ([], []))
            else:
                # Non transaction block.
                header = get_block_header(block)
            header_blocks[header.header_hash] = header

        return header_blocks

    async def get_header_block_by_height(
        self, height: int, header_hash: bytes32, tx_filter: bool = True
    ) -> Optional[HeaderBlock]:
        header_dict: dict[bytes32, HeaderBlock] = await self.get_header_blocks_in_range(height, height, tx_filter)
        if len(header_dict) == 0:
            return None
        if header_hash not in header_dict:
            return None
        return header_dict[header_hash]

    async def get_block_records_at(self, heights: list[uint32], batch_size: int = 900) -> list[BlockRecord]:
        """
        gets block records by height (only blocks that are part of the chain)
        """
        records: list[BlockRecord] = []
        hashes: list[bytes32] = []
        assert batch_size < self.block_store.db_wrapper.host_parameter_limit
        for height in heights:
            header_hash: Optional[bytes32] = self.height_to_hash(height)
            if header_hash is None:
                raise ValueError(f"Do not have block at height {height}")
            hashes.append(header_hash)
            if len(hashes) > batch_size:
                res = await self.block_store.get_block_records_by_hash(hashes)
                records.extend(res)
                hashes = []

        if len(hashes) > 0:
            res = await self.block_store.get_block_records_by_hash(hashes)
            records.extend(res)
        return records

    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        if header_hash in self.__block_records:
            return self.block_record(header_hash)
        return None

    async def get_block_record_from_db(self, header_hash: bytes32) -> Optional[BlockRecord]:
        ret = self.__block_records.get(header_hash)
        if ret is not None:
            return ret
        return await self.block_store.get_block_record(header_hash)

    async def prev_block_hash(self, header_hashes: list[bytes32]) -> list[bytes32]:
        """
        Given a list of block header hashes, returns the previous header hashes
        for each block, in the order they were passed in.
        """
        ret = []
        for h in header_hashes:
            b = self.__block_records.get(h)
            if b is not None:
                ret.append(b.prev_hash)
            else:
                ret.append(await self.block_store.get_prev_hash(h))
        return ret

    async def contains_block_from_db(self, header_hash: bytes32) -> bool:
        ret = header_hash in self.__block_records
        if ret:
            return True

        return (await self.block_store.get_block_record(header_hash)) is not None

    def remove_block_record(self, header_hash: bytes32) -> None:
        sbr = self.block_record(header_hash)
        del self.__block_records[header_hash]
        self.__heights_in_cache[sbr.height].remove(header_hash)

    def add_block_record(self, block_record: BlockRecord) -> None:
        """
        Adds a block record to the cache.
        """

        self.__block_records[block_record.header_hash] = block_record
        if block_record.height not in self.__heights_in_cache.keys():
            self.__heights_in_cache[block_record.height] = set()
        self.__heights_in_cache[block_record.height].add(block_record.header_hash)

    async def persist_sub_epoch_challenge_segments(
        self, ses_block_hash: bytes32, segments: list[SubEpochChallengeSegment]
    ) -> None:
        await self.block_store.persist_sub_epoch_challenge_segments(ses_block_hash, segments)

    async def get_sub_epoch_challenge_segments(
        self,
        ses_block_hash: bytes32,
    ) -> Optional[list[SubEpochChallengeSegment]]:
        segments: Optional[list[SubEpochChallengeSegment]] = await self.block_store.get_sub_epoch_challenge_segments(
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

    async def lookup_block_generators(self, header_hash: bytes32, generator_refs: set[uint32]) -> dict[uint32, bytes]:
        generators: dict[uint32, bytes] = {}

        # if this is empty, we shouldn't have called this function to begin with
        assert len(generator_refs)

        # The block heights in the transactions_generator_ref_list don't
        # necessarily refer to the main chain. The generators may be found in 2
        # different places. A fork of the chain (but in the database) or in
        # the main chain.

        #              * <- header_hash
        #              | :
        # peak -> *    | : reorg_chain
        #          \   / :
        #           \ /  :
        #            *  <- fork point
        #         :  |
        #  main   :  |
        #  chain  :  |
        #         :  |
        #         :  * <- genesis

        # If the block is not part of the main chain, we're on a fork, and we
        # need to find the fork point
        peak_block = await self.get_block_record_from_db(header_hash)
        assert peak_block is not None
        if self.height_to_hash(peak_block.height) != header_hash:
            peak: Optional[BlockRecord] = self.get_peak()
            assert peak is not None
            reorg_chain: dict[uint32, bytes32]
            # Then we look up blocks up to fork point one at a time, backtracking
            reorg_chain, _ = await lookup_fork_chain(
                self,
                (peak.height, peak.header_hash),
                (peak_block.height, peak_block.header_hash),
                self.constants,
            )

            remaining_refs = set()
            for ref_height in generator_refs:
                if ref_height in reorg_chain:
                    gen = await self.block_store.get_generator(reorg_chain[ref_height])
                    if gen is None:
                        raise ValueError(Err.GENERATOR_REF_HAS_NO_GENERATOR)
                    generators[ref_height] = gen
                else:
                    remaining_refs.add(ref_height)
        else:
            remaining_refs = generator_refs

        if len(remaining_refs) > 0:
            # any remaining references fall in the main chain, and can be looked up
            # in a single query
            generators.update(await self.block_store.get_generators_at(remaining_refs))

        return generators
