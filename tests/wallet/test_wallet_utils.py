from __future__ import annotations

from typing import Callable, Collection, List, Optional, Protocol, Tuple, Union

import pytest
from chia_rs import Coin, CoinState

from chia.types.block import BlockIdentifierTimed
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinInfo
from chia.util.ints import uint32, uint64
from chia.wallet.util.wallet_sync_utils import sort_coin_infos, sort_coin_states


class CreationFunction(Protocol):
    def __call__(self, created_height: Optional[int], spent_height: Optional[int]) -> Union[CoinState, CoinInfo]:
        ...


CoinDataCollection = Collection[Union[CoinState, CoinInfo]]
HeightsFunction = Callable[[CoinDataCollection], List[Tuple[Optional[int], Optional[int]]]]
SortFunction = Callable[[CoinDataCollection], CoinDataCollection]


def dummy_coin_state(*, created_height: Optional[int], spent_height: Optional[int]) -> CoinState:
    return CoinState(Coin(bytes(b"0" * 32), bytes(b"0" * 32), 0), spent_height, created_height)


def dummy_coin_info(*, created_height: Optional[int], spent_height: Optional[int]) -> CoinInfo:
    created_block = (
        None if created_height is None else BlockIdentifierTimed(bytes32(b"0" * 32), uint32(created_height), uint64(0))
    )
    spent_block = (
        None if spent_height is None else BlockIdentifierTimed(bytes32(b"0" * 32), uint32(spent_height), uint64(0))
    )
    return CoinInfo(Coin(bytes(b"0" * 32), bytes(b"0" * 32), 0), created_block, spent_block, None)


def heights_coin_states(coin_states: Collection[CoinState]) -> List[Tuple[Optional[int], Optional[int]]]:
    return [(coin_state.created_height, coin_state.spent_height) for coin_state in coin_states]


def heights_coin_infos(coin_infos: List[CoinInfo]) -> List[Tuple[Optional[int], Optional[int]]]:
    heights = []
    for coin_info in coin_infos:
        created_height = None if coin_info.created_block is None else int(coin_info.created_height)
        spent_height = None if coin_info.created_block is None else int(coin_info.created_height)
        heights.append((created_height, spent_height))
    return heights


@pytest.mark.parametrize(
    "dummy_creation, heights, sort",
    [
        (dummy_coin_state, heights_coin_states, sort_coin_states),
        (dummy_coin_info, heights_coin_infos, sort_coin_infos),
    ],
)
def test_sort_coin_data(dummy_creation: CreationFunction, heights: HeightsFunction, sort: SortFunction) -> None:
    sorted_coin_data = [
        dummy_creation(created_height=None, spent_height=None),
        dummy_creation(created_height=1, spent_height=None),
        dummy_creation(created_height=9, spent_height=10),
        dummy_creation(created_height=10, spent_height=None),
        dummy_creation(created_height=10, spent_height=10),
        dummy_creation(created_height=10, spent_height=11),
        dummy_creation(created_height=11, spent_height=None),
        dummy_creation(created_height=11, spent_height=11),
        dummy_creation(created_height=10, spent_height=12),
        dummy_creation(created_height=11, spent_height=12),
        dummy_creation(created_height=12, spent_height=None),
        dummy_creation(created_height=12, spent_height=12),
        dummy_creation(created_height=1, spent_height=20),
        dummy_creation(created_height=19, spent_height=20),
    ]
    unsorted_coin_data = set(sorted_coin_data)
    assert heights(unsorted_coin_data) != heights(sorted_coin_data)
    assert heights(sort(unsorted_coin_data)) == heights(sorted_coin_data)
