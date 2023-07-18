from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

import pytest
from blspy import G1Element, G2Element
from chia_rs import ELIGIBLE_FOR_DEDUP
from chiabip158 import PyBIP158

from chia.consensus.constants import ConsensusConstants
from chia.consensus.cost_calculator import NPCResult
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions, mempool_check_time_locks
from chia.full_node.mempool_manager import (
    MEMPOOL_MIN_FEE_INCREASE,
    MempoolManager,
    TimelockConditions,
    can_replace,
    compute_assert_height,
    optional_max,
    optional_min,
)
from chia.protocols import wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.setup_nodes import SimulatorsAndWallets
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.eligible_coin_spends import DedupCoinSpend, EligibleCoinSpends, run_for_cost
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.mempool_item import BundleCoinSpend, MempoolItem
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.types.spend_bundle_conditions import Spend, SpendBundleConditions
from chia.util.errors import Err, ValidationError
from chia.util.ints import uint16, uint32, uint64
from chia.wallet.payment import Payment
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_node import WalletNode

IDENTITY_PUZZLE = SerializedProgram.from_program(Program.to(1))
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
    block_height: uint32 = TEST_HEIGHT,
    block_timestamp: uint64 = TEST_TIMESTAMP,
    constants: ConsensusConstants = DEFAULT_CONSTANTS,
) -> MempoolManager:
    mempool_manager = MempoolManager(get_coin_record, constants)
    test_block_record = create_test_block_record(height=block_height, timestamp=block_timestamp)
    await mempool_manager.new_peak(test_block_record, None)
    return mempool_manager


async def setup_mempool_with_coins(*, coin_amounts: List[int]) -> Tuple[MempoolManager, List[Coin]]:
    coins = []
    test_coin_records = {}
    for amount in coin_amounts:
        coin = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, uint64(amount))
        coins.append(coin)
        test_coin_records[coin.name()] = CoinRecord(coin, uint32(0), uint32(0), False, uint64(0))

    async def get_coin_record(coin_id: bytes32) -> Optional[CoinRecord]:
        return test_coin_records.get(coin_id)

    mempool_manager = await instantiate_mempool_manager(get_coin_record)
    return (mempool_manager, coins)


def make_test_conds(
    *,
    birth_height: Optional[int] = None,
    birth_seconds: Optional[int] = None,
    height_relative: Optional[int] = None,
    height_absolute: int = 0,
    seconds_relative: Optional[int] = None,
    seconds_absolute: int = 0,
    before_height_relative: Optional[int] = None,
    before_height_absolute: Optional[int] = None,
    before_seconds_relative: Optional[int] = None,
    before_seconds_absolute: Optional[int] = None,
    cost: int = 0,
    spend_ids: List[bytes32] = [TEST_COIN_ID],
) -> SpendBundleConditions:
    return SpendBundleConditions(
        [
            Spend(
                spend_id,
                IDENTITY_PUZZLE_HASH,
                IDENTITY_PUZZLE_HASH,
                TEST_COIN_AMOUNT,
                None if height_relative is None else uint32(height_relative),
                None if seconds_relative is None else uint64(seconds_relative),
                None if before_height_relative is None else uint32(before_height_relative),
                None if before_seconds_relative is None else uint64(before_seconds_relative),
                None if birth_height is None else uint32(birth_height),
                None if birth_seconds is None else uint64(birth_seconds),
                [],
                [],
                [],
                [],
                [],
                [],
                [],
                [],
                0,
            )
            for spend_id in spend_ids
        ],
        0,
        uint32(height_absolute),
        uint64(seconds_absolute),
        None if before_height_absolute is None else uint32(before_height_absolute),
        None if before_seconds_absolute is None else uint64(before_seconds_absolute),
        [],
        cost,
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
            # the coin is 5 blocks old in this test
            (make_test_conds(before_height_relative=5), Err.ASSERT_BEFORE_HEIGHT_RELATIVE_FAILED),
            (make_test_conds(before_height_relative=6), None),
            # The block height is 15
            (make_test_conds(before_height_absolute=15), Err.ASSERT_BEFORE_HEIGHT_ABSOLUTE_FAILED),
            (make_test_conds(before_height_absolute=16), None),
            # the coin is 150 seconds old in this test
            (make_test_conds(before_seconds_relative=150), Err.ASSERT_BEFORE_SECONDS_RELATIVE_FAILED),
            (make_test_conds(before_seconds_relative=151), None),
            # The block timestamp is 10150
            (make_test_conds(before_seconds_absolute=10150), Err.ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED),
            (make_test_conds(before_seconds_absolute=10151), None),
        ],
    )
    def test_conditions(
        self,
        conds: SpendBundleConditions,
        expected: Optional[Err],
    ) -> None:
        assert (
            mempool_check_time_locks(
                self.REMOVALS,
                conds,
                self.PREV_BLOCK_HEIGHT,
                self.PREV_BLOCK_TIMESTAMP,
            )
            == expected
        )


def expect(
    *, height: int = 0, before_height: Optional[int] = None, before_seconds: Optional[int] = None
) -> TimelockConditions:
    ret = TimelockConditions(uint32(height))
    if before_height is not None:
        ret.assert_before_height = uint32(before_height)
    if before_seconds is not None:
        ret.assert_before_seconds = uint64(before_seconds)
    return ret


@pytest.mark.parametrize(
    "conds,expected",
    [
        # ASSERT_HEIGHT_*
        # coin birth height is 12
        (make_test_conds(), expect()),
        (make_test_conds(height_absolute=42), expect(height=42)),
        # 1 is a relative height, but that only amounts to 13, so the absolute
        # height is more restrictive
        (make_test_conds(height_relative=1), expect(height=13)),
        # 100 is a relative height, and since the coin was confirmed at height 12,
        # that's 112
        (make_test_conds(height_absolute=42, height_relative=100), expect(height=112)),
        # Same thing but without the absolute height
        (make_test_conds(height_relative=100), expect(height=112)),
        (make_test_conds(height_relative=0), expect(height=12)),
        # 42 is more restrictive than 13
        (make_test_conds(height_absolute=42, height_relative=1), expect(height=42)),
        # ASSERT_BEFORE_HEIGHT_*
        (make_test_conds(before_height_absolute=100), expect(before_height=100)),
        # coin is created at 12 + 1 relative height = 13
        (make_test_conds(before_height_relative=1), expect(before_height=13)),
        # coin is created at 12 + 0 relative height = 12
        (make_test_conds(before_height_relative=0), expect(before_height=12)),
        # 13 is more restrictive than 42
        (make_test_conds(before_height_absolute=42, before_height_relative=1), expect(before_height=13)),
        # 100 is a relative height, and since the coin was confirmed at height 12,
        # that's 112
        (make_test_conds(before_height_absolute=200, before_height_relative=100), expect(before_height=112)),
        # Same thing but without the absolute height
        (make_test_conds(before_height_relative=100), expect(before_height=112)),
        # ASSERT_BEFORE_SECONDS_*
        # coin timestamp is 10000
        # single absolute assert before seconds
        (make_test_conds(before_seconds_absolute=20000), expect(before_seconds=20000)),
        # coin is created at 10000 + 100 relative seconds = 10100
        (make_test_conds(before_seconds_relative=100), expect(before_seconds=10100)),
        # coin is created at 10000 + 0 relative seconds = 10000
        (make_test_conds(before_seconds_relative=0), expect(before_seconds=10000)),
        # 10100 is more restrictive than 20000
        (make_test_conds(before_seconds_absolute=20000, before_seconds_relative=100), expect(before_seconds=10100)),
        # 20000 is a relative seconds, and since the coin was confirmed at seconds
        # 10000 that's 300000
        (make_test_conds(before_seconds_absolute=20000, before_seconds_relative=20000), expect(before_seconds=20000)),
        # Same thing but without the absolute seconds
        (make_test_conds(before_seconds_relative=20000), expect(before_seconds=30000)),
    ],
)
def test_compute_assert_height(conds: SpendBundleConditions, expected: TimelockConditions) -> None:
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


