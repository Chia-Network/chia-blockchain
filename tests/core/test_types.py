from __future__ import annotations

from dataclasses import replace

import pytest
from chia_rs import Coin, CoinState

from chia.types.block import BlockIdentifierTimed
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinInfo, CoinSpend, SpendInfo
from chia.util.ints import uint32, uint64

coin = Coin(bytes32(b"0" * 32), bytes32(b"1" * 32), uint64(0))


def test_coin_info() -> None:
    created_block = BlockIdentifierTimed(bytes32(b"2" * 32), uint32(1), uint64(2))
    spent_block = BlockIdentifierTimed(bytes32(b"3" * 32), uint32(2), uint64(3))
    spend_info = SpendInfo(SerializedProgram.from_bytes(b"4"), SerializedProgram.from_bytes(b"5"))
    coin_info = CoinInfo(
        coin=coin,
        created_block=created_block,
        spent_block=spent_block,
        spend_info=spend_info,
    )
    # Coin / Spend infos
    assert coin_info.coin == coin
    assert coin_info.spend_info == spend_info
    assert coin_info.puzzle == spend_info.puzzle
    assert coin_info.solution == spend_info.solution
    # Created infos
    assert coin_info.created_block == created_block
    assert coin_info.created_height == created_block.height
    assert coin_info.created_timestamp == created_block.timestamp
    # Spent infos
    assert coin_info.spent_block == spent_block
    assert coin_info.spent_height == spent_block.height
    assert coin_info.spent_timestamp == spent_block.timestamp
    # Helpers
    assert coin_info.to_coin_state() == CoinState(coin, coin_info.spent_height, coin_info.created_height)
    assert coin_info.to_coin_spend() == CoinSpend(coin, coin_info.puzzle, coin_info.solution)
    coin_info_none_blocks = replace(coin_info, created_block=None, spent_block=None)
    assert coin_info_none_blocks.to_coin_state() == CoinState(coin, None, None)


def test_coin_info_failures() -> None:
    coin_info = CoinInfo(
        coin=coin,
        created_block=None,
        spent_block=None,
        spend_info=None,
    )
    # Spend info
    with pytest.raises(ValueError, match="spend_info not available"):
        assert coin_info.puzzle
    with pytest.raises(ValueError, match="spend_info not available"):
        assert coin_info.solution
    # Blocks
    with pytest.raises(ValueError, match="created_block not available"):
        assert coin_info.created_height
    with pytest.raises(ValueError, match="spent_block not available"):
        assert coin_info.spent_height
    # Timestamps
    with pytest.raises(ValueError, match="created_block not available"):
        assert coin_info.created_timestamp
    with pytest.raises(ValueError, match="spent_block not available"):
        assert coin_info.spent_timestamp
