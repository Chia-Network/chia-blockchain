from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.types.sized_bytes import bytes32
from src.util.ints import uint64
from src.util.streamable import streamable, Streamable
from src.wallet.cc_wallet.ccparent import CCParent
from src.types.program import Program
from src.types.coin import Coin


@dataclass(frozen=True)
@streamable
class DIDInfo(Streamable):
    my_did: Optional[bytes]
    backup_ids: List[bytes]
    num_of_backup_ids_needed: uint64
    parent_info: List[Tuple[bytes32, Optional[CCParent]]]  # {coin.name(): CCParent}
    current_inner: Optional[Program]  # represents a Program as bytes
    temp_coin: Optional[Coin]  # partially recovered wallet uses this to hold info
