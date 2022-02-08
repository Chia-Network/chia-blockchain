from enum import IntEnum
from typing import List

from typing_extensions import TypedDict

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint64


class WalletType(IntEnum):
    # Wallet Types
    STANDARD_WALLET = 0
    RATE_LIMITED = 1
    ATOMIC_SWAP = 2
    AUTHORIZED_PAYEE = 3
    MULTI_SIG = 4
    CUSTODY = 5
    CAT = 6
    RECOVERABLE = 7
    DISTRIBUTED_ID = 8
    POOLING_WALLET = 9


class AmountWithPuzzlehash(TypedDict):
    amount: uint64
    puzzlehash: bytes32
    memos: List[bytes]
