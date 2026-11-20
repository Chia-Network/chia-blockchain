from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import NamedTuple, Protocol

from chia_rs import CoinRecord, FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.block_height_map import BlockHeightMap
from chia.consensus.block_store_protocol import BlockStoreProtocol
from chia.consensus.coin_store_protocol import CoinStoreProtocol
from chia.full_node.explorer_store_protocol import ExplorerStoreProtocol


class FullNodeBlockStoreProtocol(BlockStoreProtocol, Protocol):
    """
    The block store as FullNode, its peer API and its RPC use it: the
    consensus surface plus block archive reads and compactification.
    """

    async def get_full_block_bytes(self, header_hash: bytes32) -> bytes | None: ...

    async def get_full_blocks_at(self, heights: list[uint32]) -> list[FullBlock]: ...

    async def get_block_bytes_in_range(
        self,
        start: int,
        stop: int,
    ) -> list[bytes]: ...

    async def replace_proof(self, header_hash: bytes32, block: FullBlock) -> None: ...

    async def is_fully_compactified(self, header_hash: bytes32) -> bool | None: ...

    async def get_random_not_compactified(self, number: int) -> list[int]: ...

    async def count_compactified_blocks(self) -> int: ...

    async def count_uncompactified_blocks(self) -> int: ...


class FullNodeCoinStoreProtocol(CoinStoreProtocol, Protocol):
    """
    The coin store as FullNode, its peer API and its RPC use it: the
    consensus surface plus coin-ID lookups.
    """

    async def get_coin_record(self, coin_name: bytes32) -> CoinRecord | None: ...

    async def is_empty(self) -> bool: ...


class NodeStores(NamedTuple):
    """
    The stores a FullNode runs on. For SQLite, the block and coin stores
    share one database and one transaction.
    """

    block_store: FullNodeBlockStoreProtocol
    coin_store: FullNodeCoinStoreProtocol
    hint_store: ExplorerStoreProtocol
    height_map: BlockHeightMap


# Opens the stores for the node's lifetime and closes them on exit.
OpenNodeStores = Callable[[], AbstractAsyncContextManager[NodeStores]]
