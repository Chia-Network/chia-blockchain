from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import pytest
from blspy import G1Element, G2Element
from chiabip158 import PyBIP158

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.mempool_check_conditions import mempool_check_time_locks
from chia.full_node.mempool_manager import MempoolManager, compute_assert_height
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.types.spend_bundle_conditions import Spend, SpendBundleConditions
from chia.util.errors import Err, ValidationError
from chia.util.ints import uint32, uint64

IDENTITY_PUZZLE = Program.to(1)
IDENTITY_PUZZLE_HASH = IDENTITY_PUZZLE.get_tree_hash()

TEST_TIMESTAMP = uint64(10040)
TEST_COIN_AMOUNT = uint64(1000000000)
TEST_COIN = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT)
TEST_COIN_ID = TEST_COIN.name()
TEST_COIN_RECORD = CoinRecord(TEST_COIN, uint32(0), uint32(0), False, TEST_TIMESTAMP)
TEST_COIN_AMOUNT2 = uint64(2000000000)
TEST_COIN2 = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT2)
TEST_COIN_ID2 = TEST_COIN2.name()
TEST_COIN_RECORD2 = CoinRecord(TEST_COIN2, uint32(0), uint32(0), False, TEST_TIMESTAMP)
TEST_COIN_AMOUNT3 = uint64(3000000000)
TEST_COIN3 = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT3)
TEST_COIN_ID3 = TEST_COIN3.name()
TEST_COIN_RECORD3 = CoinRecord(TEST_COIN3, uint32(0), uint32(0), False, TEST_TIMESTAMP)
TEST_HEIGHT = uint32(5)


@dataclass(frozen=True)
class TestBlockRecord:
    """
    This is a subset of BlockRecord that the mempool manager uses for peak.
    """

    header_hash: bytes32
    height: uint32
    timestamp: Optional[uint64]
    prev_transaction_block_height: uint32
    prev_transaction_block_hash: Optional[bytes32]

    @property
    def is_transaction_block(self) -> bool:
        return self.timestamp is not None


async def zero_calls_get_coin_record(_: bytes32) -> Optional[CoinRecord]:
    assert False


async def get_coin_record_for_test_coins(coin_id: bytes32) -> Optional[CoinRecord]:
    test_coin_records = {
        TEST_COIN_ID: TEST_COIN_RECORD,
        TEST_COIN_ID2: TEST_COIN_RECORD2,
        TEST_COIN_ID3: TEST_COIN_RECORD3,
    }
    return test_coin_records.get(coin_id)


def height_hash(height: int) -> bytes32:
    return bytes32(height.to_bytes(32, byteorder="big"))


def create_test_block_record(*, height: uint32 = TEST_HEIGHT, timestamp: uint64 = TEST_TIMESTAMP) -> TestBlockRecord:
    return TestBlockRecord(
        header_hash=height_hash(height),
        height=height,
        timestamp=timestamp,
        prev_transaction_block_height=uint32(height - 1),
        prev_transaction_block_hash=height_hash(height - 1),
    )


async def instantiate_mempool_manager(
    get_coin_record: Callable[[bytes32], Awaitable[Optional[CoinRecord]]],
    *,
    current_block_height: uint32 = TEST_HEIGHT,
    current_block_timestamp: uint64 = TEST_TIMESTAMP,
) -> MempoolManager:
    mempool_manager = MempoolManager(get_coin_record, DEFAULT_CONSTANTS)
    test_block_record = create_test_block_record(height=current_block_height, timestamp=current_block_timestamp)
    await mempool_manager.new_peak(test_block_record, None)
    return mempool_manager


def make_test_conds(
    *,
    birth_height: Optional[int] = None,
    birth_seconds: Optional[int] = None,
    height_relative: Optional[int] = None,
    height_absolute: int = 0,
    seconds_relative: int = 0,
    seconds_absolute: int = 0,
) -> SpendBundleConditions:
    return SpendBundleConditions(
        [
            Spend(
                TEST_COIN.name(),
                IDENTITY_PUZZLE_HASH,
                uint32(height_relative) if height_relative else None,
                uint64(seconds_relative),
                None,
                None,
                uint32(birth_height) if birth_height else None,
                uint64(birth_seconds) if birth_seconds else None,
                [],
                [],
                0,
            )
        ],
        0,
        uint32(height_absolute),
        uint64(seconds_absolute),
        None,
        None,
        [],
        0,
        0,
        0,
    )


