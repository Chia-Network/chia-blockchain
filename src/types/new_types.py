from typing import Optional
from dataclasses import dataclass
from blspy import G2Element

from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32, uint128
from src.util.streamable import Streamable, streamable
from src.types.pool_target import PoolTarget
from src.types.proof_of_time import ProofOfTime
from src.types.proof_of_space import ProofOfSpace
from src.types.program import Program


@dataclass(frozen=True)
@streamable
class SubepochSummary(Streamable):
    prev_subepoch_summary_hash: bytes32
    info_hashes_hash: bytes32  # Hash of (final challenge block + hash of reward chain at end of last seg)
    num_subblocks: uint32
    new_difficulty: Optional[uint128]  # Only once per epoch (diff adjustment)
    new_ips: Optional[uint64]  # Only once per epoch (diff adjustment)


@dataclass(frozen=True)
@streamable
class ChallengeTrunkBlock(Streamable):
    height: uint32  # Tmp
    weight: uint128  # tmp
    total_iters: uint128  # tmp
    prev_challenge_trunk_block_hash: bytes32
    challenge_pot: ProofOfTime
    infusion_challenge_point_pot: ProofOfTime
    infusion_point_pot: Optional[ProofOfTime]
    proof_of_space: ProofOfSpace
    infusion_challenge_point_sig: G2Element
    subepoch_summary_hash: Optional[bytes32]


@dataclass(frozen=True)
@streamable
class RewardTrunkBlock(Streamable):
    challenge_hash: bytes32
    prev_reward_trunk_block_hash: bytes32
    proof_of_space: ProofOfSpace
    infusion_challenge_point_pot: ProofOfTime
    infusion_point_pot: Optional[ProofOfTime]
    infusion_challenge_point_sig: G2Element


@dataclass(frozen=True)
@streamable
class FoliageBlock(Streamable):
    timestamp: uint64
    filter_hash: bytes32
    additions_root: bytes32
    removals_root: bytes32
    previous_generators_root: bytes32  # This needs to be a tree hash
    generator_root: bytes32            # This needs to be a tree hash
    aggregated_signature: G2Element
    total_transaction_fees: uint64
    cost: uint64
    extension_data: bytes32


@dataclass(frozen=True)
@streamable
class FoliageSubblock(Streamable):
    height: uint32
    weight: uint128
    reward_trunk_block_hash: bytes32
    prev_signed_foliage_subblock_hash: Optional[bytes32]
    pool_target: PoolTarget
    pool_signature: G2Element
    farmer_reward_puzzle_hash: bytes32
    farmer_reward_amount: uint64
    foliage_block_hash: Optional[FoliageBlock]


@dataclass(frozen=True)
@streamable
class FoliageHeader(Streamable):
    prev_foliage_subblock_hash: bytes32
    foliage_subblock: FoliageSubblock
    foliage_block: Optional[FoliageBlock]
    foliage_subblock_signature: G2Element


@dataclass(frozen=True)
@streamable
class HeaderBlock(Streamable):
    challenge_trunk_block: Optional[ChallengeTrunkBlock]
    reward_trunk_block: RewardTrunkBlock
    header: FoliageHeader


@dataclass(frozen=True)
@streamable
class FullBlock(Streamable):
    challenge_trunk_block: Optional[ChallengeTrunkBlock]
    reward_trunk_block: RewardTrunkBlock
    header: FoliageHeader
    transactions_generator: Optional[Program]
    transactions_filter: bytes
