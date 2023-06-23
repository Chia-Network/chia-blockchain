from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from typing_extensions import Protocol

from chia.consensus.constants import ConsensusConstants
from chia.consensus.pot_iterations import calculate_ip_iters, calculate_sp_iters
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.streamable import Streamable, streamable


class BlockRecordProtocol(Protocol):
    @property
    def header_hash(self) -> bytes32:
        ...

    @property
    def height(self) -> uint32:
        ...

    @property
    def timestamp(self) -> Optional[uint64]:
        ...

    @property
    def prev_transaction_block_height(self) -> uint32:
        ...

    @property
    def prev_transaction_block_hash(self) -> Optional[bytes32]:
        ...

    @property
    def is_transaction_block(self) -> bool:
        return self.timestamp is not None


@streamable
@dataclass(frozen=True)
class BlockRecordDB(Streamable):
    """
    This class contains the fields from `BlockRecord` that get stored in the DB.
    Unlike `BlockRecord`, this should never extend with more fields, in order to avoid DB corruption.
    """
    header_hash: bytes32
    prev_hash: bytes32
    height: uint32
    weight: uint128
    total_iters: uint128
    signage_point_index: uint8
    challenge_vdf_output: ClassgroupElement
    infused_challenge_vdf_output: Optional[ClassgroupElement]
    reward_infusion_new_challenge: bytes32
    challenge_block_info_hash: bytes32
    sub_slot_iters: uint64
    pool_puzzle_hash: bytes32
    farmer_puzzle_hash: bytes32
    required_iters: uint64
    deficit: uint8
    overflow: bool
    prev_transaction_block_height: uint32
    timestamp: Optional[uint64]
    prev_transaction_block_hash: Optional[bytes32]
    fees: Optional[uint64]
    reward_claims_incorporated: Optional[List[Coin]]
    finished_challenge_slot_hashes: Optional[List[bytes32]]
    finished_infused_challenge_slot_hashes: Optional[List[bytes32]]
    finished_reward_slot_hashes: Optional[List[bytes32]]
    sub_epoch_summary_included: Optional[SubEpochSummary]


