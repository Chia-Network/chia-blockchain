from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, TypeVar

from chia_rs.sized_ints import uint8, uint32

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
    VC = 13
    CRCAT = 57

    def to_json_dict(self) -> str:
        # yes, this isn't a `dict`, but it is json and
        # unfortunately the magic method name is misleading
        # not sure this code is used
        # TODO: determine if this code is used and if not, remove it
        return self.name


class CoinType(IntEnum):
    NORMAL = 0
    CLAWBACK = 1
    CRCAT_PENDING = 2
    CRCAT = 3


class RemarkDataType(IntEnum):
    NORMAL = 0
    CUSTODY = 1
    CLAWBACK = 2


T_contra = TypeVar("T_contra", contravariant=True)


@dataclass(frozen=True)
class WalletIdentifier:
    id: uint32
    type: WalletType

    @classmethod
    def create(cls, wallet: WalletProtocol[T_contra]) -> WalletIdentifier:
        return cls(wallet.id(), wallet.type())


# TODO, Can be replaced with WalletIdentifier if we have streamable enums
@streamable
@dataclass(frozen=True)
class StreamableWalletIdentifier(Streamable):
    id: uint32
    type: uint8
