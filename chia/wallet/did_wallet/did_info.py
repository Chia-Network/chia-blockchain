from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof


@streamable
@dataclass(frozen=True)
class DIDInfo(Streamable):
    origin_coin: Optional[Coin]  # Coin ID of this coin is our DID
    backup_ids: List[bytes32]
    num_of_backup_ids_needed: uint64
    parent_info: List[Tuple[bytes32, Optional[LineageProof]]]  # {coin.name(): LineageProof}
    current_inner: Optional[Program]  # represents a Program as bytes
    temp_coin: Optional[Coin]  # partially recovered wallet uses these to hold info
    temp_puzhash: Optional[bytes32]
    temp_pubkey: Optional[bytes]
    sent_recovery_transaction: bool
    metadata: str  # JSON of the user defined metadata


@streamable
@dataclass(frozen=True)
class DIDCoinData(Streamable):
    p2_puzzle: Program
    recovery_list_hash: bytes32
    num_verification: uint16
    singleton_struct: Program
    metadata: Program
    inner_puzzle: Optional[Program]
    coin_state: CoinState
