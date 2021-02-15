from dataclasses import dataclass
from blspy import G1Element

from src.types.blockchain_format.sized_bytes import bytes32
from src.util.streamable import Streamable, streamable
from src.util.ints import uint32
from src.wallet.util.wallet_types import WalletType


@dataclass(frozen=True)
@streamable
class DerivationRecord(Streamable):
    """
    These are records representing a puzzle hash, which is generated from a
    public key, derivation index, and wallet type. Stored in the puzzle_store.
    """

    index: uint32
    puzzle_hash: bytes32
    pubkey: G1Element
    wallet_type: WalletType
    wallet_id: uint32
