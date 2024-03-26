from __future__ import annotations

from typing import Collection, Dict, List, Optional, Set, Tuple

import pytest
from chia_rs import Coin, CoinState

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.util.peer_request_cache import PeerRequestCache
from chia.wallet.util.wallet_sync_utils import sort_coin_states

coin_states = [
    CoinState(Coin(bytes32(b"\00" * 32), bytes32(b"\00" * 32), uint64(1)), None, None),
    CoinState(Coin(bytes32(b"\00" * 32), bytes32(b"\11" * 32), uint64(1)), None, uint32(1)),
    CoinState(Coin(bytes32(b"\00" * 32), bytes32(b"\22" * 32), uint64(1)), uint32(1), uint32(1)),
    CoinState(Coin(bytes32(b"\00" * 32), bytes32(b"\33" * 32), uint64(1)), uint32(1), uint32(1)),
    CoinState(Coin(bytes32(b"\00" * 32), bytes32(b"\44" * 32), uint64(1)), uint32(2), uint32(1)),
    CoinState(Coin(bytes32(b"\00" * 32), bytes32(b"\55" * 32), uint64(1)), uint32(2), uint32(2)),
    CoinState(Coin(bytes32(b"\00" * 32), bytes32(b"\66" * 32), uint64(1)), uint32(20), uint32(10)),
    CoinState(Coin(bytes32(b"\00" * 32), bytes32(b"\77" * 32), uint64(1)), None, uint32(20)),
]


def assert_race_cache(cache: PeerRequestCache, expected_entries: Dict[int, Set[CoinState]]) -> None:
    for i in range(100):
        if i in expected_entries:
            assert cache.get_race_cache(i) == expected_entries[i], f"failed for {i}"
        else:
            with pytest.raises(KeyError):
                cache.get_race_cache(i)


def dummy_coin_state(*, created_height: Optional[int], spent_height: Optional[int]) -> CoinState:
    return CoinState(
        Coin(bytes(b"0" * 32), bytes(b"0" * 32), uint64(0)),
        uint32.construct_optional(spent_height),
        uint32.construct_optional(created_height),
    )


def heights(coin_states: Collection[CoinState]) -> List[Tuple[Optional[int], Optional[int]]]:
    return [(coin_state.created_height, coin_state.spent_height) for coin_state in coin_states]


def test_sort_coin_states() -> None:
    sorted_coin_states = [
        dummy_coin_state(created_height=None, spent_height=None),
        dummy_coin_state(created_height=1, spent_height=None),
        dummy_coin_state(created_height=9, spent_height=10),
        dummy_coin_state(created_height=10, spent_height=None),
        dummy_coin_state(created_height=10, spent_height=10),
        dummy_coin_state(created_height=10, spent_height=11),
        dummy_coin_state(created_height=11, spent_height=None),
        dummy_coin_state(created_height=11, spent_height=11),
        dummy_coin_state(created_height=10, spent_height=12),
        dummy_coin_state(created_height=11, spent_height=12),
        dummy_coin_state(created_height=12, spent_height=None),
        dummy_coin_state(created_height=12, spent_height=12),
        dummy_coin_state(created_height=1, spent_height=20),
        dummy_coin_state(created_height=19, spent_height=20),
    ]
    unsorted_coin_states = set(sorted_coin_states.copy())
    assert heights(unsorted_coin_states) != heights(sorted_coin_states)
    assert heights(sort_coin_states(unsorted_coin_states)) == heights(sorted_coin_states)


def test_add_states_to_race_cache() -> None:
    cache = PeerRequestCache()
    expected_entries: Dict[int, Set[CoinState]] = {}
    assert_race_cache(cache, expected_entries)

    # Repeated adding of the same coin state should not have any impact
    expected_entries[0] = {coin_states[0]}
    for i in range(3):
        cache.add_states_to_race_cache(coin_states[0:1])
        assert_race_cache(cache, expected_entries)

    # Add a coin state with max height 1
    cache.add_states_to_race_cache(coin_states[1:2])
    expected_entries[1] = {coin_states[1]}
    assert_race_cache(cache, expected_entries)

    # Add two more with max height 1
    cache.add_states_to_race_cache(coin_states[2:4])
    expected_entries[1] = {*coin_states[1:4]}
    assert_race_cache(cache, expected_entries)

    # Add one with max height 2
    cache.add_states_to_race_cache(coin_states[4:5])
    expected_entries[2] = {coin_states[4]}
    assert_race_cache(cache, expected_entries)

    # Adding all again should add all the remaining states
    cache.add_states_to_race_cache(coin_states)
    expected_entries[0] = {coin_states[0]}
    expected_entries[2] = {*coin_states[4:6]}
    expected_entries[20] = {*coin_states[6:8]}
    assert_race_cache(cache, expected_entries)


def test_cleanup_race_cache() -> None:
    cache = PeerRequestCache()
    cache.add_states_to_race_cache(coin_states)
    expected_race_cache = {
        0: {coin_states[0]},
        1: {*coin_states[1:4]},
        2: {*coin_states[4:6]},
        20: {*coin_states[6:8]},
    }
    assert_race_cache(cache, expected_race_cache)
    # Should not have an impact because 0 is the min height
    cache.cleanup_race_cache(min_height=0)
    assert_race_cache(cache, expected_race_cache)
    # Drop all below 19
    cache.cleanup_race_cache(min_height=1)
    expected_race_cache.pop(0)
    assert_race_cache(cache, expected_race_cache)
    # Drop all below 19
    cache.cleanup_race_cache(min_height=19)
    expected_race_cache.pop(1)
    expected_race_cache.pop(2)
    assert_race_cache(cache, expected_race_cache)
    # This should clear the cache
    cache.cleanup_race_cache(min_height=100)
    expected_race_cache.clear()
    assert_race_cache(cache, expected_race_cache)


def test_rollback_race_cache() -> None:
    cache = PeerRequestCache()
    cache.add_states_to_race_cache(coin_states)
    expected_race_cache = {
        0: {coin_states[0]},
        1: {*coin_states[1:4]},
        2: {*coin_states[4:6]},
        20: {*coin_states[6:8]},
    }
    assert_race_cache(cache, expected_race_cache)
    # Should not have an impact because 20 is the max height
    cache.rollback_race_cache(fork_height=20)
    assert_race_cache(cache, expected_race_cache)
    # Drop all above 19
    cache.rollback_race_cache(fork_height=19)
    expected_race_cache.pop(20)
    assert_race_cache(cache, expected_race_cache)
    # Drop all above 0
    cache.rollback_race_cache(fork_height=0)
    expected_race_cache.pop(1)
    expected_race_cache.pop(2)
    assert_race_cache(cache, expected_race_cache)
    # This should clear the cache
    cache.rollback_race_cache(fork_height=-1)
    expected_race_cache.clear()
    assert_race_cache(cache, expected_race_cache)
