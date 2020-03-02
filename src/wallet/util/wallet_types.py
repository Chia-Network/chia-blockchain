from enum import Enum


class WalletType(Enum):
    # Condition Costs
    STANDARD_WALLET = 0
    RATE_LIMITED = 1
    ATOMIC_SWAP = 2
    AUTHORIZED_PAYEE = 3
    MULTI_SIG = 4
    CUSTODY = 5
    COLORED_COIN = 6
    RECOVERABLE = 7
