import logging
from typing import Dict, Optional, Tuple, List
from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import ReceiveBlockResult
from chia.consensus.blockchain_interface import BlockchainInterface
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


class WalletBlockchain(BlockchainInterface):
    constants: ConsensusConstants
    _basic_store: KeyValStore
    _weight_proof_handler: WalletWeightProofHandler

    synced_weight_proof: Optional[WeightProof]

    _peak: Optional[HeaderBlock]
    _height_to_hash: Dict[uint32, bytes32]
    _block_records: Dict[bytes32, BlockRecord]
    _latest_timestamp: uint64
    _sub_slot_iters: uint64
    _difficulty: uint64
    CACHE_SIZE: int

    @staticmethod
    async def create(
        _basic_store: KeyValStore, constants: ConsensusConstants, weight_proof_handler: WalletWeightProofHandler
    ):
        """
        Initializes a blockchain with the BlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = WalletBlockchain()
        self._basic_store = _basic_store
        self.constants = constants
        self.CACHE_SIZE = constants.SUB_EPOCH_BLOCKS + 100
        self._weight_proof_handler = weight_proof_handler
        self.synced_weight_proof = await self._basic_store.get_object("SYNCED_WEIGHT_PROOF", WeightProof)
        self._peak = None
        self._peak = await self.get_peak_block()
        self._latest_timestamp = uint64(0)
        self._height_to_hash = {}
        self._block_records = {}
        if self.synced_weight_proof is not None:
            await self.new_weight_proof(self.synced_weight_proof)
        else:
            self._sub_slot_iters = constants.SUB_SLOT_ITERS_STARTING
            self._difficulty = constants.DIFFICULTY_STARTING

        return self

    async def new_weight_proof(self, weight_proof: WeightProof, records: Optional[List[BlockRecord]] = None) -> None:
        peak: Optional[HeaderBlock] = await self.get_peak_block()

        if peak is not None and weight_proof.recent_chain_data[-1].weight <= peak.weight:
            # No update, don't change anything
            return None
        self.synced_weight_proof = weight_proof
        await self._basic_store.set_object("SYNCED_WEIGHT_PROOF", weight_proof)

        latest_timestamp = self._latest_timestamp

        if records is None:
            success, _, _, records = await self._weight_proof_handler.validate_weight_proof(weight_proof, True)
            assert success
        assert records is not None and len(records) > 1

        for record in records:
            self._height_to_hash[record.height] = record.header_hash
            self.add_block_record(record)
            if record.is_transaction_block:
                assert record.timestamp is not None
                if record.timestamp > latest_timestamp:
                    latest_timestamp = record.timestamp

        self._sub_slot_iters = records[-1].sub_slot_iters
        self._difficulty = uint64(records[-1].weight - records[-2].weight)
        await self.set_peak_block(weight_proof.recent_chain_data[-1], latest_timestamp)
        self.clean_block_records()

    async def receive_block(self, block: HeaderBlock) -> Tuple[ReceiveBlockResult, Optional[Err]]:
        if self.contains_block(block.header_hash):
            return ReceiveBlockResult.ALREADY_HAVE_BLOCK, None
        if not self.contains_block(block.prev_header_hash) and block.height > 0:
            return ReceiveBlockResult.DISCONNECTED_BLOCK, None
        if (
            len(block.finished_sub_slots) > 0
            and block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None
        ):
            assert block.finished_sub_slots[0].challenge_chain.new_difficulty is not None  # They both change together
            sub_slot_iters: uint64 = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
            difficulty: uint64 = block.finished_sub_slots[0].challenge_chain.new_difficulty
        else:
            sub_slot_iters = self._sub_slot_iters
            difficulty = self._difficulty
        required_iters, error = validate_finished_header_block(
            self.constants, self, block, False, difficulty, sub_slot_iters, False
        )
        if error is not None:
            return ReceiveBlockResult.INVALID_BLOCK, error.code
        if required_iters is None:
            return ReceiveBlockResult.INVALID_BLOCK, Err.INVALID_POSPACE

        block_record: BlockRecord = block_to_block_record(
            self.constants, self, required_iters, None, block, sub_slot_iters
        )
        self.add_block_record(block_record)
        if self._peak is None:
            if block_record.is_transaction_block:
                latest_timestamp = block_record.timestamp
            else:
                latest_timestamp = None
            self._height_to_hash[block_record.height] = block_record.header_hash
            await self.set_peak_block(block, latest_timestamp)
            return ReceiveBlockResult.NEW_PEAK, None
        elif block_record.weight > self._peak.weight:
            if block_record.prev_hash == self._peak.header_hash:
                fork_height: int = self._peak.height
            else:
                fork_height = find_fork_point_in_chain(self, block_record, self._peak)
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
            self.clean_block_records()
            return ReceiveBlockResult.NEW_PEAK, None
        return ReceiveBlockResult.ADDED_AS_ORPHAN, None

    async def _rollback_to_height(self, height: int):
        if self._peak is None:
            return
        for h in range(max(0, height + 1), self._peak.height + 1):
            del self._height_to_hash[uint32(h)]

        await self._basic_store.remove_object("PEAK_BLOCK")

    def get_peak_height(self) -> uint32:
        if self._peak is None:
            return uint32(0)
        return self._peak.height

    async def set_peak_block(self, block: HeaderBlock, timestamp: Optional[uint64] = None):
        await self._basic_store.set_object("PEAK_BLOCK", block)
        self._peak = block
        if timestamp is not None:
            self._latest_timestamp = timestamp
        elif block.foliage_transaction_block is not None:
            self._latest_timestamp = block.foliage_transaction_block.timestamp
        log.info(f"Peak set to : {self._peak.height} timestamp: {self._latest_timestamp}")

    async def get_peak_block(self) -> Optional[HeaderBlock]:
        if self._peak is not None:
            return self._peak
        return await self._basic_store.get_object("PEAK_BLOCK", HeaderBlock)

    def get_latest_timestamp(self) -> uint64:
        return self._latest_timestamp

    def contains_block(self, header_hash: bytes32) -> bool:
        return header_hash in self._block_records

    def contains_height(self, height: uint32) -> bool:
        return height in self._height_to_hash

    def height_to_hash(self, height: uint32) -> bytes32:
        return self._height_to_hash[height]

    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        if self.contains_block(header_hash):
            return self.block_record(header_hash)
        return None

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self._block_records[header_hash]

    def add_block_record(self, block_record: BlockRecord):
        self._block_records[block_record.header_hash] = block_record

    def clean_block_records(self):
        """
        Cleans the cache so that we only maintain relevant blocks. This removes
        block records that have height < peak - CACHE_SIZE.
        """
        height_limit = max(0, self.get_peak_height() - self.CACHE_SIZE)
        if len(self._block_records) < self.CACHE_SIZE:
            return None

        to_remove: List[bytes32] = []
        for header_hash, block_record in self._block_records.items():
            if block_record.height < height_limit:
                to_remove.append(header_hash)

        for header_hash in to_remove:
            del self._block_records[header_hash]
