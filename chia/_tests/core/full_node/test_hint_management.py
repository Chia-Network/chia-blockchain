from __future__ import annotations

from typing import List, Optional

import pytest

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block
from chia.consensus.block_record import BlockRecord
from chia.consensus.blockchain import Blockchain, StateChangeSummary
from chia.full_node.hint_management import get_hints_and_subscription_coin_ids
from chia.simulator.block_tools import BlockTools
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint32, uint64

coin_ids = [std_hash(i.to_bytes(4, "big")) for i in range(10)]
parent_ids = [std_hash(i.to_bytes(4, "big")) for i in range(10)]
phs = [std_hash(i.to_bytes(4, "big")) for i in range(10)]
removals = [(coin_ids[0], phs[0]), (coin_ids[2], phs[0]), (coin_ids[1], phs[7])]
additions = [
    (Coin(coin_ids[0], phs[2], uint64(123)), None),
    (Coin(coin_ids[0], phs[4], uint64(3)), b"1" * 32),
    (Coin(coin_ids[2], phs[7], uint64(123)), None),
    (Coin(coin_ids[2], phs[4], uint64(6)), None),
    (Coin(coin_ids[2], phs[9], uint64(123)), b"1" * 32),
    (Coin(coin_ids[1], phs[5], uint64(123)), None),
    (Coin(coin_ids[1], phs[6], uint64(5)), b"1" * 3),
]


def no_sub(c: bytes32) -> bool:
    return False


@pytest.mark.anyio
async def test_hints_to_add(bt: BlockTools, empty_blockchain: Blockchain) -> None:
    blocks = bt.get_consecutive_blocks(2)
    await _validate_and_add_block(empty_blockchain, blocks[0])
    await _validate_and_add_block(empty_blockchain, blocks[1])
    br: Optional[BlockRecord] = empty_blockchain.get_peak()
    assert br is not None

    scs = StateChangeSummary(br, uint32(0), [], removals, additions, [])
    hints_to_add, lookup_coin_ids = get_hints_and_subscription_coin_ids(scs, no_sub, no_sub)
    assert len(lookup_coin_ids) == 0

    first_coin_id: bytes32 = Coin(bytes32(coin_ids[0]), bytes32(phs[4]), uint64(3)).name()
    second_coin_id: bytes32 = Coin(bytes32(coin_ids[1]), bytes32(phs[6]), uint64(5)).name()
    third_coin_id: bytes32 = Coin(bytes32(coin_ids[2]), bytes32(phs[9]), uint64(123)).name()
    assert set(hints_to_add) == {(first_coin_id, b"1" * 32), (second_coin_id, b"1" * 3), (third_coin_id, b"1" * 32)}


@pytest.mark.anyio
async def test_lookup_coin_ids(bt: BlockTools, empty_blockchain: Blockchain) -> None:
    blocks = bt.get_consecutive_blocks(2)
    await _validate_and_add_block(empty_blockchain, blocks[0])
    await _validate_and_add_block(empty_blockchain, blocks[1])
    br: Optional[BlockRecord] = empty_blockchain.get_peak()
    assert br is not None

    rewards: List[Coin] = [
        Coin(coin_ids[8], phs[8], uint64(1)),
        Coin(coin_ids[9], phs[9], uint64(2)),
        Coin(coin_ids[5], phs[8], uint64(1234)),
    ]
    scs = StateChangeSummary(br, uint32(0), [], removals, additions, rewards)

    # Removal ID and addition PH
    has_coin_sub = lambda c: c == coin_ids[1]  # noqa: E731
    has_ph_sub = lambda ph: ph == phs[4]  # noqa: E731

    _, lookup_coin_ids = get_hints_and_subscription_coin_ids(scs, has_coin_sub, has_ph_sub)

    first_coin_id: bytes32 = Coin(bytes32(coin_ids[0]), bytes32(phs[4]), uint64(3)).name()
    second_coin_id: bytes32 = Coin(bytes32(coin_ids[2]), bytes32(phs[4]), uint64(6)).name()
    assert set(lookup_coin_ids) == {coin_ids[1], first_coin_id, second_coin_id}

    # Removal PH and addition ID
    has_coin_sub = lambda c: c == first_coin_id  # noqa: E731
    has_ph_sub = lambda ph: ph == phs[0]  # noqa: E731

    _, lookup_coin_ids = get_hints_and_subscription_coin_ids(scs, has_coin_sub, has_ph_sub)
    assert set(lookup_coin_ids) == {first_coin_id, coin_ids[0], coin_ids[2]}

    # Subscribe to hint
    third_coin_id: bytes32 = Coin(bytes32(coin_ids[2]), phs[9], uint64(123)).name()

    has_ph_sub = lambda ph: ph == bytes32(b"1" * 32)  # noqa: E731

    _, lookup_coin_ids = get_hints_and_subscription_coin_ids(scs, no_sub, has_ph_sub)
    assert set(lookup_coin_ids) == {first_coin_id, third_coin_id}

    # Reward PH
    has_ph_sub = lambda ph: ph == rewards[0].puzzle_hash  # noqa: E731

    _, lookup_coin_ids = get_hints_and_subscription_coin_ids(scs, no_sub, has_ph_sub)
    assert set(lookup_coin_ids) == {rewards[0].name(), rewards[2].name()}

    # Reward coin id + reward ph
    has_coin_sub = lambda c: c == rewards[1].name()  # noqa: E731

    _, lookup_coin_ids = get_hints_and_subscription_coin_ids(scs, has_coin_sub, has_ph_sub)
    assert set(lookup_coin_ids) == {rewards[1].name(), rewards[0].name(), rewards[2].name()}
