from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

from chia.util.ints import uint8, uint32
from chia.util.streamable import Streamable, streamable

if TYPE_CHECKING:
    from chia.wallet.wallet_protocol import WalletProtocol


class WalletType(IntEnum):
    # Wallet Types
    STANDARD_WALLET = 0
    ATOMIC_SWAP = 2
    AUTHORIZED_PAYEE = 3
    MULTI_SIG = 4
    CUSTODY = 5
    CAT = 6
    RECOVERABLE = 7
    DECENTRALIZED_ID = 8
    POOLING_WALLET = 9
    NFT = 10
    DATA_LAYER = 11
    DATA_LAYER_OFFER = 12


class CoinType(IntEnum):
    NORMAL = 0
    CLAWBACK = 1


@dataclass(frozen=True)
class WalletIdentifier:
    id: uint32
    type: WalletType

    @classmethod
    def create(cls, wallet: WalletProtocol) -> WalletIdentifier:
        return cls(wallet.id(), wallet.type())


# TODO, Can be replaced with WalletIdentifier if we have streamable enums
@streamable
@dataclass(frozen=True)
class StreamableWalletIdentifier(Streamable):
    id: uint32
    type: uint8