class TestCheckTimeLocks:
    COIN_CONFIRMED_HEIGHT = uint32(10)
    COIN_TIMESTAMP = uint64(10000)
    PREV_BLOCK_HEIGHT = uint32(15)
    PREV_BLOCK_TIMESTAMP = uint64(10150)

    COIN_RECORD = CoinRecord(
        TEST_COIN,
        confirmed_block_index=uint32(COIN_CONFIRMED_HEIGHT),
        spent_block_index=uint32(0),
        coinbase=False,
        timestamp=COIN_TIMESTAMP,
    )
    REMOVALS: Dict[bytes32, CoinRecord] = {TEST_COIN.name(): COIN_RECORD}

    @pytest.mark.parametrize(
        "conds,expected",
        [
            (make_test_conds(height_relative=5), None),
            (make_test_conds(height_relative=6), Err.ASSERT_HEIGHT_RELATIVE_FAILED),
            (make_test_conds(height_absolute=15), None),
            (make_test_conds(height_absolute=16), Err.ASSERT_HEIGHT_ABSOLUTE_FAILED),
            (make_test_conds(seconds_relative=150), None),
            (make_test_conds(seconds_relative=151), Err.ASSERT_SECONDS_RELATIVE_FAILED),
            (make_test_conds(seconds_absolute=10150), None),
            (make_test_conds(seconds_absolute=10151), Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
            # the coin's confirmed height is 10
            (make_test_conds(birth_height=9), Err.ASSERT_MY_BIRTH_HEIGHT_FAILED),
            (make_test_conds(birth_height=10), None),
            (make_test_conds(birth_height=11), Err.ASSERT_MY_BIRTH_HEIGHT_FAILED),
            # coin timestamp is 10000
            (make_test_conds(birth_seconds=9999), Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            (make_test_conds(birth_seconds=10000), None),
            (make_test_conds(birth_seconds=10001), Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
        ],
    )
    def test_conditions(
        self,
        conds: SpendBundleConditions,
        expected: Optional[Err],
    ) -> None:
        assert (
            mempool_check_time_locks(self.REMOVALS, conds, self.PREV_BLOCK_HEIGHT, self.PREV_BLOCK_TIMESTAMP)
            == expected
        )


def expect(*, height: int = 0) -> uint32:
    return uint32(height)


@pytest.mark.parametrize(
    "conds,expected",
    [
        # coin birth height is 12
        (make_test_conds(), expect()),
        (make_test_conds(height_absolute=42), expect(height=42)),
        # 1 is a relative height, but that only amounts to 13, so the absolute
        # height is more restrictive
        (make_test_conds(height_relative=1), expect(height=13)),
        # 100 is a relative height, and sinec the coin was confirmed at height 12,
        # that's 112
        (make_test_conds(height_absolute=42, height_relative=100), expect(height=112)),
        # Same thing but without the absolute height
        (make_test_conds(height_relative=100), expect(height=112)),
    ],
)
def test_compute_assert_height(conds: SpendBundleConditions, expected: uint32) -> None:
    coin_id = TEST_COIN.name()
    confirmed_height = uint32(12)
    coin_records = {coin_id: CoinRecord(TEST_COIN, confirmed_height, uint32(0), False, uint64(10000))}

    assert compute_assert_height(coin_records, conds) == expected


def spend_bundle_from_conditions(conditions: List[List[Any]], coin: Coin = TEST_COIN) -> SpendBundle:
    solution = Program.to(conditions)
    coin_spend = CoinSpend(coin, IDENTITY_PUZZLE, solution)
    return SpendBundle([coin_spend], G2Element())


async def add_spendbundle(
    mempool_manager: MempoolManager, sb: SpendBundle, sb_name: bytes32
) -> Tuple[Optional[uint64], MempoolInclusionStatus, Optional[Err]]:
    npc_result = await mempool_manager.pre_validate_spendbundle(sb, None, sb_name)
    return await mempool_manager.add_spend_bundle(sb, npc_result, sb_name, TEST_HEIGHT)


async def generate_and_add_spendbundle(
    mempool_manager: MempoolManager,
    conditions: List[List[Any]],
    coin: Coin = TEST_COIN,
) -> Tuple[SpendBundle, bytes32, Tuple[Optional[uint64], MempoolInclusionStatus, Optional[Err]]]:
    sb = spend_bundle_from_conditions(conditions, coin)
    sb_name = sb.name()
    result = await add_spendbundle(mempool_manager, sb, sb_name)
    return (sb, sb_name, result)


@pytest.mark.asyncio
async def test_empty_spend_bundle() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    sb = SpendBundle([], G2Element())
    with pytest.raises(ValidationError, match="INVALID_SPEND_BUNDLE"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_negative_addition_amount() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, -1]]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="COIN_AMOUNT_NEGATIVE"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_valid_addition_amount() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    max_amount = mempool_manager.constants.MAX_COIN_AMOUNT
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, max_amount]]
    coin = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, max_amount)
    sb = spend_bundle_from_conditions(conditions, coin)
    npc_result = await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())
    assert npc_result.error is None


