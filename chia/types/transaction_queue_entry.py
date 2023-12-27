from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional, Tuple

from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err


@dataclass(frozen=True)
class TransactionQueueEntry:
    """
    A transaction received from peer. This is put into a queue, and not yet in the mempool.
    """

    transaction: SpendBundle = field(compare=False)
    transaction_bytes: Optional[bytes] = field(compare=False)
    spend_name: bytes32
    peer: Optional[WSChiaConnection] = field(compare=False)
    test: bool = field(compare=False)
    done: asyncio.Future[Tuple[MempoolInclusionStatus, Optional[Err]]] = field(
        default_factory=asyncio.Future,
        compare=False,
    )