def make_bundle_spends_map_and_fee(
    spend_bundle: SpendBundle, npc_result: NPCResult
) -> Tuple[Dict[bytes32, BundleCoinSpend], uint64]:
    bundle_coin_spends: Dict[bytes32, BundleCoinSpend] = {}
    eligibility_and_additions: Dict[bytes32, Tuple[bool, List[Coin]]] = {}
    removals_amount = 0
    additions_amount = 0
    assert npc_result.conds is not None
    for spend in npc_result.conds.spends:
        coin_id = bytes32(spend.coin_id)
        spend_additions = []
        for puzzle_hash, amount, _ in spend.create_coin:
            spend_additions.append(Coin(coin_id, puzzle_hash, amount))
            additions_amount += amount
        eligibility_and_additions[coin_id] = (bool(spend.flags & ELIGIBLE_FOR_DEDUP), spend_additions)
    for coin_spend in spend_bundle.coin_spends:
        coin_id = coin_spend.coin.name()
        removals_amount += coin_spend.coin.amount
        eligible_for_dedup, spend_additions = eligibility_and_additions.get(coin_id, (False, []))
        bundle_coin_spends[coin_id] = BundleCoinSpend(coin_spend, eligible_for_dedup, spend_additions)
    fee = uint64(removals_amount - additions_amount)
    return bundle_coin_spends, fee


