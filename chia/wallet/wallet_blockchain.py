import asyncio
import logging
import pathlib
from typing import Dict, Optional, List
from chia.consensus.block_header_validation import validate_finished_header_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.constants import ConsensusConstants
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.full_block_to_block_record import block_to_block_record, header_block_to_sub_block_record
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.types.weight_proof import WeightProof
from chia.util.ints import uint32, uint64
from chia.wallet.key_val_store import KeyValStore
from chia.wallet.wallet_weight_proof_handler import WalletWeightProofHandler


class WalletBlockchain:
    constants: ConsensusConstants
    _basic_store: KeyValStore

    synced_weight_proof: Optional[WeightProof]

    _peak: Optional[HeaderBlock]
    _peak_verified_by_peer: Dict[bytes32, HeaderBlock]  # Peer node id / Header block that we validated the weight for
    _height_to_hash: Dict[uint32, bytes32]
    _block_records: Dict[bytes32, BlockRecord]
    _latest_timestamp: uint64

    @staticmethod
    async def create(_basic_store: KeyValStore, constants: ConsensusConstants):
        """
        Initializes a blockchain with the BlockRecords from disk, assuming they have all been
        validated. Uses the genesis block given in override_constants, or as a fallback,
        in the consensus constants config.
        """
        self = WalletBlockchain()
        self._basic_store = _basic_store

        self.constants = constants
        self.synced_weight_proof = await self._get_stored_wp()

        self._peak_verified_by_peer = {}
        self._peak = None
        self._peak = await self.get_peak_block()
        self._latest_timestamp = uint64(0)
        self._height_to_hash = {}
        self._block_records = {}
        if self.synced_weight_proof is not None:
            await self.new_weight_proof(self.synced_weight_proof)
        return self

    async def _get_stored_wp(self) -> Optional[WeightProof]:
        return await self._basic_store.get_object("SYNCED_WEIGHT_PROOF", WeightProof)

    async def new_weight_proof(self, weight_proof: WeightProof, weight_proof_handler: WalletWeightProofHandler) -> None:
        peak: Optional[HeaderBlock] = await self.get_peak_block()

        if peak is not None and weight_proof.recent_chain_data[-1].weight <= peak.weight:
            # No update, don't change anything
            return None
        self.synced_weight_proof = weight_proof
        await self._basic_store.set_object("SYNCED_WEIGHT_PROOF", weight_proof)

        for block in weight_proof.recent_chain_data:
            self._height_to_hash[block.height] = block.header_hash

        latest_timestamp = self._latest_timestamp

        success, _, _, records = await weight_proof_handler.validate_weight_proof(weight_proof, True)

        for record in records:
            self.add_block_record(record)
            if record.is_transaction_block and record.timestamp > latest_timestamp:
                latest_timestamp = record.timestamp

        await self.set_peak_block(weight_proof.recent_chain_data[-1], latest_timestamp)

    async def new_blocks(self, recent_blocks: List[HeaderBlock]):
        """
        Adds block to the chain and sets the new peak.
        NOTE: This assumes that blocks were already validated with validate_blocks method.
        """
        latest_timestamp = self._latest_timestamp
        for block in recent_blocks:
            self._height_to_hash[block.height] = block.header_hash
            if block.is_transaction_block and block.foliage_transaction_block.timestamp > latest_timestamp:
                latest_timestamp = block.foliage_transaction_block.timestamp

            if self._peak is None or block.height > self._peak.height:
                await self.set_peak_block(block, latest_timestamp)

    async def rollback_to_height(self, height: int):
        if self._peak is None:
            return
        for h in range(max(0, height), self._peak.height + 1):
            del self._height_to_hash[uint32(h)]
        if height == -1:
            await self._basic_store.remove_object("PEAK_BLOCK")
            self._peak = None
            self._latest_timestamp = uint64(0)
        else:
            await self.set_peak_block(self._height_to_hash[uint32(height)])

    def get_last_peak_from_peer(self, peer_node_id) -> Optional[HeaderBlock]:
        return self._peak_verified_by_peer.get(peer_node_id, None)

    def get_peak_height(self) -> uint32:
        if self._peak is None:
            return uint32(0)
        return self._peak.height

    async def set_peak_block(self, block: HeaderBlock, timestamp: Optional[uint64] = None):
        await self._basic_store.set_object("PEAK_BLOCK", block)
        self._peak = block
        if timestamp is not None:
            self._latest_timestamp = timestamp
        elif block.is_transaction_block:
            self._latest_timestamp = block.foliage_transaction_block.timestamp

    async def get_peak_block(self) -> Optional[HeaderBlock]:
        if self._peak is not None:
            return self._peak
        return await self._basic_store.get_object("PEAK_BLOCK", HeaderBlock)

    def get_latest_timestamp(self) -> uint64:
        return self._latest_timestamp

    def contains_block(self, header_hash: bytes32) -> bool:
        return header_hash in self._block_records

    def contains_height(self, height: uint32):
        return height in self._height_to_hash

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
                sub_slot_iters, difficulty = self.constants.SUB_SLOT_ITERS_STARTING, self.constants.DIFFICULTY_STARTING
            else:
                prev_b: Optional[BlockRecord] = self.try_block_record(block.prev_header_hash)
                if prev_b is None:
                    return False
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
            print(f"Validated: {block.height}")
            block_record = block_to_block_record(
                self.constants,
                self,
                required_iters,
                None,
                block,
            )
            self.add_block_record(block_record)

        return True
