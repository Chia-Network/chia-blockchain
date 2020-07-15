from enum import Enum

from src.util.ints import uint8


class WalletType(Enum):
    # Condition Costs
    STANDARD_WALLET = uint8(0)
    RATE_LIMITED = uint8(1)
    ATOMIC_SWAP = uint8(2)
    AUTHORIZED_PAYEE = uint8(3)
    MULTI_SIG = uint8(4)
    CUSTODY = uint8(5)
    COLOURED_COIN = uint8(6)
    RECOVERABLE = uint8(7)
