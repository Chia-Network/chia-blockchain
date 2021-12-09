from enum import Enum


class TradeStatus(Enum):
    """
    The order of these reflect their relevance.  PENDING_CONFIRM is the most relevant while CANCELLED is the least.
    """

    PENDING_CONFIRM = 0
    PENDING_CANCEL = 1
    PENDING_ACCEPT = 2
    CONFIRMED = 3
    FAILED = 4
    CANCELLED = 5
