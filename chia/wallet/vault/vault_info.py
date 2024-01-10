from __future__ import annotations

from dataclasses import dataclass

from chia_rs import G1Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class VaultInfo(Streamable):
    coin: Coin
    launcher_id: bytes32
    pubkey: bytes
    hidden_puzzle_hash: bytes32
    inner_puzzle_hash: bytes32
    is_recoverable: bool


@dataclass(frozen=True)
class RecoveryInfo:
    bls_pk: G1Element
    timelock: uint64