def mempool_item_from_spendbundle(spend_bundle: SpendBundle) -> MempoolItem:
    generator = simple_solution_generator(spend_bundle)
    npc_result = get_name_puzzle_conditions(
        generator=generator, max_cost=INFINITE_COST, mempool_mode=True, height=uint32(0), constants=DEFAULT_CONSTANTS
    )
    bundle_coin_spends, fee = make_bundle_spends_map_and_fee(spend_bundle, npc_result)
    return MempoolItem(
        spend_bundle=spend_bundle,
        fee=fee,
        npc_result=npc_result,
        spend_bundle_name=spend_bundle.name(),
        height_added_to_mempool=TEST_HEIGHT,
        bundle_coin_spends=bundle_coin_spends,
    )


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
@pytest.mark.parametrize("softfork2", [False, True])
@pytest.mark.parametrize(
    "opcode,lock_value,expected_status,expected_error",
    [
        # the mempool rules don't allow relative height- or time conditions on
        # ephemeral spends
        # SECONDS RELATIVE
        (co.ASSERT_SECONDS_RELATIVE, -2, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_SECONDS_RELATIVE, -1, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_SECONDS_RELATIVE, 0, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_SECONDS_RELATIVE, 1, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_SECONDS_RELATIVE, 9, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_SECONDS_RELATIVE, 10, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        # HEIGHT RELATIVE
        (co.ASSERT_HEIGHT_RELATIVE, -2, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_HEIGHT_RELATIVE, -1, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_HEIGHT_RELATIVE, 0, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_HEIGHT_RELATIVE, 1, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_HEIGHT_RELATIVE, 5, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_HEIGHT_RELATIVE, 6, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_HEIGHT_RELATIVE, 7, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_HEIGHT_RELATIVE, 10, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_HEIGHT_RELATIVE, 11, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        # BEFORE HEIGHT RELATIVE
        (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -2, mis.FAILED, Err.ASSERT_BEFORE_HEIGHT_RELATIVE_FAILED),
        (co.ASSERT_BEFORE_HEIGHT_RELATIVE, -1, mis.FAILED, Err.ASSERT_BEFORE_HEIGHT_RELATIVE_FAILED),
        (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 0, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 1, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 5, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 6, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 7, mis.FAILED, Err.EPHEMERAL_RELATIVE_CONDITION),
        # HEIGHT ABSOLUTE
        (co.ASSERT_HEIGHT_ABSOLUTE, 4, mis.SUCCESS, None),
        (co.ASSERT_HEIGHT_ABSOLUTE, 5, mis.SUCCESS, None),
        (co.ASSERT_HEIGHT_ABSOLUTE, 6, mis.PENDING, Err.ASSERT_HEIGHT_ABSOLUTE_FAILED),
        (co.ASSERT_HEIGHT_ABSOLUTE, 7, mis.PENDING, Err.ASSERT_HEIGHT_ABSOLUTE_FAILED),
        # BEFORE HEIGHT ABSOLUTE
        (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 4, mis.FAILED, Err.ASSERT_BEFORE_HEIGHT_ABSOLUTE_FAILED),
        (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 5, mis.FAILED, Err.ASSERT_BEFORE_HEIGHT_ABSOLUTE_FAILED),
        (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 6, mis.SUCCESS, None),
        (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 7, mis.SUCCESS, None),
        # SECONDS ABSOLUTE
        # Current block timestamp is 10050
        (co.ASSERT_SECONDS_ABSOLUTE, 10049, mis.SUCCESS, None),
        (co.ASSERT_SECONDS_ABSOLUTE, 10050, mis.SUCCESS, None),
        (co.ASSERT_SECONDS_ABSOLUTE, 10051, mis.FAILED, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
        (co.ASSERT_SECONDS_ABSOLUTE, 10052, mis.FAILED, Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
        # BEFORE SECONDS ABSOLUTE
        (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10049, mis.FAILED, Err.ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED),
        (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10050, mis.FAILED, Err.ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED),
        (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10051, mis.SUCCESS, None),
        (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10052, mis.SUCCESS, None),
    ],
)
async def test_ephemeral_timelock(
    opcode: ConditionOpcode,
    lock_value: int,
    expected_status: MempoolInclusionStatus,
    expected_error: Optional[Err],
    softfork2: bool,
) -> None:
    if softfork2:
        constants = DEFAULT_CONSTANTS.replace(SOFT_FORK2_HEIGHT=0)
    else:
        constants = DEFAULT_CONSTANTS

    mempool_manager = await instantiate_mempool_manager(
        get_coin_record=get_coin_record_for_test_coins,
        block_height=uint32(5),
        block_timestamp=uint64(10050),
        constants=constants,
    )

    if not softfork2 and opcode in [
        co.ASSERT_BEFORE_HEIGHT_ABSOLUTE,
        co.ASSERT_BEFORE_HEIGHT_RELATIVE,
        co.ASSERT_BEFORE_SECONDS_ABSOLUTE,
        co.ASSERT_BEFORE_SECONDS_RELATIVE,
    ]:
        expected_error = Err.INVALID_CONDITION
        expected_status = MempoolInclusionStatus.FAILED

    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    created_coin = Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, 1)
    sb1 = spend_bundle_from_conditions(conditions)
    sb2 = spend_bundle_from_conditions([[opcode, lock_value]], created_coin)
    # sb spends TEST_COIN and creates created_coin which gets spent too
    sb = SpendBundle.aggregate([sb1, sb2])
    # We shouldn't have a record of this ephemeral coin
    assert await get_coin_record_for_test_coins(created_coin.name()) is None
    try:
        _, status, error = await add_spendbundle(mempool_manager, sb, sb.name())
        assert (status, error) == (expected_status, expected_error)
    except ValidationError as e:
        assert expected_status == mis.FAILED
        assert expected_error == e.code


def test_optional_min() -> None:
    assert optional_min(uint32(100), None) == uint32(100)
    assert optional_min(None, uint32(100)) == uint32(100)
    assert optional_min(None, None) is None
    assert optional_min(uint32(123), uint32(234)) == uint32(123)


def test_optional_max() -> None:
    assert optional_max(uint32(100), None) == uint32(100)
    assert optional_max(None, uint32(100)) == uint32(100)
    assert optional_max(None, None) is None
    assert optional_max(uint32(123), uint32(234)) == uint32(234)


def mk_item(
    coins: List[Coin],
    *,
    cost: int = 1,
    fee: int = 0,
    assert_height: Optional[int] = None,
    assert_before_height: Optional[int] = None,
    assert_before_seconds: Optional[int] = None,
) -> MempoolItem:
    # we don't actually care about the puzzle and solutions for the purpose of
    # can_replace()
    spends = [CoinSpend(c, SerializedProgram(), SerializedProgram()) for c in coins]
    spend_bundle = SpendBundle(spends, G2Element())
    npc_result = NPCResult(None, make_test_conds(cost=cost, spend_ids=[c.name() for c in coins]), uint64(cost))
    return MempoolItem(
        spend_bundle,
        uint64(fee),
        npc_result,
        spend_bundle.name(),
        uint32(0),
        None if assert_height is None else uint32(assert_height),
        None if assert_before_height is None else uint32(assert_before_height),
        None if assert_before_seconds is None else uint64(assert_before_seconds),
    )


def make_test_coins() -> List[Coin]:
    ret: List[Coin] = []
    for i in range(5):
        ret.append(Coin(height_hash(i), height_hash(i + 100), i * 100))
    return ret


coins = make_test_coins()


@pytest.mark.parametrize(
    "existing_items,new_item,expected",
    [
        # FEE RULE
        # the new item must pay a higher fee, in absolute terms
        # replacing exactly the same spend is fine, as long as we increment the fee
        ([mk_item(coins[0:1])], mk_item(coins[0:1]), False),
        # this is less than the minimum fee increase
        ([mk_item(coins[0:1])], mk_item(coins[0:1], fee=9999999), False),
        # this is the minimum fee increase
        ([mk_item(coins[0:1])], mk_item(coins[0:1], fee=10000000), True),
        # FEE RATE RULE
        # the new item must pay a higher fee per cost than the existing item(s)
        # the existing fee rate is 2 and the new fee rate is 2
        ([mk_item(coins[0:1], cost=1000, fee=2000)], mk_item(coins[0:1], cost=10000000, fee=20000000), False),
        # the new rate is >2
        ([mk_item(coins[0:1], cost=1000, fee=2000)], mk_item(coins[0:1], cost=10000000, fee=20000001), True),
        # SUPERSET RULE
        # we can't replace an item spending coin 0 and 1 with an
        # item that just spends coin 0
        ([mk_item(coins[0:2])], mk_item(coins[0:1], fee=10000000), False),
        # or just spends coin 1
        ([mk_item(coins[0:2])], mk_item(coins[1:2], fee=10000000), False),
        # but if we spend the same coins
        ([mk_item(coins[0:2])], mk_item(coins[0:2], fee=10000000), True),
        # or if we spend the same coins with additional coins
        ([mk_item(coins[0:2])], mk_item(coins[0:3], fee=10000000), True),
        # FEE- AND FEE RATE RULES
        # if we're replacing two items, each paying a fee of 100, we need to
        # spend (at least) the same coins and pay at least 10000000 higher fee
        (
            [mk_item(coins[0:1], fee=100, cost=100), mk_item(coins[1:2], fee=100, cost=100)],
            mk_item(coins[0:2], fee=10000200, cost=200),
            True,
        ),
        # if the fee rate is exactly the same, we won't allow the replacement
        (
            [mk_item(coins[0:1], fee=100, cost=100), mk_item(coins[1:2], fee=100, cost=100)],
            mk_item(coins[0:2], fee=10000200, cost=10000200),
            False,
        ),
        # TIMELOCK RULE
        # the new item must not have different time lock than the existing item(s)
        # the assert height time lock condition was introduced in the new item
        ([mk_item(coins[0:1])], mk_item(coins[0:1], fee=10000000, assert_height=1000), False),
        # the assert before height time lock condition was introduced in the new item
        ([mk_item(coins[0:1])], mk_item(coins[0:1], fee=10000000, assert_before_height=1000), False),
        # the assert before seconds time lock condition was introduced in the new item
        ([mk_item(coins[0:1])], mk_item(coins[0:1], fee=10000000, assert_before_seconds=1000), False),
        # if we don't alter any time locks, we are allowed to replace
        ([mk_item(coins[0:1])], mk_item(coins[0:1], fee=10000000), True),
        # ASSERT_HEIGHT
        # the assert height time lock condition was removed in the new item
        ([mk_item(coins[0:1], assert_height=1000)], mk_item(coins[0:1], fee=10000000), False),
        # different assert height constraint
        ([mk_item(coins[0:1], assert_height=1000)], mk_item(coins[0:1], fee=10000000, assert_height=100), False),
        ([mk_item(coins[0:1], assert_height=1000)], mk_item(coins[0:1], fee=10000000, assert_height=2000), False),
        # the same assert height is OK
        ([mk_item(coins[0:1], assert_height=1000)], mk_item(coins[0:1], fee=10000000, assert_height=1000), True),
        # The new spend just have to match the most restrictive condition
        (
            [mk_item(coins[0:1], assert_height=200), mk_item(coins[1:2], assert_height=400)],
            mk_item(coins[0:2], fee=10000000, assert_height=400),
            True,
        ),
        # ASSERT_BEFORE_HEIGHT
        # the assert before height time lock condition was removed in the new item
        ([mk_item(coins[0:1], assert_before_height=1000)], mk_item(coins[0:1], fee=10000000), False),
        # different assert before height constraint
        (
            [mk_item(coins[0:1], assert_before_height=1000)],
            mk_item(coins[0:1], fee=10000000, assert_before_height=100),
            False,
        ),
        (
            [mk_item(coins[0:1], assert_before_height=1000)],
            mk_item(coins[0:1], fee=10000000, assert_before_height=2000),
            False,
        ),
        # The new spend just have to match the most restrictive condition
        (
            [mk_item(coins[0:1], assert_before_height=200), mk_item(coins[1:2], assert_before_height=400)],
            mk_item(coins[0:2], fee=10000000, assert_before_height=200),
            True,
        ),
        # ASSERT_BEFORE_SECONDS
        # the assert before height time lock condition was removed in the new item
        ([mk_item(coins[0:1], assert_before_seconds=1000)], mk_item(coins[0:1], fee=10000000), False),
        # different assert before seconds constraint
        (
            [mk_item(coins[0:1], assert_before_seconds=1000)],
            mk_item(coins[0:1], fee=10000000, assert_before_seconds=100),
            False,
        ),
        (
            [mk_item(coins[0:1], assert_before_seconds=1000)],
            mk_item(coins[0:1], fee=10000000, assert_before_seconds=2000),
            False,
        ),
        # the assert before height time lock condition was introduced in the new item
        (
            [mk_item(coins[0:1], assert_before_seconds=1000)],
            mk_item(coins[0:1], fee=10000000, assert_before_seconds=1000),
            True,
        ),
        # The new spend just have to match the most restrictive condition
        (
            [mk_item(coins[0:1], assert_before_seconds=200), mk_item(coins[1:2], assert_before_seconds=400)],
            mk_item(coins[0:2], fee=10000000, assert_before_seconds=200),
            True,
        ),
        # MIXED CONDITIONS
        # we can't replace an assert_before_seconds with assert_before_height
        (
            [mk_item(coins[0:1], assert_before_seconds=1000)],
            mk_item(coins[0:1], fee=10000000, assert_before_height=2000),
            False,
        ),
        # we added another condition
        (
            [mk_item(coins[0:1], assert_before_seconds=1000)],
            mk_item(coins[0:1], fee=10000000, assert_before_seconds=1000, assert_height=200),
            False,
        ),
        # we removed assert before height
        (
            [mk_item(coins[0:1], assert_height=200, assert_before_height=1000)],
            mk_item(coins[0:1], fee=10000000, assert_height=200),
            False,
        ),
    ],
)
def test_can_replace(existing_items: List[MempoolItem], new_item: MempoolItem, expected: bool) -> None:
    removals = set(c.name() for c in new_item.spend_bundle.removals())
    assert can_replace(existing_items, removals, new_item) == expected


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


@pytest.mark.parametrize("reverse_tx_order", [True, False])
@pytest.mark.asyncio
async def test_create_bundle_from_mempool(reverse_tx_order: bool) -> None:
    async def make_coin_spends(coins: List[Coin], *, high_fees: bool = True) -> List[CoinSpend]:
        spends_list = []
        for i in range(0, len(coins)):
            coin_spend = CoinSpend(
                coins[i],
                IDENTITY_PUZZLE,
                Program.to(
                    [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, i if high_fees else (coins[i].amount - 1)]]
                ),
            )
            spends_list.append(coin_spend)
        return spends_list

    async def send_spends_to_mempool(coin_spends: List[CoinSpend]) -> None:
        g2 = G2Element()
        for cs in coin_spends:
            sb = SpendBundle([cs], g2)
            result = await add_spendbundle(mempool_manager, sb, sb.name())
            assert result[1] == MempoolInclusionStatus.SUCCESS

    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(2000000000, 2000002200)))
    high_rate_spends = await make_coin_spends(coins[0:2000])
    low_rate_spends = await make_coin_spends(coins[2000:2100], high_fees=False)
    spends = low_rate_spends + high_rate_spends if reverse_tx_order else high_rate_spends + low_rate_spends
    await send_spends_to_mempool(spends)
    assert mempool_manager.peak is not None
    result = mempool_manager.create_bundle_from_mempool(mempool_manager.peak.header_hash)
    assert result is not None
    # Make sure we filled the block with only high rate spends
    assert len([s for s in high_rate_spends if s in result[0].coin_spends]) == len(result[0].coin_spends)
    assert len([s for s in low_rate_spends if s in result[0].coin_spends]) == 0


