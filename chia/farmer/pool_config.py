from dataclasses import dataclass

from blspy import G1Element, G2Element

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.streamable import streamable, Streamable


@dataclass(frozen=True)
@streamable
class PoolConfig(Streamable):
    pool_url: str
    target: bytes32
    target_signature: G2Element
    pool_puzzle_hash: bytes32
    singleton_genesis: bytes32
    owner_public_key: G1Element
