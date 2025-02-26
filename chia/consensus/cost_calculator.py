from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from chia_rs.sized_ints import uint16

from chia.types.spend_bundle_conditions import SpendBundleConditions
from chia.util.streamable import Streamable, streamable


@streamable
@dataclass(frozen=True)
class NPCResult(Streamable):
    error: Optional[uint16]
    conds: Optional[SpendBundleConditions]