@pytest.mark.asyncio
async def test_too_big_addition_amount() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    max_amount = mempool_manager.constants.MAX_COIN_AMOUNT
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, max_amount + 1]]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="COIN_AMOUNT_EXCEEDS_MAXIMUM"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_duplicate_output() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
    ]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="DUPLICATE_OUTPUT"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_block_cost_exceeds_max() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    conditions = []
    for i in range(2400):
        conditions.append([ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, i])
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="BLOCK_COST_EXCEEDS_MAX"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_double_spend_prevalidation() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    sb = spend_bundle_from_conditions(conditions)
    sb_twice: SpendBundle = SpendBundle.aggregate([sb, sb])
    with pytest.raises(ValidationError, match="DOUBLE_SPEND"):
        await mempool_manager.pre_validate_spendbundle(sb_twice, None, sb_twice.name())


@pytest.mark.asyncio
async def test_minting_coin() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT]]
    sb = spend_bundle_from_conditions(conditions)
    npc_result = await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())
    assert npc_result.error is None
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT + 1]]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="MINTING_COIN"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_reserve_fee_condition() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_record)
    conditions = [[ConditionOpcode.RESERVE_FEE, TEST_COIN_AMOUNT]]
    sb = spend_bundle_from_conditions(conditions)
    npc_result = await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())
    assert npc_result.error is None
    conditions = [[ConditionOpcode.RESERVE_FEE, TEST_COIN_AMOUNT + 1]]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="RESERVE_FEE_CONDITION_FAILED"):
        await mempool_manager.pre_validate_spendbundle(sb, None, sb.name())


@pytest.mark.asyncio
async def test_unknown_unspent() -> None:
    async def get_coin_record(_: bytes32) -> Optional[CoinRecord]:
        return None

    mempool_manager = await instantiate_mempool_manager(get_coin_record)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    _, _, result = await generate_and_add_spendbundle(mempool_manager, conditions)
    assert result == (None, MempoolInclusionStatus.FAILED, Err.UNKNOWN_UNSPENT)


@pytest.mark.asyncio
async def test_same_sb_twice_with_eligible_coin() -> None:
    mempool_manager = await instantiate_mempool_manager(get_coin_record_for_test_coins)
    sb1_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 2],
    ]
    sb1 = spend_bundle_from_conditions(sb1_conditions)
    sb2_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 3],
        [ConditionOpcode.AGG_SIG_UNSAFE, G1Element(), IDENTITY_PUZZLE_HASH],
    ]
    sb2 = spend_bundle_from_conditions(sb2_conditions, TEST_COIN2)
    sb = SpendBundle.aggregate([sb1, sb2])
    sb_name = sb.name()
    result = await add_spendbundle(mempool_manager, sb, sb_name)
    expected_cost = uint64(10268283)
    assert result == (expected_cost, MempoolInclusionStatus.SUCCESS, None)
    assert mempool_manager.get_spendbundle(sb_name) == sb
    result = await add_spendbundle(mempool_manager, sb, sb_name)
    assert result == (expected_cost, MempoolInclusionStatus.SUCCESS, None)
    assert mempool_manager.get_spendbundle(sb_name) == sb


