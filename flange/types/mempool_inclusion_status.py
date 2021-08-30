from enum import IntEnum


class MempoolInclusionStatus(IntEnum):
    SUCCESS = 1  # Transaction added to mempool
    PENDING = 2  # Transaction not yet added to mempool
    FAILED = 3  # Transaction was invalid and dropped