@pytest.mark.asyncio
async def test_create_bundle_from_mempool_on_max_cost() -> None:
    # This test exercises the path where an item's inclusion would exceed the
    # maximum cumulative cost, so it gets skipped as a result
    async def make_and_send_big_cost_sb(coin: Coin) -> None:
        conditions = []
        g1 = G1Element()
        for _ in range(2436):
            conditions.append([ConditionOpcode.AGG_SIG_UNSAFE, g1, IDENTITY_PUZZLE_HASH])
        conditions.append([ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, coin.amount - 1])
        # Create a spend bundle with a big enough cost that gets it close to the limit
        _, _, res = await generate_and_add_spendbundle(mempool_manager, conditions, coin)
        assert res[1] == MempoolInclusionStatus.SUCCESS

    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=[1000000000, 1000000001])
    # Create a spend bundle with a big enough cost that gets it close to the limit
    await make_and_send_big_cost_sb(coins[0])
    # Create a second spend bundle with a relatively smaller cost.
    # Combined with the first spend bundle, we'd exceed the maximum block clvm cost
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, coins[1].amount - 2]]
    sb2, _, res = await generate_and_add_spendbundle(mempool_manager, conditions, coins[1])
    assert res[1] == MempoolInclusionStatus.SUCCESS
    assert mempool_manager.peak is not None
    result = mempool_manager.create_bundle_from_mempool(mempool_manager.peak.header_hash)
    assert result is not None
    agg, additions = result
    # The second spend bundle has a higher FPC so it should get picked first
    assert agg == sb2
    # The first spend bundle hits the maximum block clvm cost and gets skipped
    assert additions == [Coin(coins[1].name(), IDENTITY_PUZZLE_HASH, coins[1].amount - 2)]
    assert agg.removals() == [coins[1]]