@streamable
@dataclass(frozen=True)
class BlockRecord(Streamable):
    """
    This class is not included or hashed into the blockchain, but it is kept in memory as a more
    efficient way to maintain data about the blockchain. This allows us to validate future blocks,
    difficulty adjustments, etc, without saving the whole header block in memory.
    """

    header_hash: bytes32
    prev_hash: bytes32  # Header hash of the previous block
    height: uint32
    weight: uint128  # Total cumulative difficulty of all ancestor blocks since genesis
    total_iters: uint128  # Total number of VDF iterations since genesis, including this block
    signage_point_index: uint8
    challenge_vdf_output: ClassgroupElement  # This is the intermediary VDF output at ip_iters in challenge chain
    infused_challenge_vdf_output: Optional[
        ClassgroupElement
    ]  # This is the intermediary VDF output at ip_iters in infused cc, iff deficit <= 3
    reward_infusion_new_challenge: bytes32  # The reward chain infusion output, input to next VDF
    challenge_block_info_hash: bytes32  # Hash of challenge chain data, used to validate end of slots in the future
    sub_slot_iters: uint64  # Current network sub_slot_iters parameter
    pool_puzzle_hash: bytes32  # Need to keep track of these because Coins are created in a future block
    farmer_puzzle_hash: bytes32
    required_iters: uint64  # The number of iters required for this proof of space
    deficit: uint8  # A deficit of 16 is an overflow block after an infusion. Deficit of 15 is a challenge block
    overflow: bool
    prev_transaction_block_height: uint32
    pos_ss_cc_challenge_hash: bytes32
    cc_sp_hash: bytes32

    # Transaction block (present iff is_transaction_block)
    timestamp: Optional[uint64]
    prev_transaction_block_hash: Optional[bytes32]  # Header hash of the previous transaction block
    fees: Optional[uint64]
    reward_claims_incorporated: Optional[List[Coin]]

    # Slot (present iff this is the first SB in sub slot)
    finished_challenge_slot_hashes: Optional[List[bytes32]]
    finished_infused_challenge_slot_hashes: Optional[List[bytes32]]
    finished_reward_slot_hashes: Optional[List[bytes32]]

    # Sub-epoch (present iff this is the first SB after sub-epoch)
    sub_epoch_summary_included: Optional[SubEpochSummary]

    @property
    def is_transaction_block(self) -> bool:
        return self.timestamp is not None

    @property
    def first_in_sub_slot(self) -> bool:
        return self.finished_challenge_slot_hashes is not None

    def is_challenge_block(self, constants: ConsensusConstants) -> bool:
        return self.deficit == constants.MIN_BLOCKS_PER_CHALLENGE_BLOCK - 1

    def sp_sub_slot_total_iters(self, constants: ConsensusConstants) -> uint128:
        if self.overflow:
            return uint128(self.total_iters - self.ip_iters(constants) - self.sub_slot_iters)
        else:
            return uint128(self.total_iters - self.ip_iters(constants))

    def ip_sub_slot_total_iters(self, constants: ConsensusConstants) -> uint128:
        return uint128(self.total_iters - self.ip_iters(constants))

    def sp_iters(self, constants: ConsensusConstants) -> uint64:
        return calculate_sp_iters(constants, self.sub_slot_iters, self.signage_point_index)

    def ip_iters(self, constants: ConsensusConstants) -> uint64:
        return calculate_ip_iters(
            constants,
            self.sub_slot_iters,
            self.signage_point_index,
            self.required_iters,
        )

    def sp_total_iters(self, constants: ConsensusConstants) -> uint128:
        return uint128(self.sp_sub_slot_total_iters(constants) + self.sp_iters(constants))

    def to_block_record_db(self) -> BlockRecordDB:
        return BlockRecordDB(
            header_hash=self.header_hash,
            prev_hash=self.prev_hash,
            height=self.height,
            weight=self.weight,
            total_iters=self.total_iters,
            signage_point_index=self.signage_point_index,
            challenge_vdf_output=self.challenge_vdf_output,
            infused_challenge_vdf_output=self.infused_challenge_vdf_output,
            reward_infusion_new_challenge=self.reward_infusion_new_challenge,
            challenge_block_info_hash=self.challenge_block_info_hash,
            sub_slot_iters=self.sub_slot_iters,
            pool_puzzle_hash=self.pool_puzzle_hash,
            farmer_puzzle_hash=self.farmer_puzzle_hash,
            required_iters=self.required_iters,
            deficit=self.deficit,
            overflow=self.overflow,
            prev_transaction_block_height=self.prev_transaction_block_height,
            timestamp=self.timestamp,
            prev_transaction_block_hash=self.prev_transaction_block_hash,
            fees=self.fees,
            reward_claims_incorporated=self.reward_claims_incorporated,
            finished_challenge_slot_hashes=self.finished_challenge_slot_hashes,
            finished_infused_challenge_slot_hashes=self.finished_infused_challenge_slot_hashes,
            finished_reward_slot_hashes=self.finished_reward_slot_hashes,
            sub_epoch_summary_included=self.sub_epoch_summary_included,
        )

    @classmethod
    def from_block_record_db(
        cls, block_record_db: BlockRecordDB, pos_ss_cc_challenge_hash: bytes32, cc_sp_hash: bytes32
    ) -> BlockRecord:
        return cls(
            header_hash=block_record_db.header_hash,
            prev_hash=block_record_db.prev_hash,
            height=block_record_db.height,
            weight=block_record_db.weight,
            total_iters=block_record_db.total_iters,
            signage_point_index=block_record_db.signage_point_index,
            challenge_vdf_output=block_record_db.challenge_vdf_output,
            infused_challenge_vdf_output=block_record_db.infused_challenge_vdf_output,
            reward_infusion_new_challenge=block_record_db.reward_infusion_new_challenge,
            challenge_block_info_hash=block_record_db.challenge_block_info_hash,
            sub_slot_iters=block_record_db.sub_slot_iters,
            pool_puzzle_hash=block_record_db.pool_puzzle_hash,
            farmer_puzzle_hash=block_record_db.farmer_puzzle_hash,
            required_iters=block_record_db.required_iters,
            deficit=block_record_db.deficit,
            overflow=block_record_db.overflow,
            prev_transaction_block_height=block_record_db.prev_transaction_block_height,
            pos_ss_cc_challenge_hash=pos_ss_cc_challenge_hash,
            cc_sp_hash=cc_sp_hash,
            timestamp=block_record_db.timestamp,
            prev_transaction_block_hash=block_record_db.prev_transaction_block_hash,
            fees=block_record_db.fees,
            reward_claims_incorporated=block_record_db.reward_claims_incorporated,
            finished_challenge_slot_hashes=block_record_db.finished_challenge_slot_hashes,
            finished_infused_challenge_slot_hashes=block_record_db.finished_infused_challenge_slot_hashes,
            finished_reward_slot_hashes=block_record_db.finished_reward_slot_hashes,
            sub_epoch_summary_included=block_record_db.sub_epoch_summary_included,
        )
