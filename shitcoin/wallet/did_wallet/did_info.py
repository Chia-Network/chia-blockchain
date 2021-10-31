from dataclasses import dataclass
from typing import List, Optional, Tuple

from shitcoin.types.blockchain_format.sized_bytes import bytes32
from shitcoin.util.ints import uint64
from shitcoin.util.streamable import streamable, Streamable
from shitcoin.wallet.lineage_proof import LineageProof
from shitcoin.types.blockchain_format.program import Program
from shitcoin.types.blockchain_format.coin import Coin


@dataclass(frozen=True)
@streamable
class DIDInfo(Streamable):
    origin_coin: Optional[Coin]  # Coin ID of this coin is our DID
    backup_ids: List[bytes]
    num_of_backup_ids_needed: uint64
    parent_info: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): LineageProof}
    current_inner: Optional[Program]  # represents a Program as bytes
    temp_coin: Optional[Coin]  # partially recovered wallet uses these to hold info
    temp_puzhash: Optional[bytes32]
    temp_pubkey: Optional[bytes]
    sent_recovery_transaction: bool
