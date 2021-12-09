from enum import Enum


class TradeStatus(Enum):
    PENDING_ACCEPT = 0
    PENDING_CONFIRM = 1
    PENDING_CANCEL = 2
    CANCELED = 3
    CONFIRMED = 4
    FAILED = 5