@pytest.mark.asyncio
async def test_sb_twice_with_eligible_coin_and_different_spends_order() -> None:
    mempool_manager = await instantiate_mempool_manager(get_coin_record_for_test_coins)
    sb1_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 2],
    ]
    sb1 = spend_bundle_from_conditions(sb1_conditions)
    sb2_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 3],
        [ConditionOpcode.AGG_SIG_UNSAFE, G1Element(), IDENTITY_PUZZLE_HASH],
    ]
    sb2 = spend_bundle_from_conditions(sb2_conditions, TEST_COIN2)
    sb3_conditions = [[ConditionOpcode.AGG_SIG_UNSAFE, G1Element(), IDENTITY_PUZZLE_HASH]]
    sb3 = spend_bundle_from_conditions(sb3_conditions, TEST_COIN3)
    sb = SpendBundle.aggregate([sb1, sb2, sb3])
    sb_name = sb.name()
    reordered_sb = SpendBundle.aggregate([sb3, sb1, sb2])
    reordered_sb_name = reordered_sb.name()
    assert mempool_manager.get_spendbundle(sb_name) is None
    assert mempool_manager.get_spendbundle(reordered_sb_name) is None
    result = await add_spendbundle(mempool_manager, sb, sb_name)
    expected_cost = uint64(13091510)
    assert result == (expected_cost, MempoolInclusionStatus.SUCCESS, None)
    assert mempool_manager.get_spendbundle(sb_name) == sb
    assert mempool_manager.get_spendbundle(reordered_sb_name) is None
    # This reordered spend bundle should generate conflicting coin spends with
    # the previously added spend bundle
    result = await add_spendbundle(mempool_manager, reordered_sb, reordered_sb_name)
    assert result == (expected_cost, MempoolInclusionStatus.PENDING, Err.MEMPOOL_CONFLICT)
    assert mempool_manager.get_spendbundle(sb_name) == sb
    assert mempool_manager.get_spendbundle(reordered_sb_name) is None


co = ConditionOpcode
mis = MempoolInclusionStatus


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "opcode,lock_value,expected_status,expected_error",
    [
        (co.ASSERT_SECONDS_RELATIVE, -2, mis.SUCCESS, None),
        (co.ASSERT_SECONDS_RELATIVE, -1, mis.SUCCESS, None),
        # The rules allow spending an ephemeral coin with an ASSERT_SECONDS_RELATIVE 0 condition
        (co.ASSERT_SECONDS_RELATIVE, 0, mis.SUCCESS, None),
        (co.ASSERT_SECONDS_RELATIVE, 1, mis.FAILED, Err.ASSERT_SECONDS_RELATIVE_FAILED),
        (co.ASSERT_HEIGHT_RELATIVE, -2, mis.SUCCESS, None),
        (co.ASSERT_HEIGHT_RELATIVE, -1, mis.SUCCESS, None),
        # Unlike ASSERT_SECONDS_RELATIVE, for ASSERT_HEIGHT_RELATIVE the block height
        # must be greater than the coin creation height + the argument, which means
        # the coin cannot be spent in the same block (where the height would be the same)
        (co.ASSERT_HEIGHT_RELATIVE, 0, mis.PENDING, Err.ASSERT_HEIGHT_RELATIVE_FAILED),
        (co.ASSERT_HEIGHT_RELATIVE, 1, mis.PENDING, Err.ASSERT_HEIGHT_RELATIVE_FAILED),
        (co.ASSERT_HEIGHT_ABSOLUTE, 4, mis.SUCCESS, None),
        (co.ASSERT_HEIGHT_ABSOLUTE, 5, mis.SUCCESS, None),
        (co.ASSERT_HEIGHT_ABSOLUTE, 6, mis.PENDING, Err.ASSERT_HEIGHT_ABSOLUTE_FAILED),
        (co.ASSERT_HEIGHT_ABSOLUTE, 7, mis.PENDING, Err.ASSERT_HEIGHT_ABSOLUTE_FAILED),
        # Current block timestamp is 10050
        (co.ASSERT_SECONDS_ABSOLUTE, 10049, mis.SUCCESS, None),
        (co.ASSERT_SECONDS_ABSOLUTE, 10050, mis.SUCCESS, None),
        (co.ASSERT_SECONDS_ABSOLUTE, 10051, mis.FAILED, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
        (co.ASSERT_SECONDS_ABSOLUTE, 10052, mis.FAILED, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
    ],
)
async def test_ephemeral_timelock(
    opcode: ConditionOpcode,
    lock_value: int,
    expected_status: MempoolInclusionStatus,
    expected_error: Optional[Err],
) -> None:
    mempool_manager = await instantiate_mempool_manager(
        get_coin_record=get_coin_record_for_test_coins,
        current_block_height=uint32(5),
        current_block_timestamp=uint64(10050),
    )
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1], [opcode, lock_value]]
    created_coin = Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, 1)
    sb1 = spend_bundle_from_conditions(conditions)
    sb2 = spend_bundle_from_conditions(conditions, created_coin)
    # sb spends TEST_COIN and creates created_coin which gets spent too
    sb = SpendBundle.aggregate([sb1, sb2])
    # We shouldn't have a record of this ephemeral coin
    assert await get_coin_record_for_test_coins(created_coin.name()) is None
    _, status, error = await add_spendbundle(mempool_manager, sb, sb.name())
    assert (status, error) == (expected_status, expected_error)


