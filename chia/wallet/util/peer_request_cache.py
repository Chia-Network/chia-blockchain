from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Set, Tuple

from chia.protocols.wallet_protocol import CoinState
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.header_block import HeaderBlock
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64
from chia.util.lru_cache import LRUCache


class PeerRequestCache:
    _blocks: LRUCache[uint32, HeaderBlock]  # height -> HeaderBlock
    _block_requests: LRUCache[Tuple[uint32, uint32], asyncio.Task[Any]]  # (start, end) -> Task
    _states_validated: LRUCache[bytes32, Optional[uint32]]  # coin state hash -> last change height, or None for reorg
    _timestamps: LRUCache[uint32, uint64]  # block height -> timestamp
    _blocks_validated: LRUCache[bytes32, uint32]  # header_hash -> height
    _block_signatures_validated: LRUCache[bytes32, uint32]  # sig_hash -> height
    _additions_in_block: LRUCache[Tuple[bytes32, bytes32], uint32]  # header_hash, puzzle_hash -> height
    # The wallet gets the state update before receiving the block. In untrusted mode the block is required for the
    # coin state validation, so we cache them before we apply them once we received the block.
    _race_cache: Dict[uint32, Set[CoinState]]

    def __init__(self) -> None:
        self._blocks = LRUCache(100)
        self._block_requests = LRUCache(300)
        self._states_validated = LRUCache(1000)
        self._timestamps = LRUCache(1000)
        self._blocks_validated = LRUCache(1000)
        self._block_signatures_validated = LRUCache(1000)
        self._additions_in_block = LRUCache(200)
        self._race_cache = {}

    def get_block(self, height: uint32) -> Optional[HeaderBlock]:
        return self._blocks.get(height)

    def add_to_blocks(self, header_block: HeaderBlock) -> None:
        self._blocks.put(header_block.height, header_block)
        if header_block.is_transaction_block:
            assert header_block.foliage_transaction_block is not None
            if self._timestamps.get(header_block.height) is None:
                self._timestamps.put(header_block.height, uint64(header_block.foliage_transaction_block.timestamp))

    def get_block_request(self, start: uint32, end: uint32) -> Optional[asyncio.Task[Any]]:
        return self._block_requests.get((start, end))

    def add_to_block_requests(self, start: uint32, end: uint32, request: asyncio.Task[Any]) -> None:
        self._block_requests.put((start, end), request)

    def in_states_validated(self, coin_state_hash: bytes32) -> bool:
        return self._states_validated.get(coin_state_hash) is not None

    def add_to_states_validated(self, coin_state: CoinState) -> None:
        cs_height: Optional[uint32] = None
        if coin_state.spent_height is not None:
            cs_height = uint32(coin_state.spent_height)
        elif coin_state.created_height is not None:
            cs_height = uint32(coin_state.created_height)
        self._states_validated.put(coin_state.get_hash(), cs_height)

    def get_height_timestamp(self, height: uint32) -> Optional[uint64]:
        return self._timestamps.get(height)

    def add_to_blocks_validated(self, reward_chain_hash: bytes32, height: uint32) -> None:
        self._blocks_validated.put(reward_chain_hash, height)

    def in_blocks_validated(self, reward_chain_hash: bytes32) -> bool:
        return self._blocks_validated.get(reward_chain_hash) is not None

    def add_to_block_signatures_validated(self, block: HeaderBlock) -> None:
        sig_hash: bytes32 = self._calculate_sig_hash_from_block(block)
        self._block_signatures_validated.put(sig_hash, block.height)

    @staticmethod
    def _calculate_sig_hash_from_block(block: HeaderBlock) -> bytes32:
        return std_hash(
            bytes(block.reward_chain_block.proof_of_space.plot_public_key)
            + bytes(block.foliage.foliage_block_data)
            + bytes(block.foliage.foliage_block_data_signature)
        )

    def in_block_signatures_validated(self, block: HeaderBlock) -> bool:
        sig_hash: bytes32 = self._calculate_sig_hash_from_block(block)
        return self._block_signatures_validated.get(sig_hash) is not None

    def add_to_additions_in_block(self, header_hash: bytes32, addition_ph: bytes32, height: uint32) -> None:
        self._additions_in_block.put((header_hash, addition_ph), height)

    def in_additions_in_block(self, header_hash: bytes32, addition_ph: bytes32) -> bool:
        return self._additions_in_block.get((header_hash, addition_ph)) is not None

    def add_states_to_race_cache(self, coin_states: List[CoinState]) -> None:
        for coin_state in coin_states:
            created_height = 0 if coin_state.created_height is None else coin_state.created_height
            spent_height = 0 if coin_state.spent_height is None else coin_state.spent_height
            max_height = uint32(max(created_height, spent_height))
            race_cache = self._race_cache.setdefault(max_height, set())
            race_cache.add(coin_state)

    def get_race_cache(self, height: int) -> Set[CoinState]:
        return self._race_cache[uint32(height)]

    def rollback_race_cache(self, *, fork_height: int) -> None:
        self._race_cache = {
            height: coin_states for height, coin_states in self._race_cache.items() if height <= fork_height
        }

    def cleanup_race_cache(self, *, min_height: int) -> None:
        self._race_cache = {
            height: coin_states for height, coin_states in self._race_cache.items() if height >= min_height
        }

    def clear_after_height(self, height: int) -> None:
        # Remove any cached item which relates to an event that happened at a height above height.
        new_blocks = LRUCache[uint32, HeaderBlock](self._blocks.capacity)
        for k, v in self._blocks.cache.items():
            if k <= height:
                new_blocks.put(k, v)
        self._blocks = new_blocks

        new_block_requests: LRUCache[Tuple[uint32, uint32], asyncio.Task[Any]] = LRUCache(self._block_requests.capacity)
        for (start_h, end_h), fetch_task in self._block_requests.cache.items():
            if start_h <= height and end_h <= height:
                new_block_requests.put((start_h, end_h), fetch_task)
        self._block_requests = new_block_requests

        new_states_validated: LRUCache[bytes32, Optional[uint32]] = LRUCache(self._states_validated.capacity)
        for cs_hash, cs_height in self._states_validated.cache.items():
            if cs_height is not None and cs_height <= height:
                new_states_validated.put(cs_hash, cs_height)
        self._states_validated = new_states_validated

        new_timestamps: LRUCache[uint32, uint64] = LRUCache(self._timestamps.capacity)
        for h, ts in self._timestamps.cache.items():
            if h <= height:
                new_timestamps.put(h, ts)
        self._timestamps = new_timestamps

        new_blocks_validated: LRUCache[bytes32, uint32] = LRUCache(self._blocks_validated.capacity)
        for hh, h in self._blocks_validated.cache.items():
            if h <= height:
                new_blocks_validated.put(hh, h)
        self._blocks_validated = new_blocks_validated

        new_block_signatures_validated: LRUCache[bytes32, uint32] = LRUCache(self._block_signatures_validated.capacity)
        for sig_hash, h in self._block_signatures_validated.cache.items():
            if h <= height:
                new_block_signatures_validated.put(sig_hash, h)
        self._block_signatures_validated = new_block_signatures_validated

        new_additions_in_block: LRUCache[Tuple[bytes32, bytes32], uint32] = LRUCache(self._additions_in_block.capacity)
        for (hh, ph), h in self._additions_in_block.cache.items():
            if h <= height:
                new_additions_in_block.put((hh, ph), h)
        self._additions_in_block = new_additions_in_block


def can_use_peer_request_cache(
    coin_state: CoinState, peer_request_cache: PeerRequestCache, fork_height: Optional[uint32]
) -> bool:
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
