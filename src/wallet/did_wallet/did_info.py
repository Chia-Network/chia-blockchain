from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.types.sized_bytes import bytes32
from src.util.streamable import streamable, Streamable
from src.wallet.cc_wallet.ccparent import CCParent
from src.types.program import Program


@dataclass(frozen=True)
@streamable
class DIDInfo(Streamable):
    my_core: Optional[str]
    backup_ids: List[bytes]
    parent_info: List[Tuple[bytes32, Optional[CCParent]]]  # {coin.name(): CCParent}
    current_inner: Optional[Program]  # represents a Program as bytes
