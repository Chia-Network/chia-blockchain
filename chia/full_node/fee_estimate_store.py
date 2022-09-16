from typing import Optional

from chia.full_node.fee_history import FeeTrackerBackup


class FeeStore:
    """
    This object stores Fee Stats
    """

    backup: Optional[FeeTrackerBackup] = None

    @classmethod
    def create(cls) -> "FeeStore":
        self = cls()
        self.backup = None
        return self

    def get_stored_fee_data(self) -> Optional[FeeTrackerBackup]:
        return self.backup

    def store_fee_data(self, fee_backup: FeeTrackerBackup) -> None:
        self.backup = fee_backup