@pytest.mark.parametrize(
    "opcode,arg,expect_eviction, expect_limit",
    [
        # current height: 10 current_time: 10000
        # we step the chain forward 1 block and 19 seconds
        (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10001, True, None),
        (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10019, True, None),
        (co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 10020, False, 10020),
        (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 11, True, None),
        (co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 12, False, 12),
        # the coin was created at height: 5 timestamp: 9900
        (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 6, True, None),
        (co.ASSERT_BEFORE_HEIGHT_RELATIVE, 7, False, 5 + 7),
        (co.ASSERT_BEFORE_SECONDS_RELATIVE, 119, True, None),
        (co.ASSERT_BEFORE_SECONDS_RELATIVE, 120, False, 9900 + 120),
    ],
)
@pytest.mark.asyncio
async def test_assert_before_expiration(
    opcode: ConditionOpcode, arg: int, expect_eviction: bool, expect_limit: Optional[int]
) -> None:
    async def get_coin_record(coin_id: bytes32) -> Optional[CoinRecord]:
        return {TEST_COIN.name(): CoinRecord(TEST_COIN, uint32(5), uint32(0), False, uint64(9900))}.get(coin_id)

    mempool_manager = await instantiate_mempool_manager(
        get_coin_record,
        block_height=uint32(10),
        block_timestamp=uint64(10000),
        constants=DEFAULT_CONSTANTS.replace(SOFT_FORK2_HEIGHT=0),
    )

    bundle = spend_bundle_from_conditions(
        [
            [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
            [opcode, arg],
        ],
        coin=TEST_COIN,
    )
    bundle_name = bundle.name()
    assert (await add_spendbundle(mempool_manager, bundle, bundle_name))[1] == mis.SUCCESS
    # make sure the spend was added correctly
    assert mempool_manager.get_spendbundle(bundle_name) == bundle

    block_record = create_test_block_record(height=uint32(11), timestamp=uint64(10019))
    await mempool_manager.new_peak(block_record, None)

    still_in_pool = mempool_manager.get_spendbundle(bundle_name) == bundle
    assert still_in_pool != expect_eviction
    if still_in_pool:
        assert expect_limit is not None
        item = mempool_manager.get_mempool_item(bundle_name)
        assert item is not None
        if opcode in [co.ASSERT_BEFORE_SECONDS_ABSOLUTE, co.ASSERT_BEFORE_SECONDS_RELATIVE]:
            assert item.assert_before_seconds == expect_limit
        elif opcode in [co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, co.ASSERT_BEFORE_HEIGHT_RELATIVE]:
            assert item.assert_before_height == expect_limit
        else:
            assert False


def make_test_spendbundle(coin: Coin, *, fee: int = 0, eligible_spend: bool = False) -> SpendBundle:
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, uint64(coin.amount - fee)]]
    if not eligible_spend:
        conditions.append([ConditionOpcode.AGG_SIG_UNSAFE, G1Element(), IDENTITY_PUZZLE_HASH])
    return spend_bundle_from_conditions(conditions, coin)


async def send_spendbundle(
    mempool_manager: MempoolManager,
    sb: SpendBundle,
    expected_result: Tuple[MempoolInclusionStatus, Optional[Err]] = (MempoolInclusionStatus.SUCCESS, None),
) -> None:
    result = await add_spendbundle(mempool_manager, sb, sb.name())
    assert (result[1], result[2]) == expected_result


async def make_and_send_spendbundle(
    mempool_manager: MempoolManager,
    coin: Coin,
    *,
    fee: int = 0,
    expected_result: Tuple[MempoolInclusionStatus, Optional[Err]] = (MempoolInclusionStatus.SUCCESS, None),
) -> SpendBundle:
    sb = make_test_spendbundle(coin, fee=fee)
    await send_spendbundle(mempool_manager, sb, expected_result)
    return sb


def assert_sb_in_pool(mempool_manager: MempoolManager, sb: SpendBundle) -> None:
    assert sb == mempool_manager.get_spendbundle(sb.name())


def assert_sb_not_in_pool(mempool_manager: MempoolManager, sb: SpendBundle) -> None:
    assert mempool_manager.get_spendbundle(sb.name()) is None


@pytest.mark.asyncio
async def test_insufficient_fee_increase() -> None:
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000010)))
    sb1_1 = await make_and_send_spendbundle(mempool_manager, coins[0])
    sb1_2 = await make_and_send_spendbundle(
        mempool_manager, coins[0], fee=1, expected_result=(MempoolInclusionStatus.PENDING, Err.MEMPOOL_CONFLICT)
    )
    # The old spendbundle must stay
    assert_sb_in_pool(mempool_manager, sb1_1)
    assert_sb_not_in_pool(mempool_manager, sb1_2)


@pytest.mark.asyncio
async def test_sufficient_fee_increase() -> None:
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000010)))
    sb1_1 = await make_and_send_spendbundle(mempool_manager, coins[0])
    sb1_2 = await make_and_send_spendbundle(mempool_manager, coins[0], fee=MEMPOOL_MIN_FEE_INCREASE)
    # sb1_1 gets replaced with sb1_2
    assert_sb_not_in_pool(mempool_manager, sb1_1)
    assert_sb_in_pool(mempool_manager, sb1_2)


@pytest.mark.asyncio
async def test_superset() -> None:
    # Aggregated spendbundle sb12 replaces sb1 since it spends a superset
    # of coins spent in sb1
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000010)))
    sb1 = await make_and_send_spendbundle(mempool_manager, coins[0])
    sb2 = make_test_spendbundle(coins[1], fee=MEMPOOL_MIN_FEE_INCREASE)
    sb12 = SpendBundle.aggregate([sb2, sb1])
    await send_spendbundle(mempool_manager, sb12)
    assert_sb_in_pool(mempool_manager, sb12)
    assert_sb_not_in_pool(mempool_manager, sb1)


@pytest.mark.asyncio
async def test_superset_violation() -> None:
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000010)))
    sb1 = make_test_spendbundle(coins[0])
    sb2 = make_test_spendbundle(coins[1])
    sb12 = SpendBundle.aggregate([sb1, sb2])
    await send_spendbundle(mempool_manager, sb12)
    assert_sb_in_pool(mempool_manager, sb12)
    # sb23 must not replace existing sb12 as the former does not spend all
    # coins that are spent in the latter (specifically, the first coin)
    sb3 = make_test_spendbundle(coins[2], fee=MEMPOOL_MIN_FEE_INCREASE)
    sb23 = SpendBundle.aggregate([sb2, sb3])
    await send_spendbundle(
        mempool_manager, sb23, expected_result=(MempoolInclusionStatus.PENDING, Err.MEMPOOL_CONFLICT)
    )
    assert_sb_in_pool(mempool_manager, sb12)
    assert_sb_not_in_pool(mempool_manager, sb23)


@pytest.mark.asyncio
async def test_total_fpc_decrease() -> None:
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000010)))
    sb1 = make_test_spendbundle(coins[0])
    sb2 = make_test_spendbundle(coins[1], fee=MEMPOOL_MIN_FEE_INCREASE * 2)
    sb12 = SpendBundle.aggregate([sb1, sb2])
    await send_spendbundle(mempool_manager, sb12)
    sb3 = await make_and_send_spendbundle(mempool_manager, coins[2], fee=MEMPOOL_MIN_FEE_INCREASE * 2)
    assert_sb_in_pool(mempool_manager, sb12)
    assert_sb_in_pool(mempool_manager, sb3)
    # sb1234 should not be in pool as it decreases total fees per cost
    sb4 = make_test_spendbundle(coins[3], fee=MEMPOOL_MIN_FEE_INCREASE)
    sb1234 = SpendBundle.aggregate([sb12, sb3, sb4])
    await send_spendbundle(
        mempool_manager, sb1234, expected_result=(MempoolInclusionStatus.PENDING, Err.MEMPOOL_CONFLICT)
    )
    assert_sb_not_in_pool(mempool_manager, sb1234)


