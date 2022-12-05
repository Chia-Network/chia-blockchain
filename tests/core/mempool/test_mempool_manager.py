from __future__ import annotations

from typing import Any, List, Optional

import pytest
import pytest_asyncio
from blspy import G2Element

from chia.consensus.block_record import BlockRecord
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.mempool_manager import MempoolManager
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32, bytes100
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import ValidationError
from chia.util.ints import uint8, uint32, uint64, uint128

IDENTITY_PUZZLE = Program.to(1)
IDENTITY_PUZZLE_HASH = IDENTITY_PUZZLE.get_tree_hash()

TEST_TIMESTAMP = uint64(1616108400)
TEST_COIN = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, uint64(1000000000))
TEST_COIN_ID = TEST_COIN.name()
TEST_COIN_RECORD = CoinRecord(TEST_COIN, uint32(0), uint32(0), False, TEST_TIMESTAMP)
TEST_COIN_RECORDS = {TEST_COIN_ID: TEST_COIN_RECORD}
TEST_HEIGHT = uint32(1)


async def get_coin_record(coin_id: bytes32) -> Optional[CoinRecord]:
    return TEST_COIN_RECORDS.get(coin_id)


@pytest_asyncio.fixture(scope="function")
async def mempool_manager() -> MempoolManager:
    mempool_manager = MempoolManager(get_coin_record, DEFAULT_CONSTANTS)
    test_block_record = BlockRecord(
        IDENTITY_PUZZLE_HASH,
        IDENTITY_PUZZLE_HASH,
        TEST_HEIGHT,
        uint128(0),
        uint128(0),
        uint8(0),
        ClassgroupElement(bytes100(b"0" * 100)),
        None,
        IDENTITY_PUZZLE_HASH,
        IDENTITY_PUZZLE_HASH,
        uint64(0),
        IDENTITY_PUZZLE_HASH,
        IDENTITY_PUZZLE_HASH,
        uint64(0),
        uint8(0),
        False,
        uint32(TEST_HEIGHT - 1),
        TEST_TIMESTAMP,
        None,
        uint64(0),
        None,
        None,
        None,
        None,
        None,
    )
    await mempool_manager.new_peak(test_block_record, None)
    return mempool_manager


def spend_bundle_from_conditions(conditions: List[List[Any]]) -> SpendBundle:
    solution = Program.to(conditions)
    coin_spend = CoinSpend(TEST_COIN, IDENTITY_PUZZLE, solution)
    return SpendBundle([coin_spend], G2Element())


@pytest.mark.asyncio
async def test_negative_addition_amount(mempool_manager: MempoolManager) -> None:
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, -1]]
    sb = spend_bundle_from_conditions(conditions)
    # chia_rs currently emits this instead of Err.COIN_AMOUNT_NEGATIVE
    # Addressed in https://github.com/Chia-Network/chia_rs/pull/99
    with pytest.raises(ValidationError, match="Err.INVALID_CONDITION"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_valid_addition_amount(mempool_manager: MempoolManager) -> None:
    max_amount = mempool_manager.constants.MAX_COIN_AMOUNT
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, max_amount]]
    sb = spend_bundle_from_conditions(conditions)
    npc_result = await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())
    assert npc_result.error is None


@pytest.mark.asyncio
async def test_too_big_addition_amount(mempool_manager: MempoolManager) -> None:
    max_amount = mempool_manager.constants.MAX_COIN_AMOUNT
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, max_amount + 1]]
    sb = spend_bundle_from_conditions(conditions)
    # chia_rs currently emits this instead of Err.COIN_AMOUNT_EXCEEDS_MAXIMUM
    # Addressed in https://github.com/Chia-Network/chia_rs/pull/99
    with pytest.raises(ValidationError, match="Err.INVALID_CONDITION"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())
