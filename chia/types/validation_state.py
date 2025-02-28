from __future__ import annotations

import dataclasses
from typing import Optional

from chia_rs.sized_ints import uint64

from chia.consensus.block_record import BlockRecord


@dataclasses.dataclass
class ValidationState:
    ssi: uint64
    difficulty: uint64
    prev_ses_block: Optional[BlockRecord] = None
