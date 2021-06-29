from dataclasses import dataclass
from typing import List, Optional

from blspy import G2Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.pool_target import PoolTarget
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@dataclass(frozen=True)
@streamable
class TransactionsInfo(Streamable):
    # Information that goes along with each transaction block
    generator_root: bytes32  # sha256 of the block generator in this block
    generator_refs_root: bytes32  # sha256 of the concatenation of the generator ref list entries
    aggregated_signature: G2Element
    fees: uint64  # This only includes user fees, not block rewards
    cost: uint64  # This is the total cost of running this block in the CLVM
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
    # The hash of this is the "header hash". Note that for unfinished blocks, the prev_block_hash
    # Is the prev from the signage point, and can be replaced with a more recent block
    prev_block_hash: bytes32
    reward_block_hash: bytes32
    foliage_block_data: FoliageBlockData
    foliage_block_data_signature: G2Element
    foliage_transaction_block_hash: Optional[bytes32]
    foliage_transaction_block_signature: Optional[G2Element]
