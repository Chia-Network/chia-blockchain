from __future__ import annotations

from dataclasses import dataclass

from chia_rs import CoinState
from chia_rs.sized_bytes import bytes32

from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class RemoteInfo(Streamable):
    # Coin IDs that the remote wallet is tracking.
    remote_coin_ids: list[bytes32]


@streamable
@dataclass(frozen=True)
class RemoteCoinData(Streamable):
    coin_state: CoinState
