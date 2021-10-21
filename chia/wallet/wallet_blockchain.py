import asyncio
import logging
from typing import Dict, Optional, List
from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain_interface import BlockchainInterface
from chia.consensus.constants import ConsensusConstants
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.full_block_to_block_record import block_to_block_record
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import WeightProof
from chia.util.ints import uint32
from chia.wallet.key_val_store import KeyValStore

log = logging.getLogger(__name__)


class WalletBlockchain(BlockchainInterface):
    constants: ConsensusConstants
    constants_json: Dict
    # peak of the blockchain
    wallet_state_manager_lock: asyncio.Lock
    # Whether blockchain is shut down or not
    _shut_down: bool

    # Lock to prevent simultaneous reads and writes
    lock: asyncio.Lock
    log: logging.Logger
    basic_store: KeyValStore
    latest_tx_block: Optional[HeaderBlock]
    peak: Optional[HeaderBlock]
    peak_verified_by_peer: Dict[bytes32, HeaderBlock]  # Peer node id / Header block that we validated the weight for
    synced_weight_proof: Optional[WeightProof]
    recent_blocks_dict: Dict[bytes32, HeaderBlock]
    _height_to_hash: Dict[uint32, bytes32]
    _block_records: Dict[bytes32, BlockRecord]

    @staticmethod
    async def create(basic_store: KeyValStore, constants):
        """
        Initializes a blockchain with the BlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = WalletBlockchain()
        self.peak_verified_by_peer = {}
        self.basic_store = basic_store
        self.latest_tx_block = None
        self.latest_tx_block = await self.get_latest_tx_block()
        self.peak = None
        self.peak = await self.get_peak_block()
        self.synced_weight_proof = await self.get_stored_wp()
        self.recent_blocks_dict = {}
        self._height_to_hash = {}
        self._block_records = {}
        if self.synced_weight_proof is not None:
            await self.new_blocks(self.synced_weight_proof.recent_chain_data)
        self.constants = constants
        return self

    async def get_stored_wp(self):
        return await self.basic_store.get_object("SYNCED_WIEGHT_PROOF", WeightProof)

    async def new_weight_proof(self, weight_proof, summaries, block_records):
        self.synced_weight_proof = weight_proof
        await self.basic_store.set_object("SYNCED_WIEGHT_PROOF", weight_proof)

        self.synced_summaries = summaries
        for block in weight_proof.recent_chain_data:
            self.recent_blocks_dict[block.header_hash] = block
            self._height_to_hash[block.height] = block.header_hash
        for block_record in block_records:
            self._block_records[block_record.header_hash] = block_record

    async def new_blocks(self, recent_blocks):
        for block in recent_blocks:
            if block.height in self._height_to_hash:
                current_hash = self._height_to_hash[block.height]
                if current_hash in self.recent_blocks_dict:
                    self.recent_blocks_dict.pop(current_hash)

            self.recent_blocks_dict[block.header_hash] = block
            self._height_to_hash[block.height] = block.header_hash
            if self.peak is None or block.height > self.peak.height:
                await self.set_peak_block(block)

    async def rollback_to_height(self, height):
        pass

    def get_last_peak_from_peer(self, peer_node_id) -> Optional[HeaderBlock]:
        return self.peak_verified_by_peer.get(peer_node_id, None)

    def get_peak_height(self) -> uint32:
        if self.peak is None:
            return uint32(0)
        return self.peak.height

    async def set_latest_tx_block(self, block: HeaderBlock):
        await self.basic_store.set_object("LATEST_TX_BLOCK", block)
        self.latest_tx_block = block

    async def get_latest_tx_block(self) -> Optional[HeaderBlock]:
        """Used to show the synced status to the ui"""
        if self.latest_tx_block is not None:
            return self.latest_tx_block
        obj = await self.basic_store.get_object("LATEST_TX_BLOCK", HeaderBlock)
        return obj

    async def set_peak_block(self, block: HeaderBlock):
        await self.basic_store.set_object("PEAK_BLOCK", block)
        self.peak = block

    async def get_peak_block(self) -> Optional[HeaderBlock]:
        if self.peak is not None:
            return self.peak
        obj = await self.basic_store.get_object("PEAK_BLOCK", HeaderBlock)
        return obj

    def contains_block(self, header_hash: bytes32) -> bool:
        return header_hash in self._block_records

    def try_block_record(self, header_hash: bytes32) -> Optional[BlockRecord]:
        if self.contains_block(header_hash):
            return self.block_record(header_hash)
        return None

    def block_record(self, header_hash: bytes32) -> BlockRecord:
        return self._block_records[header_hash]

    def add_block_record(self, block_record: BlockRecord):
        self._block_records[block_record.header_hash] = block_record

    async def validate_blocks(self, blocks: List[HeaderBlock]) -> bool:
        for block in blocks:
            if block.height == 0:
                prev_b: Optional[BlockRecord] = None
                sub_slot_iters, difficulty = self.constants.SUB_SLOT_ITERS_STARTING, self.constants.DIFFICULTY_STARTING
            else:
                prev_b = self.block_record(block.prev_header_hash)
                sub_slot_iters, difficulty = get_next_sub_slot_iters_and_difficulty(
                    self.constants, len(block.finished_sub_slots) > 0, prev_b, self
                )
            required_iters, error = validate_finished_header_block(
                self.constants, self, block, False, difficulty, sub_slot_iters, False
            )
            if error is not None:
                return False
            if required_iters is None:
                return False
            block_record = block_to_block_record(
                self.constants,
                self,
                required_iters,
                None,
                block,
            )
            self.add_block_record(block_record)

        return True
