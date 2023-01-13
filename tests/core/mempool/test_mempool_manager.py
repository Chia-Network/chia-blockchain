from __future__ import annotations

from typing import Any, Awaitable, Callable, List, Optional, Tuple

import pytest
from blspy import G2Element

from chia.consensus.block_record import BlockRecord
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.mempool_manager import MempoolManager, compute_assert_height
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32, bytes100
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.types.spend_bundle_conditions import Spend, SpendBundleConditions
from chia.util.errors import Err, ValidationError
from chia.util.ints import uint8, uint32, uint64, uint128

IDENTITY_PUZZLE = Program.to(1)
IDENTITY_PUZZLE_HASH = IDENTITY_PUZZLE.get_tree_hash()

TEST_TIMESTAMP = uint64(1616108400)
TEST_COIN_AMOUNT = uint64(1000000000)
TEST_COIN = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT)
TEST_COIN_ID = TEST_COIN.name()
TEST_COIN_RECORD = CoinRecord(TEST_COIN, uint32(0), uint32(0), False, TEST_TIMESTAMP)
TEST_HEIGHT = uint32(1)


async def zero_calls_get_coin_record(_: bytes32) -> Optional[CoinRecord]:
    assert False


def create_test_block_record(*, height: uint32 = TEST_HEIGHT) -> BlockRecord:
    return BlockRecord(
        IDENTITY_PUZZLE_HASH,
        IDENTITY_PUZZLE_HASH,
        height,
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
        uint32(height - 1),
        TEST_TIMESTAMP,
        None,
        uint64(0),
        None,
        None,
        None,
        None,
        None,
    )


async def instantiate_mempool_manager(
    get_coin_record: Callable[[bytes32], Awaitable[Optional[CoinRecord]]]
) -> MempoolManager:
    mempool_manager = MempoolManager(get_coin_record, DEFAULT_CONSTANTS)
    test_block_record = create_test_block_record()
    await mempool_manager.new_peak(test_block_record, None)
    return mempool_manager


def test_compute_assert_height() -> None:

    c1 = Coin(bytes32(b"a" * 32), bytes32(b"b" * 32), 1337)
    coin_id = c1.name()
    confirmed_height = uint32(12)
    coin_records = {coin_id: CoinRecord(c1, confirmed_height, uint32(0), False, uint64(10000))}

    # 42 is the absolute height condition
    conds = SpendBundleConditions([Spend(coin_id, bytes32(b"c" * 32), None, 0, [], [], 0)], 0, 42, 0, [], 0)
    assert compute_assert_height(coin_records, conds) == 42

    # 1 is a relative height, but that only amounts to 13, so the absolute
    # height is more restrictive
    conds = SpendBundleConditions([Spend(coin_id, bytes32(b"c" * 32), 1, 0, [], [], 0)], 0, 42, 0, [], 0)
    assert compute_assert_height(coin_records, conds) == 42

    # 100 is a relative height, and sinec the coin was confirmed at height 12,
    # that's 112
    conds = SpendBundleConditions([Spend(coin_id, bytes32(b"c" * 32), 100, 0, [], [], 0)], 0, 42, 0, [], 0)
    assert compute_assert_height(coin_records, conds) == 112

    # Same thing but without the absolute height
    conds = SpendBundleConditions([Spend(coin_id, bytes32(b"c" * 32), 100, 0, [], [], 0)], 0, 0, 0, [], 0)
    assert compute_assert_height(coin_records, conds) == 112


def spend_bundle_from_conditions(conditions: List[List[Any]]) -> SpendBundle:
    solution = Program.to(conditions)
    coin_spend = CoinSpend(TEST_COIN, IDENTITY_PUZZLE, solution)
    return SpendBundle([coin_spend], G2Element())


async def add_spendbundle(
    mempool_manager: MempoolManager, sb: SpendBundle, sb_name: bytes32
) -> Tuple[Optional[uint64], MempoolInclusionStatus, Optional[Err]]:
    npc_result = await mempool_manager.pre_validate_spendbundle(sb, None, sb_name)
    return await mempool_manager.add_spend_bundle(sb, npc_result, sb_name, TEST_HEIGHT)