@pytest.mark.asyncio
async def test_get_items_not_in_filter() -> None:
    mempool_manager = await instantiate_mempool_manager(get_coin_record_for_test_coins)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    sb1, sb1_name, _ = await generate_and_add_spendbundle(mempool_manager, conditions)
    conditions2 = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 2]]
    sb2, sb2_name, _ = await generate_and_add_spendbundle(mempool_manager, conditions2, TEST_COIN2)
    conditions3 = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 3]]
    sb3, sb3_name, _ = await generate_and_add_spendbundle(mempool_manager, conditions3, TEST_COIN3)

    # Don't filter anything
    empty_filter = PyBIP158([])
    result = mempool_manager.get_items_not_in_filter(empty_filter)
    assert result == [sb3, sb2, sb1]

    # Filter everything
    full_filter = PyBIP158([bytearray(sb1_name), bytearray(sb2_name), bytearray(sb3_name)])
    result = mempool_manager.get_items_not_in_filter(full_filter)
    assert result == []

    # Negative limit
    with pytest.raises(AssertionError):
        mempool_manager.get_items_not_in_filter(empty_filter, limit=-1)

    # Zero limit
    with pytest.raises(AssertionError):
        mempool_manager.get_items_not_in_filter(empty_filter, limit=0)

    # Filter only one of the spend bundles
    sb3_filter = PyBIP158([bytearray(sb3_name)])

    # With a limit of one, sb2 has the highest FPC
    result = mempool_manager.get_items_not_in_filter(sb3_filter, limit=1)
    assert result == [sb2]

    # With a higher limit, all bundles aside from sb3 get included
    result = mempool_manager.get_items_not_in_filter(sb3_filter, limit=5)
    assert result == [sb2, sb1]

    # Filter two of the spend bundles
    sb2_and_3_filter = PyBIP158([bytearray(sb2_name), bytearray(sb3_name)])
    result = mempool_manager.get_items_not_in_filter(sb2_and_3_filter)
    assert result == [sb1]


@pytest.mark.asyncio
async def test_total_mempool_fees() -> None:

    coin_records: Dict[bytes32, CoinRecord] = {}

    async def get_coin_record(coin_id: bytes32) -> Optional[CoinRecord]:
        return coin_records.get(coin_id)

    mempool_manager = await instantiate_mempool_manager(get_coin_record)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]

    # the limit of total fees in the mempool is 2^63
    # the limit per mempool item is 2^50, that lets us add 8192 items with the
    # maximum amount of fee before reaching the total mempool limit
    amount = uint64(2**50)
    total_fee = 0
    for i in range(8192):
        coin = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, amount)
        coin_records[coin.name()] = CoinRecord(coin, uint32(0), uint32(0), False, uint64(0))
        amount = uint64(amount - 1)
        # the fee is 1 less than the amount because we create a coin of 1 mojo
        total_fee += amount
        _, _, result = await generate_and_add_spendbundle(mempool_manager, conditions, coin)
        assert result[1] == MempoolInclusionStatus.SUCCESS
        assert mempool_manager.mempool.total_mempool_fees() == total_fee

    coin = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, amount)
    coin_records[coin.name()] = CoinRecord(coin, uint32(0), uint32(0), False, uint64(0))
    _, _, result = await generate_and_add_spendbundle(mempool_manager, conditions, coin)
    assert result[1] == MempoolInclusionStatus.FAILED
    assert result[2] == Err.INVALID_BLOCK_FEE_AMOUNT
