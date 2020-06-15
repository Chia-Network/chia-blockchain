from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.types.sized_bytes import bytes32
from src.util.streamable import streamable, Streamable
from src.wallet.cc_wallet.ccparent import CCParent


@dataclass(frozen=True)
@streamable
class DIDInfo(Streamable):
    my_id = Optional[str]
