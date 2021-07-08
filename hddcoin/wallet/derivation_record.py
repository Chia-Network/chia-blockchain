from dataclasses import dataclass

from blspy import G1Element

from hddcoin.types.blockchain_format.sized_bytes import bytes32
from hddcoin.util.ints import uint32
from hddcoin.wallet.util.wallet_types import WalletType


@dataclass(frozen=True)
class DerivationRecord:
    """
    These are records representing a puzzle hash, which is generated from a
    public key, derivation index, and wallet type. Stored in the puzzle_store.
    """

    index: uint32
    puzzle_hash: bytes32
    pubkey: G1Element
    wallet_type: WalletType
    wallet_id: uint32
