from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from chia_rs import G1Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.lineage_proof import LineageProof


@streamable
@dataclass(frozen=True)
class RecoveryInfo(Streamable):
    bls_pk: Optional[G1Element] = None
    timelock: Optional[uint64] = None


@streamable
@dataclass(frozen=True)
class VaultInfo(Streamable):
    coin: Coin
    pubkey: bytes
    hidden_puzzle_hash: bytes32
    inner_puzzle_hash: bytes32
    lineage_proof: LineageProof
    is_recoverable: bool
    recovery_info: RecoveryInfo
