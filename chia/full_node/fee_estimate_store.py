from __future__ import annotations

import dataclasses
from typing import Optional

import typing_extensions

from chia.full_node.fee_history import FeeTrackerBackup


@typing_extensions.final
@dataclasses.dataclass
class FeeStore:
    """
    This object stores Fee Stats
    """

    _backup: Optional[FeeTrackerBackup] = None

    def get_stored_fee_data(self) -> Optional[FeeTrackerBackup]:
        return self._backup

    def store_fee_data(self, fee_backup: FeeTrackerBackup) -> None:
        self._backup = fee_backup
