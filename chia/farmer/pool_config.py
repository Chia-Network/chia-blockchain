from dataclasses import dataclass

from blspy import G1Element, G2Element

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import streamable, Streamable


@dataclass(frozen=True)
@streamable
class PoolConfig(Streamable):
    """
    This is what goes into the user's config file, to communicate between the wallet and the farmer processes.
    """

    pool_url: str
    pool_payout_instructions: str
    target_puzzle_hash: bytes32
    singleton_genesis: bytes32
    owner_public_key: G1Element
    authentication_public_key: G1Element
    authentication_public_key_timestamp: uint64
    authentication_key_info_signature: G2Element
