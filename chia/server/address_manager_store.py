from __future__ import annotations

import logging
from dataclasses import dataclass

from chia_rs.sized_ints import uint64

from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class PeerDataSerialization(Streamable):
    """
    Serializable property bag for the peer data that was previously stored in sqlite.
    """

    metadata: list[tuple[str, str]]
    nodes: list[tuple[uint64, str]]
    new_table: list[tuple[uint64, uint64]]
