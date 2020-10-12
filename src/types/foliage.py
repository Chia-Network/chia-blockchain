from dataclasses import dataclass
from typing import List
from blspy import G2Element

from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32
from src.util.streamable import Streamable, streamable
from src.types.pool_target import PoolTarget


@dataclass(frozen=True)
@streamable
class RewardClaim(Streamable):
    # The pool and farmer coinbase rewards, as they are included into transaction block
    transaction_height: uint32
    puzzle_hash: bytes32
    amount: uint64


@dataclass(frozen=True)
@streamable
class TransactionsInfo(Streamable):
    # Information that goes along with each transaction block
    previous_generators_root: bytes32  # This needs to be a tree hash
    generator_root: bytes32            # This needs to be a tree hash
    aggregated_signature: G2Element
    total_transaction_fees: uint64
    cost: uint64
    reward_claims_incorporated: List[RewardClaim]


@dataclass(frozen=True)
@streamable
class FoliageBlock(Streamable):
    # Information that goes along with each transaction block that is relevant for light clients
    prev_block_hash: bytes32
    timestamp: uint64
    filter_hash: bytes32
    additions_root: bytes32
    removals_root: bytes32
    transactions_info_hash: bytes32


@dataclass(frozen=True)
@streamable
class FoliageSubBlockData(Streamable):
    # Part of the sub-block that is signed by the plot key
    committing_prev_block_hash: bytes32
    reward_block_hash: bytes32
    pool_target: PoolTarget
    pool_signature: G2Element
    farmer_reward_puzzle_hash: bytes32
    farmer_reward_amount: uint64
    extension_data: bytes32
    transaction_block_hash: bytes32


@dataclass(frozen=True)
@streamable
class FoliageSubBlock(Streamable):
    # The entire sub-block, containing signature and the unsigned back pointer
    # The hash of this is the "block hash"
    prev_sub_block_hash: bytes32
    signed_data: FoliageSubBlockData
    plot_key_signature: G2Element
