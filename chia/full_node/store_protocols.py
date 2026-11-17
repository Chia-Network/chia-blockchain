from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import NamedTuple

from chia.consensus.block_height_map import BlockHeightMap
from chia.consensus.block_store_protocol import BlockStoreProtocol
from chia.consensus.coin_store_protocol import CoinStoreProtocol
from chia.full_node.block_archive_protocol import BlockArchiveProtocol
from chia.full_node.explorer_store_protocol import ExplorerStoreProtocol


class NodeStores(NamedTuple):
    """
    The stores a FullNode runs on. For SQLite, the block and coin stores
    share one database and one transaction.
    """

    block_store: BlockStoreProtocol
    block_archive: BlockArchiveProtocol
    coin_store: CoinStoreProtocol
    hint_store: ExplorerStoreProtocol
    height_map: BlockHeightMap


# Opens the stores for the node's lifetime and closes them on exit.
OpenNodeStores = Callable[[], AbstractAsyncContextManager[NodeStores]]
