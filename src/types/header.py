from dataclasses import dataclass

from blspy import PrependSignature

from src.types.sized_bytes import bytes32
from src.util.ints import uint64, uint32, uint128
from src.util.streamable import Streamable, streamable
from src.types.BLSSignature import BLSSignature
from src.types.pool_target import PoolTarget


@dataclass(frozen=True)
@streamable
class HeaderData(Streamable):
    height: uint32
    prev_header_hash: bytes32
    timestamp: uint64
    filter_hash: bytes32
    proof_of_space_hash: bytes32
    weight: uint128
    total_iters: uint64
    additions_root: bytes32
    removals_root: bytes32
    farmer_rewards_puzzle_hash: bytes32
    total_transaction_fees: uint64
    pool_target: PoolTarget
    aggregated_signature: BLSSignature
    cost: uint64
    extension_data: bytes32
    generator_hash: bytes32  # This needs to be a tree hash


@dataclass(frozen=True)
@streamable
class Header(Streamable):
    data: HeaderData
    harvester_signature: PrependSignature

    @property
    def height(self):
        return self.data.height

    @property
    def header_hash(self):
        return self.get_hash()

    @property
    def prev_header_hash(self) -> bytes32:
        return self.data.prev_header_hash

    @property
    def weight(self) -> uint128:
        return self.data.weight
