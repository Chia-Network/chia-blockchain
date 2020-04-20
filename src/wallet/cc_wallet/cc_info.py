from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.types.sized_bytes import bytes32
from src.util.streamable import streamable, Streamable
from src.wallet.cc_wallet.ccparent import CCParent


@dataclass(frozen=True)
@streamable
class CCInfo(Streamable):
    my_core: Optional[str]  # core is stored as the disassembled string
    parent_info: List[Tuple[bytes32, Optional[CCParent]]]  # {coin.name(): CCParent}
    my_colour_name: Optional[str]