@pytest.mark.asyncio
async def test_sufficient_total_fpc_increase() -> None:
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000010)))
    sb1 = make_test_spendbundle(coins[0])
    sb2 = make_test_spendbundle(coins[1], fee=MEMPOOL_MIN_FEE_INCREASE * 2)
    sb12 = SpendBundle.aggregate([sb1, sb2])
    await send_spendbundle(mempool_manager, sb12)
    sb3 = await make_and_send_spendbundle(mempool_manager, coins[2], fee=MEMPOOL_MIN_FEE_INCREASE * 2)
    assert_sb_in_pool(mempool_manager, sb12)
    assert_sb_in_pool(mempool_manager, sb3)
    # sb1234 has a higher fee per cost than its conflicts and should get
    # into the mempool
    sb4 = make_test_spendbundle(coins[3], fee=MEMPOOL_MIN_FEE_INCREASE * 3)
    sb1234 = SpendBundle.aggregate([sb12, sb3, sb4])
    await send_spendbundle(mempool_manager, sb1234)
    assert_sb_in_pool(mempool_manager, sb1234)
    assert_sb_not_in_pool(mempool_manager, sb12)
    assert_sb_not_in_pool(mempool_manager, sb3)


@pytest.mark.asyncio
async def test_replace_with_extra_eligible_coin() -> None:
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000010)))
    sb1234 = SpendBundle.aggregate([make_test_spendbundle(coins[i]) for i in range(4)])
    await send_spendbundle(mempool_manager, sb1234)
    assert_sb_in_pool(mempool_manager, sb1234)
    # Replace sb1234 with sb1234_2 which spends an eligible coin additionally
    eligible_sb = make_test_spendbundle(coins[4], fee=MEMPOOL_MIN_FEE_INCREASE, eligible_spend=True)
    sb1234_2 = SpendBundle.aggregate([sb1234, eligible_sb])
    await send_spendbundle(mempool_manager, sb1234_2)
    assert_sb_not_in_pool(mempool_manager, sb1234)
    assert_sb_in_pool(mempool_manager, sb1234_2)


@pytest.mark.asyncio
async def test_replacing_one_with_an_eligible_coin() -> None:
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000010)))
    sb123 = SpendBundle.aggregate([make_test_spendbundle(coins[i]) for i in range(3)])
    eligible_sb = make_test_spendbundle(coins[3], eligible_spend=True)
    sb123e = SpendBundle.aggregate([sb123, eligible_sb])
    await send_spendbundle(mempool_manager, sb123e)
    assert_sb_in_pool(mempool_manager, sb123e)
    # Replace sb123e with sb123e4
    sb4 = make_test_spendbundle(coins[4], fee=MEMPOOL_MIN_FEE_INCREASE)
    sb123e4 = SpendBundle.aggregate([sb123e, sb4])
    await send_spendbundle(mempool_manager, sb123e4)
    assert_sb_not_in_pool(mempool_manager, sb123e)
    assert_sb_in_pool(mempool_manager, sb123e4)


@pytest.mark.parametrize("amount", [0, 1])
def test_run_for_cost(amount: int) -> None:
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, amount]]
    solution = Program.to(conditions)
    cost = run_for_cost(IDENTITY_PUZZLE, solution, additions_count=1, max_cost=uint64(10000000))
    assert cost == uint64(1800044)


def test_run_for_cost_max_cost() -> None:
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    solution = Program.to(conditions)
    with pytest.raises(ValueError, match="('cost exceeded', '2b')"):
        run_for_cost(IDENTITY_PUZZLE, solution, additions_count=1, max_cost=uint64(43))


def test_dedup_info_nothing_to_do() -> None:
    # No eligible coins, nothing to deduplicate, item gets considered normally
    conditions = [
        [ConditionOpcode.AGG_SIG_UNSAFE, G1Element(), IDENTITY_PUZZLE_HASH],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
    ]
    sb = spend_bundle_from_conditions(conditions, TEST_COIN)
    mempool_item = mempool_item_from_spendbundle(sb)
    eligible_coin_spends = EligibleCoinSpends()
    unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
        bundle_coin_spends=mempool_item.bundle_coin_spends, max_cost=mempool_item.npc_result.cost
    )
    assert unique_coin_spends == sb.coin_spends
    assert cost_saving == 0
    assert unique_additions == [Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, 1)]
    assert eligible_coin_spends == EligibleCoinSpends()


def test_dedup_info_eligible_1st_time() -> None:
    # Eligible coin encountered for the first time
    conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 2],
    ]
    sb = spend_bundle_from_conditions(conditions, TEST_COIN)
    mempool_item = mempool_item_from_spendbundle(sb)
    eligible_coin_spends = EligibleCoinSpends()
    solution = SerializedProgram.from_program(Program.to(conditions))
    unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
        bundle_coin_spends=mempool_item.bundle_coin_spends, max_cost=mempool_item.npc_result.cost
    )
    assert unique_coin_spends == sb.coin_spends
    assert cost_saving == 0
    assert set(unique_additions) == {
        Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, 1),
        Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, 2),
    }
    assert eligible_coin_spends == EligibleCoinSpends({TEST_COIN_ID: DedupCoinSpend(solution=solution, cost=None)})


def test_dedup_info_eligible_but_different_solution() -> None:
    # Eligible coin but different solution from the one we encountered
    initial_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 2],
    ]
    initial_solution = SerializedProgram.from_program(Program.to(initial_conditions))
    eligible_coin_spends = EligibleCoinSpends({TEST_COIN_ID: DedupCoinSpend(solution=initial_solution, cost=None)})
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 2]]
    sb = spend_bundle_from_conditions(conditions, TEST_COIN)
    mempool_item = mempool_item_from_spendbundle(sb)
    with pytest.raises(ValueError, match="Solution is different from what we're deduplicating on"):
        eligible_coin_spends.get_deduplication_info(
            bundle_coin_spends=mempool_item.bundle_coin_spends, max_cost=mempool_item.npc_result.cost
        )


def test_dedup_info_eligible_2nd_time_and_another_1st_time() -> None:
    # Eligible coin encountered a second time, and another for the first time
    initial_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 2],
    ]
    initial_solution = SerializedProgram.from_program(Program.to(initial_conditions))
    eligible_coin_spends = EligibleCoinSpends({TEST_COIN_ID: DedupCoinSpend(solution=initial_solution, cost=None)})
    sb1 = spend_bundle_from_conditions(initial_conditions, TEST_COIN)
    second_conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 3]]
    second_solution = SerializedProgram.from_program(Program.to(second_conditions))
    sb2 = spend_bundle_from_conditions(second_conditions, TEST_COIN2)
    sb = SpendBundle.aggregate([sb1, sb2])
    mempool_item = mempool_item_from_spendbundle(sb)
    unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
        bundle_coin_spends=mempool_item.bundle_coin_spends, max_cost=mempool_item.npc_result.cost
    )
    # Only the eligible one that we encountered more than once gets deduplicated
    assert unique_coin_spends == sb2.coin_spends
    saved_cost = uint64(3600044)
    assert cost_saving == saved_cost
    assert unique_additions == [Coin(TEST_COIN_ID2, IDENTITY_PUZZLE_HASH, 3)]
    # The coin we encountered a second time has its cost and additions properly updated
    # The coin we encountered for the first time gets cost None and an empty set of additions
    expected_eligible_spends = EligibleCoinSpends(
        {
            TEST_COIN_ID: DedupCoinSpend(solution=initial_solution, cost=saved_cost),
            TEST_COIN_ID2: DedupCoinSpend(solution=second_solution, cost=None),
        }
    )
    assert eligible_coin_spends == expected_eligible_spends


