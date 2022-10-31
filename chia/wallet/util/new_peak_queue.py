from __future__ import annotations

import asyncio
import dataclasses
from enum import IntEnum
from typing import Any, List

from chia.protocols.wallet_protocol import CoinStateUpdate, NewPeakWallet
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.sized_bytes import bytes32


class NewPeakQueueTypes(IntEnum):
    # Lower number means higher priority in the queue
    COIN_ID_SUBSCRIPTION = 1
    PUZZLE_HASH_SUBSCRIPTION = 2
    FULL_NODE_STATE_UPDATED = 3
    NEW_PEAK_WALLET = 4


@dataclasses.dataclass
class NewPeakItem:
    item_type: NewPeakQueueTypes
    data: Any

    def __lt__(self, other):
        if self.item_type != other.item_type:
            return self.item_type < other.item_type
        if self.item_type in {NewPeakQueueTypes.COIN_ID_SUBSCRIPTION, NewPeakQueueTypes.PUZZLE_HASH_SUBSCRIPTION}:
            return False  # All subscriptions are equal
        return self.data[0].height < other.data[0].height

    def __le__(self, other):
        if self.item_type != other.item_type:
            return self.item_type < other.item_type
        if self.item_type in {NewPeakQueueTypes.COIN_ID_SUBSCRIPTION, NewPeakQueueTypes.PUZZLE_HASH_SUBSCRIPTION}:
            return True  # All subscriptions are equal
        return self.data[0].height <= other.data[0].height

    def __gt__(self, other):
        if self.item_type != other.item_type:
            return self.item_type > other.item_type
        if self.item_type in {NewPeakQueueTypes.COIN_ID_SUBSCRIPTION, NewPeakQueueTypes.PUZZLE_HASH_SUBSCRIPTION}:
            return False  # All subscriptions are equal
        return self.data[0].height > other.data[0].height

    def __ge__(self, other):
        if self.item_type != other.item_type:
            return self.item_type > other.item_type
        if self.item_type in {NewPeakQueueTypes.COIN_ID_SUBSCRIPTION, NewPeakQueueTypes.PUZZLE_HASH_SUBSCRIPTION}:
            return True  # All subscriptions are equal
        return self.data[0].height >= other.data[0].height


class NewPeakQueue:
    def __init__(self, inner_queue: asyncio.PriorityQueue):
        self._inner_queue: asyncio.PriorityQueue = inner_queue
        self._pending_data_process_items: int = 0

    async def subscribe_to_coin_ids(self, coin_ids: List[bytes32]):
        self._pending_data_process_items += 1
        await self._inner_queue.put(NewPeakItem(NewPeakQueueTypes.COIN_ID_SUBSCRIPTION, coin_ids))

    async def subscribe_to_puzzle_hashes(self, puzzle_hashes: List[bytes32]):
        self._pending_data_process_items += 1
        await self._inner_queue.put(NewPeakItem(NewPeakQueueTypes.PUZZLE_HASH_SUBSCRIPTION, puzzle_hashes))

    async def full_node_state_updated(self, coin_state_update: CoinStateUpdate, peer: WSChiaConnection):
        self._pending_data_process_items += 1
        await self._inner_queue.put(NewPeakItem(NewPeakQueueTypes.FULL_NODE_STATE_UPDATED, (coin_state_update, peer)))

    async def new_peak_wallet(self, new_peak: NewPeakWallet, peer: WSChiaConnection):
        await self._inner_queue.put(NewPeakItem(NewPeakQueueTypes.NEW_PEAK_WALLET, (new_peak, peer)))

    async def get(self) -> NewPeakItem:
        item: NewPeakItem = await self._inner_queue.get()
        if item.item_type != NewPeakQueueTypes.NEW_PEAK_WALLET:
            self._pending_data_process_items -= 1
        return item

    def has_pending_data_process_items(self) -> bool:
        return self._pending_data_process_items > 0
