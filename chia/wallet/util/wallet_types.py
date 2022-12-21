from __future__ import annotations

from enum import IntEnum
from typing import List

from typing_extensions import TypedDict

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64


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


class AmountWithPuzzlehash(TypedDict):
    amount: uint64
    puzzlehash: bytes32
    memos: List[bytes]
