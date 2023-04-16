from __future__ import annotations

from chia.util.ints import UInt32Enum


class TransactionType(UInt32Enum):
    INCOMING_TX = 0
    OUTGOING_TX = 1
    COINBASE_REWARD = 2
    FEE_REWARD = 3
    INCOMING_TRADE = 4
    OUTGOING_TRADE = 5