def test_dedup_info_eligible_3rd_time_another_2nd_time_and_one_non_eligible() -> None:
    # Eligible coin encountered a third time, another for the second time and one non eligible
    initial_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 2],
    ]
    initial_solution = SerializedProgram.from_program(Program.to(initial_conditions))
    second_conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 3]]
    second_solution = SerializedProgram.from_program(Program.to(second_conditions))
    saved_cost = uint64(3600044)
    eligible_coin_spends = EligibleCoinSpends(
        {
            TEST_COIN_ID: DedupCoinSpend(solution=initial_solution, cost=saved_cost),
            TEST_COIN_ID2: DedupCoinSpend(solution=second_solution, cost=None),
        }
    )
    sb1 = spend_bundle_from_conditions(initial_conditions, TEST_COIN)
    sb2 = spend_bundle_from_conditions(second_conditions, TEST_COIN2)
    sb3_conditions = [
        [ConditionOpcode.AGG_SIG_UNSAFE, G1Element(), IDENTITY_PUZZLE_HASH],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 4],
    ]
    sb3 = spend_bundle_from_conditions(sb3_conditions, TEST_COIN3)
    sb = SpendBundle.aggregate([sb1, sb2, sb3])
    mempool_item = mempool_item_from_spendbundle(sb)
    unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
        bundle_coin_spends=mempool_item.bundle_coin_spends, max_cost=mempool_item.npc_result.cost
    )
    assert unique_coin_spends == sb3.coin_spends
    saved_cost2 = uint64(1800044)
    assert cost_saving == saved_cost + saved_cost2
    assert unique_additions == [Coin(TEST_COIN_ID3, IDENTITY_PUZZLE_HASH, 4)]
    expected_eligible_spends = EligibleCoinSpends(
        {
            TEST_COIN_ID: DedupCoinSpend(initial_solution, saved_cost),
            TEST_COIN_ID2: DedupCoinSpend(second_solution, saved_cost2),
        }
    )
    assert eligible_coin_spends == expected_eligible_spends


@pytest.mark.asyncio
@pytest.mark.parametrize("new_height_step", [1, 2, -1])
async def test_coin_spending_different_ways_then_finding_it_spent_in_new_peak(new_height_step: int) -> None:
    # This test makes sure all mempool items that spend a coin (in different ways)
    # that shows up as spent in a block, get removed properly.
    # NOTE: this test's parameter allows us to cover both the optimized and
    # the reorg code paths
    new_height = uint32(TEST_HEIGHT + new_height_step)
    coin = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, 100)
    coin_id = coin.name()
    test_coin_records = {coin_id: CoinRecord(coin, uint32(0), uint32(0), False, uint64(0))}

    async def get_coin_record(coin_id: bytes32) -> Optional[CoinRecord]:
        return test_coin_records.get(coin_id)

    mempool_manager = await instantiate_mempool_manager(get_coin_record)
    # Create a bunch of mempool items that spend the coin in different ways
    for i in range(3):
        _, _, result = await generate_and_add_spendbundle(
            mempool_manager, [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, i]], coin
        )
        assert result[1] == MempoolInclusionStatus.SUCCESS
    assert len(mempool_manager.mempool.get_items_by_coin_id(coin_id)) == 3
    assert mempool_manager.mempool.size() == 3
    assert len(list(mempool_manager.mempool.items_by_feerate())) == 3
    # Setup a new peak where the incoming block has spent the coin
    # Mark this coin as spent
    test_coin_records = {coin_id: CoinRecord(coin, uint32(0), TEST_HEIGHT, False, uint64(0))}
    block_record = create_test_block_record(height=new_height)
    npc_result = NPCResult(None, make_test_conds(spend_ids=[coin_id]), uint64(0))
    await mempool_manager.new_peak(block_record, npc_result)
    # As the coin was a spend in all the mempool items we had, nothing should be left now
    assert len(mempool_manager.mempool.get_items_by_coin_id(coin_id)) == 0
    assert mempool_manager.mempool.size() == 0
    assert len(list(mempool_manager.mempool.items_by_feerate())) == 0


@pytest.mark.asyncio
async def test_bundle_coin_spends() -> None:
    # This tests the construction of bundle_coin_spends map for mempool items
    # We're creating sb123e with 4 coins, one of them being eligible
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000005)))
    sb123 = SpendBundle.aggregate([make_test_spendbundle(coins[i]) for i in range(3)])
    eligible_sb = make_test_spendbundle(coins[3], eligible_spend=True)
    sb123e = SpendBundle.aggregate([sb123, eligible_sb])
    await send_spendbundle(mempool_manager, sb123e)
    mi123e = mempool_manager.get_mempool_item(sb123e.name())
    assert mi123e is not None
    for i in range(3):
        assert mi123e.bundle_coin_spends[coins[i].name()] == BundleCoinSpend(
            coin_spend=sb123.coin_spends[i],
            eligible_for_dedup=False,
            additions=[Coin(coins[i].name(), IDENTITY_PUZZLE_HASH, coins[i].amount)],
        )
    assert mi123e.bundle_coin_spends[coins[3].name()] == BundleCoinSpend(
        coin_spend=eligible_sb.coin_spends[0],
        eligible_for_dedup=True,
        additions=[Coin(coins[3].name(), IDENTITY_PUZZLE_HASH, coins[3].amount)],
    )


