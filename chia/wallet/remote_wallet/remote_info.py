from __future__ import annotations

from dataclasses import dataclass

from chia_rs import CoinState
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16

from chia.types.blockchain_format.program import Program
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class RemoteInfo(Streamable):
    # Coin IDs that the remote wallet is tracking.
    remote_coin_ids: list[bytes32]


@streamable
@dataclass(frozen=True)
class RemoteCoinData(Streamable):
    p2_puzzle: Program
    recovery_list_hash: bytes32 | None
    num_verification: uint16
    singleton_struct: Program
    metadata: Program
    inner_puzzle: Program | None
    coin_state: CoinState

