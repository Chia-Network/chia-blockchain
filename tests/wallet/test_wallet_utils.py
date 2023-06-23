from __future__ import annotations

from typing import Collection, List, Optional, Tuple

from chia_rs import Coin, CoinState

from chia.wallet.util.wallet_sync_utils import sort_coin_states


def dummy_coin_state(*, created_height: Optional[int], spent_height: Optional[int]) -> CoinState:
    return CoinState(Coin(bytes(b"0" * 32), bytes(b"0" * 32), 0), spent_height, created_height)


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
