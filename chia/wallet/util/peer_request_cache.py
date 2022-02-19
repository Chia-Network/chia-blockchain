import asyncio
from typing import Optional

from chia.protocols.wallet_protocol import CoinState, RespondSESInfo
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.util.ints import uint32
from chia.util.lru_cache import LRUCache


class PeerRequestCache:
    _blocks: LRUCache  # height -> HeaderBlock
    _block_requests: LRUCache  # (start, end) -> RequestHeaderBlocks
    _ses_requests: LRUCache  # height -> Ses request
    _states_validated: LRUCache  # coin state hash -> last change height, or None for reorg

    def __init__(self):
        self._blocks = LRUCache(100)
        self._block_requests = LRUCache(100)
        self._ses_requests = LRUCache(100)
        self._states_validated = LRUCache(1000)

    def get_block(self, height: uint32) -> Optional[HeaderBlock]:
        return self._blocks.get(height)

    def add_to_blocks(self, header_block: HeaderBlock) -> None:
        self._blocks.put(header_block.height, header_block)

    def get_block_request(self, start: uint32, end: uint32) -> Optional[asyncio.Task]:
        return self._block_requests.get((start, end))

    def add_to_block_requests(self, start: uint32, end: uint32, request: asyncio.Task) -> None:
        self._block_requests.put((start, end), request)

    def get_ses_request(self, height: uint32) -> Optional[RespondSESInfo]:
        return self._ses_requests.get(height)

    def add_to_ses_requests(self, height: uint32, ses: RespondSESInfo) -> None:
        self._ses_requests.put(height, ses)

    def in_states_validated(self, coin_state_hash: bytes32) -> bool:
        return self._states_validated.get(coin_state_hash) is not None

    def add_to_states_validated(self, coin_state: CoinState) -> None:
        cs_height: Optional[uint32] = None
        if coin_state.spent_height is not None:
            cs_height = coin_state.spent_height
        elif coin_state.created_height is not None:
            cs_height = coin_state.created_height
        self._states_validated.put(coin_state.get_hash(), cs_height)

    def clear_after_height(self, height: int):
        # Remove any cached item which relates to an event that happened at a height above height.
        new_blocks = LRUCache(self._blocks.capacity)
        for k, v in self._blocks.cache.items():
            if k <= height:
                new_blocks.put(k, v)
        self._blocks = new_blocks

        new_block_requests = LRUCache(self._block_requests.capacity)
        for k, v in self._block_requests.cache.items():
            if k[0] <= height and k[1] <= height:
                new_block_requests.put(k, v)
        self._block_requests = new_block_requests

        new_ses_requests = LRUCache(self._ses_requests.capacity)
        for k, v in self._ses_requests.cache.items():
            if k <= height:
                new_ses_requests.put(k, v)
        self._ses_requests = new_ses_requests

        new_states_validated = LRUCache(self._states_validated.capacity)
        for k, cs_height in self._states_validated.cache.items():
            if cs_height is not None:
                new_states_validated.put(k, cs_height)
        self._states_validated = new_states_validated


async def can_use_peer_request_cache(
    coin_state: CoinState, peer_request_cache: PeerRequestCache, fork_height: Optional[uint32]
):
    if not peer_request_cache.in_states_validated(coin_state.get_hash()):
        return False
    if fork_height is None:
        return True
    if coin_state.created_height is None and coin_state.spent_height is None:
        # Performing a reorg
        return False
    if coin_state.created_height is not None and coin_state.created_height > fork_height:
        return False
    if coin_state.spent_height is not None and coin_state.spent_height > fork_height:
        return False
    return True
