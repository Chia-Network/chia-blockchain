from dataclasses import dataclass
from typing import List, Optional
from blspy import G2Element

from src.types.blockchain_format.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.streamable import Streamable, streamable
from src.types.blockchain_format.pool_target import PoolTarget
from src.types.blockchain_format.coin import Coin


@dataclass(frozen=True)
@streamable
class TransactionsInfo(Streamable):
    # Information that goes along with each transaction block
    previous_generators_root: bytes32  # This needs to be a tree hash
    generator_root: bytes32  # This needs to be a tree hash
    aggregated_signature: G2Element
    fees: uint64  # This only includes user fees, not block rewards
    cost: uint64
    reward_claims_incorporated: List[Coin]  # These can be in any order


@dataclass(frozen=True)
@streamable
class FoliageTransactionBlock(Streamable):
    # Information that goes along with each transaction block that is relevant for light clients
    prev_transaction_block_hash: bytes32
    timestamp: uint64
    filter_hash: bytes32
    additions_root: bytes32
    removals_root: bytes32
    transactions_info_hash: bytes32


@dataclass(frozen=True)
@streamable
class FoliageBlockData(Streamable):
    # Part of the block that is signed by the plot key
    unfinished_reward_block_hash: bytes32
    pool_target: PoolTarget
    pool_signature: Optional[G2Element]  # Iff ProofOfSpace has a pool pk
    farmer_reward_puzzle_hash: bytes32
    extension_data: bytes32  # Used for future updates. Can be any 32 byte value initially


@dataclass(frozen=True)
@streamable
class Foliage(Streamable):
    # The entire foliage block, containing signature and the unsigned back pointer
    # The hash of this is the "header hash"
    prev_block_hash: bytes32
    reward_block_hash: bytes32
    foliage_block_data: FoliageBlockData
    foliage_block_data_signature: G2Element
    foliage_transaction_block_hash: Optional[bytes32]
    foliage_transaction_block_signature: Optional[G2Element]
