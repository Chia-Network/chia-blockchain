from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Dict, List, Optional, Tuple, cast

from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import AddBlockResult
from chia.consensus.constants import ConsensusConstants
from chia.consensus.find_fork_point import find_fork_point_in_chain
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import WeightProof
from chia.util.errors import Err
from chia.util.ints import uint32, uint64
from chia.wallet.key_val_store import KeyValStore
from chia.wallet.wallet_weight_proof_handler import WalletWeightProofHandler

log = logging.getLogger(__name__)


# implements BlockchainInterface
class WalletBlockchain:
    if TYPE_CHECKING:
        from chia.consensus.blockchain_interface import BlockRecordsProtocol

        _protocol_check: ClassVar[BlockRecordsProtocol] = cast("WalletBlockchain", None)

    constants: ConsensusConstants
    _basic_store: KeyValStore
    _weight_proof_handler: WalletWeightProofHandler

    synced_weight_proof: Optional[WeightProof]
    _finished_sync_up_to: uint32

    _peak: Optional[HeaderBlock]
    _height_to_hash: Dict[uint32, bytes32]
    _block_records: Dict[bytes32, BlockRecord]
    _latest_timestamp: uint64
    _sub_slot_iters: uint64
    _difficulty: uint64
    CACHE_SIZE: int

    @staticmethod
    async def create(_basic_store: KeyValStore, constants: ConsensusConstants) -> WalletBlockchain:
        """
        Initializes a blockchain with the BlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = WalletBlockchain()
        self._basic_store = _basic_store
        self.constants = constants
        self.CACHE_SIZE = constants.SUB_EPOCH_BLOCKS * 3
        self.synced_weight_proof = await self._basic_store.get_object("SYNCED_WEIGHT_PROOF", WeightProof)
        self._sub_slot_iters = await self._basic_store.get_object("SUB_SLOT_ITERS", uint64)
        self._difficulty = await self._basic_store.get_object("DIFFICULTY", uint64)
        self._finished_sync_up_to = await self._basic_store.get_object("FINISHED_SYNC_UP_TO", uint32)
        if self._finished_sync_up_to is None:
            self._finished_sync_up_to = uint32(0)
        self._peak = None
        self._peak = await self.get_peak_block()
        self._latest_timestamp = uint64(0)
        self._height_to_hash = {}
        self._block_records = {}
        self._sub_slot_iters = constants.SUB_SLOT_ITERS_STARTING
        self._difficulty = constants.DIFFICULTY_STARTING

        return self

    async def new_valid_weight_proof(self, weight_proof: WeightProof, records: List[BlockRecord]) -> None:
        peak: Optional[HeaderBlock] = await self.get_peak_block()

        if peak is not None and weight_proof.recent_chain_data[-1].weight <= peak.weight:
            # No update, don't change anything
            return None
        self.synced_weight_proof = weight_proof
        async with self._basic_store.db_wrapper.writer():
            await self._basic_store.set_object("SYNCED_WEIGHT_PROOF", weight_proof)
            latest_timestamp = self._latest_timestamp
            for record in records:
                self._height_to_hash[record.height] = record.header_hash
                self.add_block_record(record)
                if record.is_transaction_block:
                    assert record.timestamp is not None
                    latest_timestamp = max(latest_timestamp, record.timestamp)

            self._sub_slot_iters = records[-1].sub_slot_iters
            self._difficulty = uint64(records[-1].weight - records[-2].weight)
            await self._basic_store.set_object("SUB_SLOT_ITERS", self._sub_slot_iters)
            await self._basic_store.set_object("DIFFICULTY", self._difficulty)
            await self.set_peak_block(weight_proof.recent_chain_data[-1], latest_timestamp)
            await self.clean_block_records()

    async def add_block(self, block: HeaderBlock) -> Tuple[AddBlockResult, Optional[Err]]:
        if self.contains_block(block.header_hash):
            return AddBlockResult.ALREADY_HAVE_BLOCK, None
        if not self.contains_block(block.prev_header_hash) and block.height > 0:
            return AddBlockResult.DISCONNECTED_BLOCK, None
        if (
            len(block.finished_sub_slots) > 0
            and block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None
        ):
            assert block.finished_sub_slots[0].challenge_chain.new_difficulty is not None  # They both change together
            sub_slot_iters = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
            difficulty = block.finished_sub_slots[0].challenge_chain.new_difficulty
        else:
            sub_slot_iters = self._sub_slot_iters
            difficulty = self._difficulty

        # Validation requires a block cache (self) that goes back to a subepoch barrier
        required_iters, error = validate_finished_header_block(
            self.constants, self, block, False, difficulty, sub_slot_iters, False
        )
        if error is not None:
            return AddBlockResult.INVALID_BLOCK, error.code
        if required_iters is None:
            return AddBlockResult.INVALID_BLOCK, Err.INVALID_POSPACE

        # We are passing in sub_slot_iters here so we don't need to backtrack until the start of the epoch to find
        # the sub slot iters and difficulty. This allows us to keep the cache small.
        block_record: BlockRecord = block_to_block_record(self.constants, self, required_iters, block, sub_slot_iters)
        self.add_block_record(block_record)
        if self._peak is None:
            if block_record.is_transaction_block:
                latest_timestamp = block_record.timestamp
            else:
                latest_timestamp = None
            self._height_to_hash[block_record.height] = block_record.header_hash
            await self.set_peak_block(block, latest_timestamp)
            return AddBlockResult.NEW_PEAK, None
        elif block_record.weight > self._peak.weight:
            if block_record.prev_hash == self._peak.header_hash:
                fork_height: int = self._peak.height
            else:
                fork_height = await find_fork_point_in_chain(self, block_record, self._peak)
            await self._rollback_to_height(fork_height)
            curr_record: BlockRecord = block_record
            latest_timestamp = self._latest_timestamp
            while curr_record.height > fork_height:
                self._height_to_hash[curr_record.height] = curr_record.header_hash
                if curr_record.timestamp is not None and curr_record.timestamp > latest_timestamp:
                    latest_timestamp = curr_record.timestamp
                if curr_record.height == 0:
                    break
                curr_record = self.block_record(curr_record.prev_hash)
            self._sub_slot_iters = block_record.sub_slot_iters
            self._difficulty = uint64(block_record.weight - self.block_record(block_record.prev_hash).weight)
            await self.set_peak_block(block, latest_timestamp)
            await self.clean_block_records()
            return AddBlockResult.NEW_PEAK, None
        return AddBlockResult.ADDED_AS_ORPHAN, None

    async def _rollback_to_height(self, height: int) -> None:
        if self._peak is None:
            return
        for h in range(max(0, height + 1), self._peak.height + 1):
            del self._height_to_hash[uint32(h)]

        await self._basic_store.remove_object("PEAK_BLOCK")

    async def set_peak_block(self, block: HeaderBlock, timestamp: Optional[uint64] = None) -> None:
        await self._basic_store.set_object("PEAK_BLOCK", block)
        self._peak = block
        if timestamp is not None:
            self._latest_timestamp = timestamp
        elif block.foliage_transaction_block is not None:
            self._latest_timestamp = block.foliage_transaction_block.timestamp
        log.info(f"Peak set to: {self._peak.height} timestamp: {self._latest_timestamp}")

    async def get_peak_block(self) -> Optional[HeaderBlock]:
        if self._peak is not None:
            return self._peak
        header_block = await self._basic_store.get_object("PEAK_BLOCK", HeaderBlock)
        assert header_block is None or isinstance(
            header_block, HeaderBlock
        ), f"get_peak_block expected Optional[HeaderBlock], got {type(header_block)}"
        return header_block

    async def set_finished_sync_up_to(self, height: int, *, in_rollback: bool = False) -> None:
        if (in_rollback and height >= 0) or (height > await self.get_finished_sync_up_to()):
            await self._basic_store.set_object("FINISHED_SYNC_UP_TO", uint32(height))
            await self.clean_block_records()

    async def get_finished_sync_up_to(self) -> uint32:
        h: Optional[uint32] = await self._basic_store.get_object("FINISHED_SYNC_UP_TO", uint32)
        if h is None:
            return uint32(0)
        return h

    def get_latest_timestamp(self) -> uint64:
        return self._latest_timestamp

    def contains_block(self, header_hash: bytes32) -> bool:
        return header_hash in self._block_records

    def contains_height(self, height: uint32) -> bool:
        return height in self._height_to_hash

    def height_to_hash(self, height: uint32) -> bytes32:
        return self._height_to_hash[height]

    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        return self._block_records.get(header_hash)

    def height_to_block_record(self, height: uint32) -> BlockRecord:
        header_hash: Optional[bytes32] = self.height_to_hash(height)
        assert header_hash is not None
        return self._block_records[header_hash]

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self._block_records[header_hash]

    async def get_block_record_from_db(self, header_hash: bytes32) -> Optional[BlockRecord]:
        # the wallet doesn't have the blockchain DB, this implements the
        # blockchain_interface
        return self._block_records.get(header_hash)

    async def prev_block_hash(self, header_hashes: List[bytes32]) -> List[bytes32]:
        ret = []
        for h in header_hashes:
            ret.append(self._block_records[h].prev_hash)
        return ret

    def add_block_record(self, block_record: BlockRecord) -> None:
        self._block_records[block_record.header_hash] = block_record

    async def clean_block_records(self) -> None:
        """
        Cleans the cache so that we only maintain relevant blocks. This removes
        block records that have height < peak - CACHE_SIZE.
        """
        height_limit = max(0, (await self.get_finished_sync_up_to()) - self.CACHE_SIZE)
        if len(self._block_records) < self.CACHE_SIZE:
            return None

        to_remove: List[bytes32] = []
        for header_hash, block_record in self._block_records.items():
            if block_record.height < height_limit:
                to_remove.append(header_hash)

        for header_hash in to_remove:
            del self._block_records[header_hash]
