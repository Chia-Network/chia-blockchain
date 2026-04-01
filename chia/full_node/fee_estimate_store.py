from __future__ import annotations

import dataclasses

import typing_extensions

from chia.full_node.fee_history import FeeTrackerBackup


@typing_extensions.final
@dataclasses.dataclass
class FeeStore:
    """
    This object stores Fee Stats
    """

    _backup: FeeTrackerBackup | None = None

    def get_stored_fee_data(self) -> FeeTrackerBackup | None:
        return self._backup

    def store_fee_data(self, fee_backup: FeeTrackerBackup) -> None:
        self._backup = fee_backup