@pytest.mark.asyncio
async def test_identical_spend_aggregation_e2e(simulator_and_wallet: SimulatorsAndWallets, self_hostname: str) -> None:
    def get_sb_names_by_coin_id(
        full_node_api: FullNodeSimulator,
        spent_coin_id: bytes32,
    ) -> Set[bytes32]:
        return set(
            i.spend_bundle_name
            for i in full_node_api.full_node.mempool_manager.mempool.get_items_by_coin_id(spent_coin_id)
        )

    async def send_to_mempool(
        full_node: FullNodeSimulator, spend_bundle: SpendBundle, *, expecting_conflict: bool = False
    ) -> None:
        res = await full_node.send_transaction(wallet_protocol.SendTransaction(spend_bundle))
        assert res is not None and ProtocolMessageTypes(res.type) == ProtocolMessageTypes.transaction_ack
        res_parsed = wallet_protocol.TransactionAck.from_bytes(res.data)
        if expecting_conflict:
            assert res_parsed.status == MempoolInclusionStatus.PENDING.value
            assert res_parsed.error == "MEMPOOL_CONFLICT"
        else:
            assert res_parsed.status == MempoolInclusionStatus.SUCCESS.value

    async def farm_a_block(full_node_api: FullNodeSimulator, wallet_node: WalletNode, ph: bytes32) -> None:
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
        await full_node_api.wait_for_wallet_synced(wallet_node=wallet_node, timeout=30)

    async def make_setup_and_coins(
        full_node_api: FullNodeSimulator, wallet_node: WalletNode
    ) -> Tuple[Wallet, list[WalletCoinRecord], bytes32]:
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        phs = [await wallet.get_new_puzzlehash() for _ in range(3)]
        for _ in range(2):
            await farm_a_block(full_node_api, wallet_node, ph)
        other_recipients = [Payment(puzzle_hash=p, amount=uint64(200), memos=[]) for p in phs[1:]]
        tx = await wallet.generate_signed_transaction(uint64(200), phs[0], primaries=other_recipients)
        assert tx.spend_bundle is not None
        await send_to_mempool(full_node_api, tx.spend_bundle)
        await farm_a_block(full_node_api, wallet_node, ph)
        coins = list(await wallet_node.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(1))
        # Two blocks farmed plus 3 transactions
        assert len(coins) == 7
        return (wallet, coins, ph)

    [[full_node_api], [[wallet_node, wallet_server]], _] = simulator_and_wallet
    server = full_node_api.full_node.server
    await wallet_server.start_client(PeerInfo(self_hostname, uint16(server._port)), None)
    wallet, coins, ph = await make_setup_and_coins(full_node_api, wallet_node)

    # Make sure spending AB then BC would generate a conflict for the latter

    tx_a = await wallet.generate_signed_transaction(uint64(30), ph, coins={coins[0].coin})
    tx_b = await wallet.generate_signed_transaction(uint64(30), ph, coins={coins[1].coin})
    tx_c = await wallet.generate_signed_transaction(uint64(30), ph, coins={coins[2].coin})
    assert tx_a.spend_bundle is not None
    assert tx_b.spend_bundle is not None
    assert tx_c.spend_bundle is not None
    ab_bundle = SpendBundle.aggregate([tx_a.spend_bundle, tx_b.spend_bundle])
    await send_to_mempool(full_node_api, ab_bundle)
    # BC should conflict here (on B)
    bc_bundle = SpendBundle.aggregate([tx_b.spend_bundle, tx_c.spend_bundle])
    await send_to_mempool(full_node_api, bc_bundle, expecting_conflict=True)
    await farm_a_block(full_node_api, wallet_node, ph)

    # Make sure DE and EF would aggregate on E when E is eligible for deduplication

    # Create a coin with the identity puzzle hash
    tx = await wallet.generate_signed_transaction(uint64(200), IDENTITY_PUZZLE_HASH, coins={coins[3].coin})
    assert tx.spend_bundle is not None
    await send_to_mempool(full_node_api, tx.spend_bundle)
    await farm_a_block(full_node_api, wallet_node, ph)
    # Grab the coin we created and make an eligible coin out of it
    coins_with_identity_ph = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(
        False, IDENTITY_PUZZLE_HASH
    )
    sb = spend_bundle_from_conditions(
        [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 110]], coins_with_identity_ph[0].coin
    )
    await send_to_mempool(full_node_api, sb)
    await farm_a_block(full_node_api, wallet_node, ph)
    # Grab the eligible coin to spend as E in DE and EF transactions
    e_coin = (await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(False, IDENTITY_PUZZLE_HASH))[
        0
    ].coin
    e_coin_id = e_coin.name()
    # Restrict spending E with an announcement to consume
    message = b"Identical spend aggregation test"
    e_announcement = Announcement(e_coin_id, message)
    # Create transactions D and F that consume an announcement created by E
    tx_d = await wallet.generate_signed_transaction(
        uint64(100), ph, fee=uint64(0), coins={coins[4].coin}, coin_announcements_to_consume={e_announcement}
    )
    tx_f = await wallet.generate_signed_transaction(
        uint64(150), ph, fee=uint64(0), coins={coins[5].coin}, coin_announcements_to_consume={e_announcement}
    )
    assert tx_d.spend_bundle is not None
    assert tx_f.spend_bundle is not None
    # Create transaction E now that spends e_coin to create another eligible
    # coin as well as the announcement consumed by D and F
    conditions: List[List[Any]] = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 42],
        [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, message],
    ]
    sb_e = spend_bundle_from_conditions(conditions, e_coin)
    # Send DE and EF combinations to the mempool
    sb_de = SpendBundle.aggregate([tx_d.spend_bundle, sb_e])
    sb_de_name = sb_de.name()
    await send_to_mempool(full_node_api, sb_de)
    sb_ef = SpendBundle.aggregate([sb_e, tx_f.spend_bundle])
    sb_ef_name = sb_ef.name()
    await send_to_mempool(full_node_api, sb_ef)
    # Send also a transaction EG that spends E differently from DE and EF,
    # so that it doesn't get deduplicated on E with them
    conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, e_coin.amount - 1],
        [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, message],
    ]
    sb_e2 = spend_bundle_from_conditions(conditions, e_coin)
    g_coin = coins[6].coin
    g_coin_id = g_coin.name()
    tx_g = await wallet.generate_signed_transaction(
        uint64(13), ph, coins={g_coin}, coin_announcements_to_consume={e_announcement}
    )
    assert tx_g.spend_bundle is not None
    sb_e2g = SpendBundle.aggregate([sb_e2, tx_g.spend_bundle])
    sb_e2g_name = sb_e2g.name()
    await send_to_mempool(full_node_api, sb_e2g)

    # Make sure our coin IDs to spend bundles mappings are correct
    assert get_sb_names_by_coin_id(full_node_api, coins[4].coin.name()) == {sb_de_name}
    assert get_sb_names_by_coin_id(full_node_api, e_coin_id) == {sb_de_name, sb_ef_name, sb_e2g_name}
    assert get_sb_names_by_coin_id(full_node_api, coins[5].coin.name()) == {sb_ef_name}
    assert get_sb_names_by_coin_id(full_node_api, g_coin_id) == {sb_e2g_name}

    await farm_a_block(full_node_api, wallet_node, ph)

    # Make sure sb_de and sb_ef coins, including the deduplicated one, are removed
    # from the coin IDs to spend bundles mappings with the creation of a new block
    assert get_sb_names_by_coin_id(full_node_api, coins[4].coin.name()) == set()
    assert get_sb_names_by_coin_id(full_node_api, e_coin_id) == set()
    assert get_sb_names_by_coin_id(full_node_api, coins[5].coin.name()) == set()
    assert get_sb_names_by_coin_id(full_node_api, g_coin_id) == set()

    # Make sure coin G remains because E2G was removed as E got spent differently (by DE and EF)
    coins_set = await wallet_node.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(1)
    assert g_coin in (c.coin for c in coins_set)
    # Only the newly created eligible coin is left now
    eligible_coins = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(
        False, IDENTITY_PUZZLE_HASH
    )
    assert len(eligible_coins) == 1
    assert eligible_coins[0].coin.amount == 42
