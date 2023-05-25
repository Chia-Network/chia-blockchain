from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.lineage_proof import LineageProof


@dataclass(frozen=True)
class SingletonCoinRecord:
    """
    These are values that correspond to a singleton in the WalletSingletonStore
    """

    coin: Coin
    singleton_id: bytes32
    wallet_id: uint32
    inner_puzzle: Program
    inner_puzzle_hash: bytes32
    confirmed: bool
    confirmed_at_height: uint32
    spent_height: uint32
    lineage_proof: LineageProof
    custom_data: Optional[Dict[str, Any]]
    generation: uint32
    timestamp: uint64

    def name(self) -> bytes32:
        return self.coin.name()