async def generate_and_add_spendbundle(
    mempool_manager: MempoolManager,
    conditions: List[List[Any]],
) -> Tuple[SpendBundle, bytes32, Tuple[Optional[uint64], MempoolInclusionStatus, Optional[Err]]]:
    sb = spend_bundle_from_conditions(conditions)
    sb_name = sb.name()
    result = await add_spendbundle(mempool_manager, sb, sb_name)
    return (sb, sb_name, result)


@pytest.mark.asyncio
async def test_empty_spend_bundle() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    sb = SpendBundle([], G2Element())
    with pytest.raises(ValidationError, match="Err.INVALID_SPEND_BUNDLE"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_negative_addition_amount() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, -1]]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="Err.COIN_AMOUNT_NEGATIVE"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_valid_addition_amount() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    max_amount = mempool_manager.constants.MAX_COIN_AMOUNT
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, max_amount]]
    sb = spend_bundle_from_conditions(conditions)
    npc_result = await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())
    assert npc_result.error is None


@pytest.mark.asyncio
async def test_too_big_addition_amount() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    max_amount = mempool_manager.constants.MAX_COIN_AMOUNT
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, max_amount + 1]]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="Err.COIN_AMOUNT_EXCEEDS_MAXIMUM"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_duplicate_output() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
    ]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="Err.DUPLICATE_OUTPUT"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_block_cost_exceeds_max() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    conditions = []
    for i in range(2400):
        conditions.append([ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, i])
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="Err.BLOCK_COST_EXCEEDS_MAX"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_double_spend_prevalidation() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    sb = spend_bundle_from_conditions(conditions)
    sb_twice: SpendBundle = SpendBundle.aggregate([sb, sb])
    with pytest.raises(ValidationError, match="Err.DOUBLE_SPEND"):
        await mempool_manager.pre_validate_spendbundle(sb_twice, None, sb_twice.name())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount,expected_status,expected_error",
    [
        (TEST_COIN_AMOUNT, MempoolInclusionStatus.SUCCESS, None),
        (TEST_COIN_AMOUNT + 1, MempoolInclusionStatus.FAILED, Err.MINTING_COIN),
    ],
)
async def test_minting_coin(
    amount: uint64,
    expected_status: MempoolInclusionStatus,
    expected_error: Optional[Err],
) -> None:
    async def get_coin_record(coin_id: bytes32) -> Optional[CoinRecord]:
        test_coin_records = {TEST_COIN_ID: TEST_COIN_RECORD}
        return test_coin_records.get(coin_id)

    mempool_manager = await instantiate_mempool_manager(get_coin_record)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, amount]]
    result = await generate_and_add_spendbundle(mempool_manager, conditions)
    _, status, error = result[2]
    assert status == expected_status
    assert error == expected_error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount,expected_status,expected_error",
    [
        (TEST_COIN_AMOUNT, MempoolInclusionStatus.SUCCESS, None),
        (TEST_COIN_AMOUNT + 1, MempoolInclusionStatus.FAILED, Err.RESERVE_FEE_CONDITION_FAILED),
    ],
)
async def test_reserve_fee_condition(
    amount: uint64,
    expected_status: MempoolInclusionStatus,
    expected_error: Optional[Err],
) -> None:
    async def get_coin_record(coin_id: bytes32) -> Optional[CoinRecord]:
        test_coin_records = {TEST_COIN_ID: TEST_COIN_RECORD}
        return test_coin_records.get(coin_id)

    mempool_manager = await instantiate_mempool_manager(get_coin_record)
    conditions = [[ConditionOpcode.RESERVE_FEE, amount]]
    result = await generate_and_add_spendbundle(mempool_manager, conditions)
    _, status, error = result[2]
    assert status == expected_status
    assert error == expected_error
