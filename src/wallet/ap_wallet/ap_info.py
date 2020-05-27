from dataclasses import dataclass
from typing import List, Optional, Tuple
from src.types.sized_bytes import bytes32, bytes48, bytes96
from src.util.streamable import streamable, Streamable


@dataclass(frozen=True)
@streamable
class APInfo(Streamable):
    authoriser_pubkey: Optional[bytes48]
    my_pubkey: Optional[bytes48]
    contacts: Optional[
        List[Tuple[str, bytes32, bytes96]]
    ]  # list of (name, puzhash, BLSSig)
    change_signature: Optional[bytes96]
