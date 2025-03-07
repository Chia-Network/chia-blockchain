from __future__ import annotations

import dataclasses
import logging
from collections.abc import Awaitable, Collection, Sequence
from typing import Any, Callable, ClassVar, Optional, Union

import pytest
from chia_rs import (
    ELIGIBLE_FOR_DEDUP,
    ELIGIBLE_FOR_FF,
    AugSchemeMPL,
    ConsensusConstants,
    G2Element,
    get_conditions_from_spendbundle,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64
from chiabip158 import PyBIP158

from chia._tests.conftest import ConsensusMode
from chia._tests.util.misc import invariant_check_mempool
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets, setup_simulators_and_wallets
from chia.consensus.condition_costs import ConditionCost
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.mempool import MAX_SKIPPED_ITEMS, PRIORITY_TX_THRESHOLD
from chia.full_node.mempool_check_conditions import mempool_check_time_locks
from chia.full_node.mempool_manager import (
    MEMPOOL_MIN_FEE_INCREASE,
    QUOTE_BYTES,
    QUOTE_EXECUTION_COST,
    MempoolManager,
    TimelockConditions,
    can_replace,
    compute_assert_height,
    optional_max,
    optional_min,
)
from chia.protocols import wallet_protocol
from chia.protocols.full_node_protocol import RequestBlock, RespondBlock
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.clvm_cost import CLVMCost
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.eligible_coin_spends import (
    DedupCoinSpend,
    EligibilityAndAdditions,
    EligibleCoinSpends,
    UnspentLineageInfo,
    run_for_cost,
)
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.mempool_item import BundleCoinSpend, MempoolItem
from chia.types.peer_info import PeerInfo
from chia.types.spend_bundle import SpendBundle
from chia.types.spend_bundle_conditions import SpendBundleConditions, SpendConditions
from chia.util.errors import Err, ValidationError
from chia.wallet.conditions import AssertCoinAnnouncement
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_node import WalletNode

IDENTITY_PUZZLE = SerializedProgram.to(1)
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


@dataclasses.dataclass(frozen=True)
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


async def zero_calls_get_coin_records(coin_ids: Collection[bytes32]) -> list[CoinRecord]:
    assert len(coin_ids) == 0
    return []


async def zero_calls_get_unspent_lineage_info_for_puzzle_hash(_puzzle_hash: bytes32) -> Optional[UnspentLineageInfo]:
    assert False  # pragma no cover


async def get_coin_records_for_test_coins(coin_ids: Collection[bytes32]) -> list[CoinRecord]:
    test_coin_records = {
        TEST_COIN_ID: TEST_COIN_RECORD,
        TEST_COIN_ID2: TEST_COIN_RECORD2,
        TEST_COIN_ID3: TEST_COIN_RECORD3,
    }

    ret: list[CoinRecord] = []
    for name in coin_ids:
        r = test_coin_records.get(name)
        if r is not None:
            ret.append(r)
    return ret


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
    get_coin_records: Callable[[Collection[bytes32]], Awaitable[list[CoinRecord]]],
    *,
    block_height: uint32 = TEST_HEIGHT,
    block_timestamp: uint64 = TEST_TIMESTAMP,
    constants: ConsensusConstants = DEFAULT_CONSTANTS,
    max_tx_clvm_cost: Optional[uint64] = None,
) -> MempoolManager:
    mempool_manager = MempoolManager(
        get_coin_records,
        zero_calls_get_unspent_lineage_info_for_puzzle_hash,
        constants,
        max_tx_clvm_cost=max_tx_clvm_cost,
    )
    test_block_record = create_test_block_record(height=block_height, timestamp=block_timestamp)
    await mempool_manager.new_peak(test_block_record, None)
    invariant_check_mempool(mempool_manager.mempool)
    return mempool_manager


async def setup_mempool_with_coins(
    *,
    coin_amounts: list[int],
    max_block_clvm_cost: Optional[int] = None,
    max_tx_clvm_cost: Optional[uint64] = None,
    mempool_block_buffer: Optional[int] = None,
) -> tuple[MempoolManager, list[Coin]]:
    coins = []
    test_coin_records = {}
    for amount in coin_amounts:
        coin = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, uint64(amount))
        coins.append(coin)
        test_coin_records[coin.name()] = CoinRecord(coin, uint32(0), uint32(0), False, uint64(0))

    async def get_coin_records(coin_ids: Collection[bytes32]) -> list[CoinRecord]:
        ret: list[CoinRecord] = []
        for name in coin_ids:
            r = test_coin_records.get(name)
            if r is not None:
                ret.append(r)
        return ret

    constants = DEFAULT_CONSTANTS
    if max_block_clvm_cost is not None:
        constants = constants.replace(MAX_BLOCK_COST_CLVM=uint64(max_block_clvm_cost + TEST_BLOCK_OVERHEAD))
    if mempool_block_buffer is not None:
        constants = constants.replace(MEMPOOL_BLOCK_BUFFER=uint8(mempool_block_buffer))
    mempool_manager = await instantiate_mempool_manager(
        get_coin_records, constants=constants, max_tx_clvm_cost=max_tx_clvm_cost
    )
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
    spend_ids: Sequence[tuple[Union[bytes32, Coin], int]] = [(TEST_COIN_ID, 0)],
) -> SpendBundleConditions:
    spend_info: list[tuple[bytes32, bytes32, bytes32, uint64, int]] = []
    for coin, flags in spend_ids:
        if isinstance(coin, Coin):
            spend_info.append((coin.name(), coin.parent_coin_info, coin.puzzle_hash, coin.amount, flags))
        else:
            spend_info.append((coin, IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT, flags))

    return SpendBundleConditions(
        [
            SpendConditions(
                coin_id,
                parent_id,
                puzzle_hash,
                amount,
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
                flags,
            )
            for coin_id, parent_id, puzzle_hash, amount, flags in spend_info
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
        False,
        0,
        0,
    )


class TestCheckTimeLocks:
    COIN_CONFIRMED_HEIGHT: ClassVar[uint32] = uint32(10)
    COIN_TIMESTAMP: ClassVar[uint64] = uint64(10000)
    PREV_BLOCK_HEIGHT: ClassVar[uint32] = uint32(15)
    PREV_BLOCK_TIMESTAMP: ClassVar[uint64] = uint64(10150)

    COIN_RECORD: ClassVar[CoinRecord] = CoinRecord(
        TEST_COIN,
        confirmed_block_index=uint32(COIN_CONFIRMED_HEIGHT),
        spent_block_index=uint32(0),
        coinbase=False,
        timestamp=COIN_TIMESTAMP,
    )
    REMOVALS: ClassVar[dict[bytes32, CoinRecord]] = {TEST_COIN.name(): COIN_RECORD}

    @pytest.mark.parametrize(
        "conds,expected",
        [
            (make_test_conds(height_relative=5), None),
            (make_test_conds(height_relative=6), Err.ASSERT_HEIGHT_RELATIVE_FAILED),
            (make_test_conds(height_absolute=PREV_BLOCK_HEIGHT), None),
            (make_test_conds(height_absolute=uint32(PREV_BLOCK_HEIGHT + 1)), Err.ASSERT_HEIGHT_ABSOLUTE_FAILED),
            (make_test_conds(seconds_relative=150), None),
            (make_test_conds(seconds_relative=151), Err.ASSERT_SECONDS_RELATIVE_FAILED),
            (make_test_conds(seconds_absolute=PREV_BLOCK_TIMESTAMP), None),
            (make_test_conds(seconds_absolute=uint64(PREV_BLOCK_TIMESTAMP + 1)), Err.ASSERT_SECONDS_ABSOLUTE_FAILED),
            # the coin's confirmed height is 10
            (make_test_conds(birth_height=9), Err.ASSERT_MY_BIRTH_HEIGHT_FAILED),
            (make_test_conds(birth_height=10), None),
            (make_test_conds(birth_height=11), Err.ASSERT_MY_BIRTH_HEIGHT_FAILED),
            # coin timestamp is 10000
            (make_test_conds(birth_seconds=uint64(COIN_TIMESTAMP - 1)), Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            (make_test_conds(birth_seconds=COIN_TIMESTAMP), None),
            (make_test_conds(birth_seconds=uint64(COIN_TIMESTAMP + 1)), Err.ASSERT_MY_BIRTH_SECONDS_FAILED),
            # the coin is 5 blocks old in this test
            (make_test_conds(before_height_relative=5), Err.ASSERT_BEFORE_HEIGHT_RELATIVE_FAILED),
            (make_test_conds(before_height_relative=6), None),
            # The block height is 15
            (make_test_conds(before_height_absolute=PREV_BLOCK_HEIGHT), Err.ASSERT_BEFORE_HEIGHT_ABSOLUTE_FAILED),
            (make_test_conds(before_height_absolute=uint64(PREV_BLOCK_HEIGHT + 1)), None),
            # the coin is 150 seconds old in this test
            (make_test_conds(before_seconds_relative=150), Err.ASSERT_BEFORE_SECONDS_RELATIVE_FAILED),
            (make_test_conds(before_seconds_relative=151), None),
            # The block timestamp is 10150
            (make_test_conds(before_seconds_absolute=PREV_BLOCK_TIMESTAMP), Err.ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED),
            (make_test_conds(before_seconds_absolute=uint64(PREV_BLOCK_TIMESTAMP + 1)), None),
        ],
    )
    def test_conditions(
        self,
        conds: SpendBundleConditions,
        expected: Optional[Err],
    ) -> None:
        assert (
            mempool_check_time_locks(
                dict(self.REMOVALS),
                conds,
                self.PREV_BLOCK_HEIGHT,
                self.PREV_BLOCK_TIMESTAMP,
            )
            == expected
        )


def expect(
    *, height: int = 0, seconds: int = 0, before_height: Optional[int] = None, before_seconds: Optional[int] = None
) -> TimelockConditions:
    ret = TimelockConditions(uint32(height), uint64(seconds))
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
        # ASSERT_SECONDS_*
        # coin timestamp is 10000
        # single absolute assert seconds
        (make_test_conds(seconds_absolute=20000), expect(seconds=20000)),
        # coin is created at 10000 + 100 relative seconds = 10100
        (make_test_conds(seconds_relative=100), expect(seconds=10100)),
        # coin is created at 10000 + 0 relative seconds = 10000
        (make_test_conds(seconds_relative=0), expect(seconds=10000)),
        # 20000 is more restrictive than 10100
        (make_test_conds(seconds_absolute=20000, seconds_relative=100), expect(seconds=20000)),
        # 20000 is a relative seconds, and since the coin was confirmed at seconds
        # 10000 that's 300000
        (make_test_conds(seconds_absolute=20000, seconds_relative=20000), expect(seconds=30000)),
        # Same thing but without the absolute seconds
        (make_test_conds(seconds_relative=20000), expect(seconds=30000)),
    ],
)
def test_compute_assert_height(conds: SpendBundleConditions, expected: TimelockConditions) -> None:
    coin_id = TEST_COIN.name()

    confirmed_height = uint32(12)
    coin_records = {coin_id: CoinRecord(TEST_COIN, confirmed_height, uint32(0), False, uint64(10000))}

    assert compute_assert_height(coin_records, conds) == expected


def spend_bundle_from_conditions(
    conditions: list[list[Any]], coin: Coin = TEST_COIN, aggsig: G2Element = G2Element()
) -> SpendBundle:
    solution = SerializedProgram.to(conditions)
    coin_spend = make_spend(coin, IDENTITY_PUZZLE, solution)
    return SpendBundle([coin_spend], aggsig)


async def add_spendbundle(
    mempool_manager: MempoolManager, sb: SpendBundle, sb_name: bytes32
) -> tuple[Optional[uint64], MempoolInclusionStatus, Optional[Err]]:
    sbc = await mempool_manager.pre_validate_spendbundle(sb, sb_name)
    ret = await mempool_manager.add_spend_bundle(sb, sbc, sb_name, TEST_HEIGHT)
    invariant_check_mempool(mempool_manager.mempool)
    return ret.cost, ret.status, ret.error


async def generate_and_add_spendbundle(
    mempool_manager: MempoolManager,
    conditions: list[list[Any]],
    coin: Coin = TEST_COIN,
    aggsig: G2Element = G2Element(),
) -> tuple[SpendBundle, bytes32, tuple[Optional[uint64], MempoolInclusionStatus, Optional[Err]]]:
    sb = spend_bundle_from_conditions(conditions, coin, aggsig)
    sb_name = sb.name()
    result = await add_spendbundle(mempool_manager, sb, sb_name)
    return (sb, sb_name, result)


def make_bundle_spends_map_and_fee(
    spend_bundle: SpendBundle, conds: SpendBundleConditions
) -> tuple[dict[bytes32, BundleCoinSpend], uint64]:
    bundle_coin_spends: dict[bytes32, BundleCoinSpend] = {}
    eligibility_and_additions: dict[bytes32, EligibilityAndAdditions] = {}
    removals_amount = 0
    additions_amount = 0
    for spend in conds.spends:
        coin_id = bytes32(spend.coin_id)
        spend_additions = []
        for puzzle_hash, amount, _ in spend.create_coin:
            spend_additions.append(Coin(coin_id, puzzle_hash, uint64(amount)))
            additions_amount += amount
        eligibility_and_additions[coin_id] = EligibilityAndAdditions(
            is_eligible_for_dedup=bool(spend.flags & ELIGIBLE_FOR_DEDUP),
            spend_additions=spend_additions,
            ff_puzzle_hash=bytes32(spend.puzzle_hash) if bool(spend.flags & ELIGIBLE_FOR_FF) else None,
        )
    for coin_spend in spend_bundle.coin_spends:
        coin_id = coin_spend.coin.name()
        removals_amount += coin_spend.coin.amount
        eligibility_info = eligibility_and_additions.get(
            coin_id, EligibilityAndAdditions(is_eligible_for_dedup=False, spend_additions=[], ff_puzzle_hash=None)
        )
        bundle_coin_spends[coin_id] = BundleCoinSpend(
            coin_spend=coin_spend,
            eligible_for_dedup=eligibility_info.is_eligible_for_dedup,
            eligible_for_fast_forward=eligibility_info.ff_puzzle_hash is not None,
            additions=eligibility_info.spend_additions,
        )
    fee = uint64(removals_amount - additions_amount)
    return bundle_coin_spends, fee


def mempool_item_from_spendbundle(spend_bundle: SpendBundle) -> MempoolItem:
    conds = get_conditions_from_spendbundle(spend_bundle, INFINITE_COST, DEFAULT_CONSTANTS, uint32(0))
    bundle_coin_spends, fee = make_bundle_spends_map_and_fee(spend_bundle, conds)
    return MempoolItem(
        spend_bundle=spend_bundle,
        fee=fee,
        conds=conds,
        spend_bundle_name=spend_bundle.name(),
        height_added_to_mempool=TEST_HEIGHT,
        bundle_coin_spends=bundle_coin_spends,
    )


@pytest.mark.anyio
async def test_empty_spend_bundle() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    sb = SpendBundle([], G2Element())
    with pytest.raises(ValidationError, match="INVALID_SPEND_BUNDLE"):
        await mempool_manager.pre_validate_spendbundle(sb)


@pytest.mark.anyio
async def test_negative_addition_amount() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, -1]]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="COIN_AMOUNT_NEGATIVE"):
        await mempool_manager.pre_validate_spendbundle(sb)


@pytest.mark.anyio
async def test_valid_addition_amount() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    max_amount = mempool_manager.constants.MAX_COIN_AMOUNT
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, max_amount]]
    coin = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, max_amount)
    sb = spend_bundle_from_conditions(conditions, coin)
    # ensure this does not throw
    _ = await mempool_manager.pre_validate_spendbundle(sb)


@pytest.mark.anyio
async def test_too_big_addition_amount() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    max_amount = mempool_manager.constants.MAX_COIN_AMOUNT
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, max_amount + 1]]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="COIN_AMOUNT_EXCEEDS_MAXIMUM"):
        await mempool_manager.pre_validate_spendbundle(sb)


@pytest.mark.anyio
async def test_duplicate_output() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
    ]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="DUPLICATE_OUTPUT"):
        await mempool_manager.pre_validate_spendbundle(sb)


@pytest.mark.anyio
async def test_block_cost_exceeds_max() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    conditions = []
    for i in range(2400):
        conditions.append([ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, i])
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="BLOCK_COST_EXCEEDS_MAX"):
        await mempool_manager.pre_validate_spendbundle(sb)


@pytest.mark.anyio
async def test_double_spend_prevalidation() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    sb = spend_bundle_from_conditions(conditions)
    sb_twice = SpendBundle.aggregate([sb, sb])
    with pytest.raises(ValidationError, match="DOUBLE_SPEND"):
        await mempool_manager.pre_validate_spendbundle(sb_twice)


@pytest.mark.anyio
async def test_minting_coin() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT]]
    sb = spend_bundle_from_conditions(conditions)
    _ = await mempool_manager.pre_validate_spendbundle(sb)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT + 1]]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="MINTING_COIN"):
        await mempool_manager.pre_validate_spendbundle(sb)


@pytest.mark.anyio
async def test_reserve_fee_condition() -> None:
    mempool_manager = await instantiate_mempool_manager(zero_calls_get_coin_records)
    conditions = [[ConditionOpcode.RESERVE_FEE, TEST_COIN_AMOUNT]]
    sb = spend_bundle_from_conditions(conditions)
    _ = await mempool_manager.pre_validate_spendbundle(sb)
    conditions = [[ConditionOpcode.RESERVE_FEE, TEST_COIN_AMOUNT + 1]]
    sb = spend_bundle_from_conditions(conditions)
    with pytest.raises(ValidationError, match="RESERVE_FEE_CONDITION_FAILED"):
        await mempool_manager.pre_validate_spendbundle(sb)


@pytest.mark.anyio
async def test_unknown_unspent() -> None:
    async def get_coin_records(_: Collection[bytes32]) -> list[CoinRecord]:
        return []

    mempool_manager = await instantiate_mempool_manager(get_coin_records)
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    _, _, result = await generate_and_add_spendbundle(mempool_manager, conditions)
    assert result == (None, MempoolInclusionStatus.FAILED, Err.UNKNOWN_UNSPENT)


@pytest.mark.anyio
async def test_same_sb_twice_with_eligible_coin() -> None:
    mempool_manager = await instantiate_mempool_manager(get_coin_records_for_test_coins)
    sb1_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 2],
    ]
    sb1 = spend_bundle_from_conditions(sb1_conditions)
    sk = AugSchemeMPL.key_gen(b"5" * 32)
    g1 = sk.get_g1()
    sig = AugSchemeMPL.sign(sk, IDENTITY_PUZZLE_HASH, g1)
    sb2_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 3],
        [ConditionOpcode.AGG_SIG_UNSAFE, g1, IDENTITY_PUZZLE_HASH],
    ]
    sb2 = spend_bundle_from_conditions(sb2_conditions, TEST_COIN2, sig)
    sb = SpendBundle.aggregate([sb1, sb2])
    sb_name = sb.name()
    result = await add_spendbundle(mempool_manager, sb, sb_name)
    expected_cost = uint64(10_236_088)
    assert result == (expected_cost, MempoolInclusionStatus.SUCCESS, None)
    assert mempool_manager.get_spendbundle(sb_name) == sb
    result = await add_spendbundle(mempool_manager, sb, sb_name)
    assert result == (expected_cost, MempoolInclusionStatus.SUCCESS, None)
    assert mempool_manager.get_spendbundle(sb_name) == sb


@pytest.mark.anyio
async def test_sb_twice_with_eligible_coin_and_different_spends_order() -> None:
    mempool_manager = await instantiate_mempool_manager(get_coin_records_for_test_coins)
    sb1_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 2],
    ]
    sb1 = spend_bundle_from_conditions(sb1_conditions)
    sk = AugSchemeMPL.key_gen(b"6" * 32)
    g1 = sk.get_g1()
    sig = AugSchemeMPL.sign(sk, IDENTITY_PUZZLE_HASH, g1)
    sb2_conditions: list[list[Any]] = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 3],
        [ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), IDENTITY_PUZZLE_HASH],
    ]
    sb2 = spend_bundle_from_conditions(sb2_conditions, TEST_COIN2, sig)
    sb3_conditions = [[ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), IDENTITY_PUZZLE_HASH]]
    sb3 = spend_bundle_from_conditions(sb3_conditions, TEST_COIN3, sig)
    sb = SpendBundle.aggregate([sb1, sb2, sb3])
    sb_name = sb.name()
    reordered_sb = SpendBundle.aggregate([sb3, sb1, sb2])
    reordered_sb_name = reordered_sb.name()
    assert mempool_manager.get_spendbundle(sb_name) is None
    assert mempool_manager.get_spendbundle(reordered_sb_name) is None
    result = await add_spendbundle(mempool_manager, sb, sb_name)
    expected_cost = uint64(13_056_132)
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


@pytest.mark.anyio
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
) -> None:
    mempool_manager = await instantiate_mempool_manager(
        get_coin_records=get_coin_records_for_test_coins,
        block_height=uint32(5),
        block_timestamp=uint64(10050),
        constants=DEFAULT_CONSTANTS,
    )

    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    created_coin = Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, uint64(1))
    sb1 = spend_bundle_from_conditions(conditions)
    sb2 = spend_bundle_from_conditions([[opcode, lock_value]], created_coin)
    # sb spends TEST_COIN and creates created_coin which gets spent too
    sb = SpendBundle.aggregate([sb1, sb2])
    # We shouldn't have a record of this ephemeral coin
    assert await get_coin_records_for_test_coins([created_coin.name()]) == []
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
    coins: list[Coin],
    *,
    cost: int = 1,
    fee: int = 0,
    assert_height: Optional[int] = None,
    assert_before_height: Optional[int] = None,
    assert_before_seconds: Optional[int] = None,
    flags: list[int] = [],
) -> MempoolItem:
    # we don't actually care about the puzzle and solutions for the purpose of
    # can_replace()
    spend_ids: list[tuple[bytes32, int]] = []
    coin_spends = []
    bundle_coin_spends = {}
    if len(flags) < len(coins):
        flags.extend([0] * (len(coins) - len(flags)))
    for c, f in zip(coins, flags):
        coin_id = c.name()
        spend_ids.append((coin_id, f))
        spend = make_spend(c, SerializedProgram.to(None), SerializedProgram.to(None))
        coin_spends.append(spend)
        bundle_coin_spends[coin_id] = BundleCoinSpend(
            coin_spend=spend,
            eligible_for_dedup=bool(f & ELIGIBLE_FOR_DEDUP),
            eligible_for_fast_forward=bool(f & ELIGIBLE_FOR_FF),
            additions=[],
        )
    spend_bundle = SpendBundle(coin_spends, G2Element())
    conds = make_test_conds(cost=cost, spend_ids=spend_ids)
    return MempoolItem(
        spend_bundle=spend_bundle,
        fee=uint64(fee),
        conds=conds,
        spend_bundle_name=spend_bundle.name(),
        height_added_to_mempool=uint32(0),
        assert_height=None if assert_height is None else uint32(assert_height),
        assert_before_height=None if assert_before_height is None else uint32(assert_before_height),
        assert_before_seconds=None if assert_before_seconds is None else uint64(assert_before_seconds),
        bundle_coin_spends=bundle_coin_spends,
    )


def make_test_coins() -> list[Coin]:
    ret: list[Coin] = []
    for i in range(5):
        ret.append(Coin(height_hash(i), height_hash(i + 100), uint64(i * 100)))
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
        # you're not allowed to clear the fast-forward or dedup flag. It's OK to set it
        # and leave it unchanged
        ([mk_item(coins[0:2])], mk_item(coins[0:3], flags=[ELIGIBLE_FOR_DEDUP, 0, 0], fee=10000000), True),
        ([mk_item(coins[0:2])], mk_item(coins[0:3], flags=[ELIGIBLE_FOR_FF, 0, 0], fee=10000000), True),
        # flag cleared
        ([mk_item(coins[0:2], flags=[ELIGIBLE_FOR_DEDUP, 0])], mk_item(coins[0:3], fee=10000000), False),
        ([mk_item(coins[0:2], flags=[ELIGIBLE_FOR_FF, 0])], mk_item(coins[0:3], fee=10000000), False),
        # unchanged
        (
            [mk_item(coins[0:2], flags=[ELIGIBLE_FOR_DEDUP, 0])],
            mk_item(coins[0:3], flags=[ELIGIBLE_FOR_DEDUP, 0, 0], fee=10000000),
            True,
        ),
        (
            [mk_item(coins[0:2], flags=[ELIGIBLE_FOR_FF, 0])],
            mk_item(coins[0:3], flags=[ELIGIBLE_FOR_FF, 0, 0], fee=10000000),
            True,
        ),
        # the spends are independent
        (
            [mk_item(coins[0:2], flags=[ELIGIBLE_FOR_DEDUP, 0])],
            mk_item(coins[0:3], flags=[0, ELIGIBLE_FOR_DEDUP, 0], fee=10000000),
            False,
        ),
        (
            [mk_item(coins[0:2], flags=[ELIGIBLE_FOR_FF, 0])],
            mk_item(coins[0:3], flags=[0, ELIGIBLE_FOR_FF, 0], fee=10000000),
            False,
        ),
        # the bits are independent
        (
            [mk_item(coins[0:2], flags=[ELIGIBLE_FOR_DEDUP, 0])],
            mk_item(coins[0:3], flags=[ELIGIBLE_FOR_FF, 0, 0], fee=10000000),
            False,
        ),
        (
            [mk_item(coins[0:2], flags=[ELIGIBLE_FOR_DEDUP, 0])],
            mk_item(coins[0:3], flags=[ELIGIBLE_FOR_FF, 0, 0], fee=10000000),
            False,
        ),
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
def test_can_replace(existing_items: list[MempoolItem], new_item: MempoolItem, expected: bool) -> None:
    removals = {c.name() for c in new_item.spend_bundle.removals()}
    assert can_replace(existing_items, removals, new_item) == expected


@pytest.mark.anyio
async def test_get_items_not_in_filter() -> None:
    mempool_manager = await instantiate_mempool_manager(get_coin_records_for_test_coins)
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


@pytest.mark.anyio
async def test_total_mempool_fees() -> None:
    coin_records: dict[bytes32, CoinRecord] = {}

    async def get_coin_records(coin_ids: Collection[bytes32]) -> list[CoinRecord]:
        ret: list[CoinRecord] = []
        for name in coin_ids:
            r = coin_records.get(name)
            if r is not None:
                ret.append(r)
        return ret

    mempool_manager = await instantiate_mempool_manager(get_coin_records)
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
@pytest.mark.anyio
async def test_create_bundle_from_mempool(reverse_tx_order: bool) -> None:
    async def make_coin_spends(coins: list[Coin], *, high_fees: bool = True) -> list[CoinSpend]:
        spends_list = []
        for i in range(0, len(coins)):
            coin_spend = make_spend(
                coins[i],
                IDENTITY_PUZZLE,
                Program.to(
                    [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, i if high_fees else (coins[i].amount - 1)]]
                ),
            )
            spends_list.append(coin_spend)
        return spends_list

    async def send_spends_to_mempool(coin_spends: list[CoinSpend]) -> None:
        g2 = G2Element()
        for cs in coin_spends:
            sb = SpendBundle([cs], g2)
            result = await add_spendbundle(mempool_manager, sb, sb.name())
            assert result[1] == MempoolInclusionStatus.SUCCESS

    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(2000000000, 2000002200)))
    high_rate_spends = await make_coin_spends(coins[0:2200])
    low_rate_spends = await make_coin_spends(coins[2200:2400], high_fees=False)
    spends = low_rate_spends + high_rate_spends if reverse_tx_order else high_rate_spends + low_rate_spends
    await send_spends_to_mempool(spends)
    assert mempool_manager.peak is not None
    result = await mempool_manager.create_bundle_from_mempool(mempool_manager.peak.header_hash)
    assert result is not None
    # Make sure we filled the block with only high rate spends
    assert len([s for s in high_rate_spends if s in result[0].coin_spends]) == len(result[0].coin_spends)
    assert len([s for s in low_rate_spends if s in result[0].coin_spends]) == 0


@pytest.mark.parametrize("num_skipped_items", [PRIORITY_TX_THRESHOLD, MAX_SKIPPED_ITEMS])
@pytest.mark.anyio
async def test_create_bundle_from_mempool_on_max_cost(num_skipped_items: int, caplog: pytest.LogCaptureFixture) -> None:
    """
    This test exercises the path where an item's inclusion would exceed the
    maximum cumulative cost, so it gets skipped as a result.

    NOTE:
      1. After PRIORITY_TX_THRESHOLD, we skip items with eligible coins.
      2. After skipping MAX_SKIPPED_ITEMS, we stop processing further items.
    """

    MAX_BLOCK_CLVM_COST = 550_000_000

    mempool_manager, coins = await setup_mempool_with_coins(
        coin_amounts=list(range(1_000_000_000, 1_000_000_030)),
        max_block_clvm_cost=MAX_BLOCK_CLVM_COST,
        max_tx_clvm_cost=uint64(MAX_BLOCK_CLVM_COST),
        mempool_block_buffer=20,
    )

    async def make_and_send_big_cost_sb(coin: Coin) -> None:
        """
        Creates a spend bundle with a big enough cost that gets it close to the
        maximum block clvm cost limit.
        """
        conditions = []
        sk = AugSchemeMPL.key_gen(b"7" * 32)
        g1 = sk.get_g1()
        sig = AugSchemeMPL.sign(sk, IDENTITY_PUZZLE_HASH, g1)
        aggsig = G2Element()
        # Let's get as close to `MAX_BLOCK_CLVM_COST` (550_000_000) as possible.
        # We start by accounting for execution cost
        spend_bundle_cost = 44
        # And then the created coin
        conditions.append([ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, coin.amount - 10_000_000])
        TEST_CREATE_COIN_SPEND_BYTESIZE = 93
        TEST_CREATE_COIN_CONDITION_COST = (
            ConditionCost.CREATE_COIN.value + TEST_CREATE_COIN_SPEND_BYTESIZE * DEFAULT_CONSTANTS.COST_PER_BYTE
        )
        spend_bundle_cost += TEST_CREATE_COIN_CONDITION_COST
        # We're using agg sig conditions to increase the spend bundle's cost
        # and reach our target cost.
        TEST_AGG_SIG_SPEND_BYTESIZE = 88
        TEST_AGGSIG_CONDITION_COST = (
            ConditionCost.AGG_SIG.value + TEST_AGG_SIG_SPEND_BYTESIZE * DEFAULT_CONSTANTS.COST_PER_BYTE
        )
        while spend_bundle_cost + TEST_AGGSIG_CONDITION_COST < MAX_BLOCK_CLVM_COST:
            conditions.append([ConditionOpcode.AGG_SIG_UNSAFE, g1, IDENTITY_PUZZLE_HASH])
            aggsig += sig
            spend_bundle_cost += TEST_AGGSIG_CONDITION_COST
        # We now have a spend bundle with a big enough cost that gets it close to the limit
        _, _, res = await generate_and_add_spendbundle(mempool_manager, conditions, coin, aggsig)
        cost, status, _ = res
        assert status == MempoolInclusionStatus.SUCCESS
        assert cost == spend_bundle_cost

    # Create the spend bundles with a big enough cost that they get close to the limit
    for i in range(num_skipped_items):
        await make_and_send_big_cost_sb(coins[i])

    # Create a spend bundle with a relatively smaller cost.
    # Combined with a big cost spend bundle, we'd exceed the maximum block clvm cost
    sb2_coin = coins[num_skipped_items]
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, sb2_coin.amount - 200_000]]
    sb2, _, res = await generate_and_add_spendbundle(mempool_manager, conditions, sb2_coin)
    assert res[1] == MempoolInclusionStatus.SUCCESS
    sb2_addition = Coin(sb2_coin.name(), IDENTITY_PUZZLE_HASH, uint64(sb2_coin.amount - 200_000))
    # Create 4 extra spend bundles with smaller FPC and smaller costs
    extra_sbs = []
    extra_additions = []
    sk = AugSchemeMPL.key_gen(b"8" * 32)
    g1 = sk.get_g1()
    sig = AugSchemeMPL.sign(sk, b"foobar", g1)
    for i in range(num_skipped_items + 1, num_skipped_items + 5):
        conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, coins[i].amount]]
        # Make the first of these without eligible coins
        if i == num_skipped_items + 1:
            conditions.append([ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), b"foobar"])
            aggsig = sig
        else:
            aggsig = G2Element()
        sb, _, res = await generate_and_add_spendbundle(mempool_manager, conditions, coins[i], aggsig)
        extra_sbs.append(sb)
        coin = Coin(coins[i].name(), IDENTITY_PUZZLE_HASH, uint64(coins[i].amount))
        extra_additions.append(coin)
        assert res[1] == MempoolInclusionStatus.SUCCESS

    assert mempool_manager.peak is not None
    caplog.set_level(logging.DEBUG)
    result = await mempool_manager.create_bundle_from_mempool(mempool_manager.peak.header_hash)
    assert result is not None
    agg, additions = result
    skipped_due_to_eligible_coins = sum(
        1
        for line in caplog.text.split("\n")
        if "Exception while checking a mempool item for deduplication: Skipping transaction with eligible coin(s)"
        in line
    )
    if num_skipped_items == PRIORITY_TX_THRESHOLD:
        # We skipped enough big cost items to reach `PRIORITY_TX_THRESHOLD`,
        # so the first from the extra 4 (the one without eligible coins) went in,
        # and the other 3 were skipped (they have eligible coins)
        assert skipped_due_to_eligible_coins == 3
        assert agg == SpendBundle.aggregate([sb2, extra_sbs[0]])
        assert additions == [sb2_addition, extra_additions[0]]
        assert agg.removals() == [sb2_coin, coins[num_skipped_items + 1]]
    elif num_skipped_items == MAX_SKIPPED_ITEMS:
        # We skipped enough big cost items to trigger `MAX_SKIPPED_ITEMS` so
        # we didn't process any of the extra items
        assert skipped_due_to_eligible_coins == 0
        assert agg == SpendBundle.aggregate([sb2])
        assert additions == [sb2_addition]
        assert agg.removals() == [sb2_coin]
    else:
        raise ValueError("num_skipped_items must be PRIORITY_TX_THRESHOLD or MAX_SKIPPED_ITEMS")  # pragma: no cover


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
@pytest.mark.anyio
async def test_assert_before_expiration(
    opcode: ConditionOpcode, arg: int, expect_eviction: bool, expect_limit: Optional[int]
) -> None:
    async def get_coin_records(coin_ids: Collection[bytes32]) -> list[CoinRecord]:
        all_coins = {TEST_COIN.name(): CoinRecord(TEST_COIN, uint32(5), uint32(0), False, uint64(9900))}
        ret: list[CoinRecord] = []
        for name in coin_ids:
            r = all_coins.get(name)
            if r is not None:
                ret.append(r)
        return ret

    mempool_manager = await instantiate_mempool_manager(
        get_coin_records,
        block_height=uint32(10),
        block_timestamp=uint64(10000),
        constants=DEFAULT_CONSTANTS,
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
    invariant_check_mempool(mempool_manager.mempool)

    still_in_pool = mempool_manager.get_spendbundle(bundle_name) == bundle
    assert still_in_pool != expect_eviction
    if still_in_pool:
        assert expect_limit is not None
        item = mempool_manager.get_mempool_item(bundle_name)
        assert item is not None
        if opcode in {co.ASSERT_BEFORE_SECONDS_ABSOLUTE, co.ASSERT_BEFORE_SECONDS_RELATIVE}:
            assert item.assert_before_seconds == expect_limit
        elif opcode in {co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, co.ASSERT_BEFORE_HEIGHT_RELATIVE}:
            assert item.assert_before_height == expect_limit
        else:
            assert False


def make_test_spendbundle(coin: Coin, *, fee: int = 0, eligible_spend: bool = False) -> SpendBundle:
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, uint64(coin.amount - fee)]]
    sig = G2Element()
    if not eligible_spend:
        sk = AugSchemeMPL.key_gen(b"2" * 32)
        g1 = sk.get_g1()
        sig = AugSchemeMPL.sign(sk, b"foobar", g1)
        conditions.append([ConditionOpcode.AGG_SIG_UNSAFE, g1, b"foobar"])
    return spend_bundle_from_conditions(conditions, coin, sig)


async def send_spendbundle(
    mempool_manager: MempoolManager,
    sb: SpendBundle,
    expected_result: tuple[MempoolInclusionStatus, Optional[Err]] = (MempoolInclusionStatus.SUCCESS, None),
) -> None:
    result = await add_spendbundle(mempool_manager, sb, sb.name())
    assert (result[1], result[2]) == expected_result


async def make_and_send_spendbundle(
    mempool_manager: MempoolManager,
    coin: Coin,
    *,
    fee: int = 0,
    expected_result: tuple[MempoolInclusionStatus, Optional[Err]] = (MempoolInclusionStatus.SUCCESS, None),
) -> SpendBundle:
    sb = make_test_spendbundle(coin, fee=fee)
    await send_spendbundle(mempool_manager, sb, expected_result)
    return sb


def assert_sb_in_pool(mempool_manager: MempoolManager, sb: SpendBundle) -> None:
    assert sb == mempool_manager.get_spendbundle(sb.name())


def assert_sb_not_in_pool(mempool_manager: MempoolManager, sb: SpendBundle) -> None:
    assert mempool_manager.get_spendbundle(sb.name()) is None


@pytest.mark.anyio
async def test_insufficient_fee_increase() -> None:
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000010)))
    sb1_1 = await make_and_send_spendbundle(mempool_manager, coins[0])
    sb1_2 = await make_and_send_spendbundle(
        mempool_manager, coins[0], fee=1, expected_result=(MempoolInclusionStatus.PENDING, Err.MEMPOOL_CONFLICT)
    )
    # The old spendbundle must stay
    assert_sb_in_pool(mempool_manager, sb1_1)
    assert_sb_not_in_pool(mempool_manager, sb1_2)


@pytest.mark.anyio
async def test_sufficient_fee_increase() -> None:
    mempool_manager, coins = await setup_mempool_with_coins(coin_amounts=list(range(1000000000, 1000000010)))
    sb1_1 = await make_and_send_spendbundle(mempool_manager, coins[0])
    sb1_2 = await make_and_send_spendbundle(mempool_manager, coins[0], fee=MEMPOOL_MIN_FEE_INCREASE)
    # sb1_1 gets replaced with sb1_2
    assert_sb_not_in_pool(mempool_manager, sb1_1)
    assert_sb_in_pool(mempool_manager, sb1_2)


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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
    solution = SerializedProgram.to(conditions)
    cost = run_for_cost(IDENTITY_PUZZLE, solution, additions_count=1, max_cost=uint64(10000000))
    assert cost == uint64(1800044)


def test_run_for_cost_max_cost() -> None:
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    solution = SerializedProgram.to(conditions)
    with pytest.raises(ValueError, match="cost exceeded"):
        run_for_cost(IDENTITY_PUZZLE, solution, additions_count=1, max_cost=uint64(43))


def test_dedup_info_nothing_to_do() -> None:
    # No eligible coins, nothing to deduplicate, item gets considered normally

    sk = AugSchemeMPL.key_gen(b"3" * 32)
    g1 = sk.get_g1()
    sig = AugSchemeMPL.sign(sk, b"foobar", g1)

    conditions = [
        [ConditionOpcode.AGG_SIG_UNSAFE, g1, b"foobar"],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
    ]
    sb = spend_bundle_from_conditions(conditions, TEST_COIN, sig)
    mempool_item = mempool_item_from_spendbundle(sb)
    eligible_coin_spends = EligibleCoinSpends()
    unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
        bundle_coin_spends=mempool_item.bundle_coin_spends, max_cost=mempool_item.conds.cost
    )
    assert unique_coin_spends == sb.coin_spends
    assert cost_saving == 0
    assert unique_additions == [Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, uint64(1))]
    assert eligible_coin_spends == EligibleCoinSpends()


def test_dedup_info_eligible_1st_time() -> None:
    # Eligible coin encountered for the first time
    conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT - 1],
    ]
    sb = spend_bundle_from_conditions(conditions, TEST_COIN)
    mempool_item = mempool_item_from_spendbundle(sb)
    assert mempool_item.conds is not None
    eligible_coin_spends = EligibleCoinSpends()
    solution = SerializedProgram.to(conditions)
    unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
        bundle_coin_spends=mempool_item.bundle_coin_spends, max_cost=mempool_item.conds.cost
    )
    assert unique_coin_spends == sb.coin_spends
    assert cost_saving == 0
    assert set(unique_additions) == {
        Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, uint64(1)),
        Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, uint64(TEST_COIN_AMOUNT - 1)),
    }
    assert eligible_coin_spends == EligibleCoinSpends({TEST_COIN_ID: DedupCoinSpend(solution=solution, cost=None)})


def test_dedup_info_eligible_but_different_solution() -> None:
    # Eligible coin but different solution from the one we encountered
    initial_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT],
    ]
    initial_solution = SerializedProgram.to(initial_conditions)
    eligible_coin_spends = EligibleCoinSpends({TEST_COIN_ID: DedupCoinSpend(solution=initial_solution, cost=None)})
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT]]
    sb = spend_bundle_from_conditions(conditions, TEST_COIN)
    mempool_item = mempool_item_from_spendbundle(sb)
    with pytest.raises(ValueError, match="Solution is different from what we're deduplicating on"):
        eligible_coin_spends.get_deduplication_info(
            bundle_coin_spends=mempool_item.bundle_coin_spends, max_cost=mempool_item.conds.cost
        )


def test_dedup_info_eligible_2nd_time_and_another_1st_time() -> None:
    # Eligible coin encountered a second time, and another for the first time
    initial_conditions = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT - 1],
    ]
    initial_solution = SerializedProgram.to(initial_conditions)
    eligible_coin_spends = EligibleCoinSpends({TEST_COIN_ID: DedupCoinSpend(solution=initial_solution, cost=None)})
    sb1 = spend_bundle_from_conditions(initial_conditions, TEST_COIN)
    second_conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT2]]
    second_solution = SerializedProgram.to(second_conditions)
    sb2 = spend_bundle_from_conditions(second_conditions, TEST_COIN2)
    sb = SpendBundle.aggregate([sb1, sb2])
    mempool_item = mempool_item_from_spendbundle(sb)
    assert mempool_item.conds is not None
    unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
        bundle_coin_spends=mempool_item.bundle_coin_spends, max_cost=mempool_item.conds.cost
    )
    # Only the eligible one that we encountered more than once gets deduplicated
    assert unique_coin_spends == sb2.coin_spends
    saved_cost = uint64(3600044)
    assert cost_saving == saved_cost
    assert unique_additions == [Coin(TEST_COIN_ID2, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT2)]
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
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT - 1],
    ]
    initial_solution = SerializedProgram.to(initial_conditions)
    second_conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT2]]
    second_solution = SerializedProgram.to(second_conditions)
    saved_cost = uint64(3600044)
    eligible_coin_spends = EligibleCoinSpends(
        {
            TEST_COIN_ID: DedupCoinSpend(solution=initial_solution, cost=saved_cost),
            TEST_COIN_ID2: DedupCoinSpend(solution=second_solution, cost=None),
        }
    )
    sb1 = spend_bundle_from_conditions(initial_conditions, TEST_COIN)
    sb2 = spend_bundle_from_conditions(second_conditions, TEST_COIN2)
    sk = AugSchemeMPL.key_gen(b"4" * 32)
    g1 = sk.get_g1()
    sig = AugSchemeMPL.sign(sk, b"foobar", g1)
    sb3_conditions = [
        [ConditionOpcode.AGG_SIG_UNSAFE, g1, b"foobar"],
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT3],
    ]
    sb3 = spend_bundle_from_conditions(sb3_conditions, TEST_COIN3, sig)
    sb = SpendBundle.aggregate([sb1, sb2, sb3])
    mempool_item = mempool_item_from_spendbundle(sb)
    assert mempool_item.conds is not None
    unique_coin_spends, cost_saving, unique_additions = eligible_coin_spends.get_deduplication_info(
        bundle_coin_spends=mempool_item.bundle_coin_spends, max_cost=mempool_item.conds.cost
    )
    assert unique_coin_spends == sb3.coin_spends
    saved_cost2 = uint64(1800044)
    assert cost_saving == saved_cost + saved_cost2
    assert unique_additions == [Coin(TEST_COIN_ID3, IDENTITY_PUZZLE_HASH, TEST_COIN_AMOUNT3)]
    expected_eligible_spends = EligibleCoinSpends(
        {
            TEST_COIN_ID: DedupCoinSpend(initial_solution, saved_cost),
            TEST_COIN_ID2: DedupCoinSpend(second_solution, saved_cost2),
        }
    )
    assert eligible_coin_spends == expected_eligible_spends


@pytest.mark.anyio
@pytest.mark.parametrize("new_height_step", [1, 2, -1])
async def test_coin_spending_different_ways_then_finding_it_spent_in_new_peak(new_height_step: int) -> None:
    """
    This test makes sure all mempool items that spend a coin (in different ways)
    that shows up as spent in a block, get removed properly.
    NOTE: `new_height_step` parameter allows us to cover both the optimized and
    the reorg code paths
    """
    new_height = uint32(TEST_HEIGHT + new_height_step)
    coin = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, uint64(100))
    coin_id = coin.name()
    test_coin_records = {coin_id: CoinRecord(coin, uint32(0), uint32(0), False, uint64(0))}

    async def get_coin_records(coin_ids: Collection[bytes32]) -> list[CoinRecord]:
        ret: list[CoinRecord] = []
        for name in coin_ids:
            r = test_coin_records.get(name)
            if r is not None:
                ret.append(r)
        return ret

    mempool_manager = await instantiate_mempool_manager(get_coin_records)
    # Create a bunch of mempool items that spend the coin in different ways
    for i in range(3):
        _, _, result = await generate_and_add_spendbundle(
            mempool_manager,
            [
                [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, coin.amount],
                [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, uint64(i)],
            ],
            coin,
        )
        assert result[1] == MempoolInclusionStatus.SUCCESS
    assert len(list(mempool_manager.mempool.get_items_by_coin_id(coin_id))) == 3
    assert mempool_manager.mempool.size() == 3
    assert len(list(mempool_manager.mempool.items_by_feerate())) == 3
    # Setup a new peak where the incoming block has spent the coin
    # Mark this coin as spent
    test_coin_records = {coin_id: CoinRecord(coin, uint32(0), TEST_HEIGHT, False, uint64(0))}
    block_record = create_test_block_record(height=new_height)
    await mempool_manager.new_peak(block_record, [coin_id])
    invariant_check_mempool(mempool_manager.mempool)
    # As the coin was a spend in all the mempool items we had, nothing should be left now
    assert len(list(mempool_manager.mempool.get_items_by_coin_id(coin_id))) == 0
    assert mempool_manager.mempool.size() == 0
    assert len(list(mempool_manager.mempool.items_by_feerate())) == 0


@pytest.mark.anyio
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
            eligible_for_fast_forward=False,
            additions=[Coin(coins[i].name(), IDENTITY_PUZZLE_HASH, coins[i].amount)],
        )
    assert mi123e.bundle_coin_spends[coins[3].name()] == BundleCoinSpend(
        coin_spend=eligible_sb.coin_spends[0],
        eligible_for_dedup=True,
        eligible_for_fast_forward=False,
        additions=[Coin(coins[3].name(), IDENTITY_PUZZLE_HASH, coins[3].amount)],
    )


@pytest.mark.anyio
async def test_identical_spend_aggregation_e2e(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str
) -> None:
    def get_sb_names_by_coin_id(
        full_node_api: FullNodeSimulator,
        spent_coin_id: bytes32,
    ) -> set[bytes32]:
        return {
            i.spend_bundle_name
            for i in full_node_api.full_node.mempool_manager.mempool.get_items_by_coin_id(spent_coin_id)
        }

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
    ) -> tuple[Wallet, list[WalletCoinRecord], bytes32]:
        wallet = wallet_node.wallet_state_manager.main_wallet
        ph = await wallet.get_new_puzzlehash()
        phs = [await wallet.get_new_puzzlehash() for _ in range(3)]
        for _ in range(2):
            await farm_a_block(full_node_api, wallet_node, ph)
        async with wallet.wallet_state_manager.new_action_scope(
            DEFAULT_TX_CONFIG, push=False, sign=True
        ) as action_scope:
            await wallet.generate_signed_transaction([uint64(200)] * len(phs), phs, action_scope)
        [tx] = action_scope.side_effects.transactions
        assert tx.spend_bundle is not None
        await send_to_mempool(full_node_api, tx.spend_bundle)
        await farm_a_block(full_node_api, wallet_node, ph)
        coins = list(await wallet_node.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(1))
        # Two blocks farmed plus 3 transactions
        assert len(coins) == 7
        return (wallet, coins, ph)

    [[full_node_api], [[wallet_node, wallet_server]], _] = simulator_and_wallet
    server = full_node_api.full_node.server
    await wallet_server.start_client(PeerInfo(self_hostname, server.get_port()), None)
    wallet, coins, ph = await make_setup_and_coins(full_node_api, wallet_node)

    # Make sure spending AB then BC would generate a conflict for the latter
    async with wallet.wallet_state_manager.new_action_scope(
        DEFAULT_TX_CONFIG, push=False, merge_spends=False, sign=True
    ) as action_scope:
        await wallet.generate_signed_transaction([uint64(30)], [ph], action_scope, coins={coins[0].coin})
        await wallet.generate_signed_transaction([uint64(30)], [ph], action_scope, coins={coins[1].coin})
        await wallet.generate_signed_transaction([uint64(30)], [ph], action_scope, coins={coins[2].coin})
    [tx_a, tx_b, tx_c] = action_scope.side_effects.transactions
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
    async with wallet.wallet_state_manager.new_action_scope(
        DEFAULT_TX_CONFIG, push=False, merge_spends=False, sign=True
    ) as action_scope:
        await wallet.generate_signed_transaction(
            [uint64(200)], [IDENTITY_PUZZLE_HASH], action_scope, coins={coins[3].coin}
        )
    [tx] = action_scope.side_effects.transactions
    assert tx.spend_bundle is not None
    await send_to_mempool(full_node_api, tx.spend_bundle)
    await farm_a_block(full_node_api, wallet_node, ph)
    # Grab the coin we created and make an eligible coin out of it
    coins_with_identity_ph = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(
        False, IDENTITY_PUZZLE_HASH
    )
    coin = coins_with_identity_ph[0].coin
    sb = spend_bundle_from_conditions([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, coin.amount]], coin)
    await send_to_mempool(full_node_api, sb)
    await farm_a_block(full_node_api, wallet_node, ph)
    # Grab the eligible coin to spend as E in DE and EF transactions
    e_coin = (await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(False, IDENTITY_PUZZLE_HASH))[
        0
    ].coin
    e_coin_id = e_coin.name()
    # Restrict spending E with an announcement to consume
    message = b"Identical spend aggregation test"
    e_announcement = AssertCoinAnnouncement(asserted_id=e_coin_id, asserted_msg=message)
    # Create transactions D and F that consume an announcement created by E
    async with wallet.wallet_state_manager.new_action_scope(
        DEFAULT_TX_CONFIG, push=False, merge_spends=False, sign=True
    ) as action_scope:
        await wallet.generate_signed_transaction(
            [uint64(100)],
            [ph],
            action_scope,
            fee=uint64(0),
            coins={coins[4].coin},
            extra_conditions=(e_announcement,),
        )
        await wallet.generate_signed_transaction(
            [uint64(150)],
            [ph],
            action_scope,
            fee=uint64(0),
            coins={coins[5].coin},
            extra_conditions=(e_announcement,),
        )
    [tx_d, tx_f] = action_scope.side_effects.transactions
    assert tx_d.spend_bundle is not None
    assert tx_f.spend_bundle is not None
    # Create transaction E now that spends e_coin to create another eligible
    # coin as well as the announcement consumed by D and F
    conditions: list[list[Any]] = [
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, e_coin.amount],
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
        [ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, e_coin.amount],
        [ConditionOpcode.ASSERT_MY_COIN_ID, e_coin.name()],
        [ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, message],
    ]
    sb_e2 = spend_bundle_from_conditions(conditions, e_coin)
    g_coin = coins[6].coin
    g_coin_id = g_coin.name()
    async with wallet.wallet_state_manager.new_action_scope(
        DEFAULT_TX_CONFIG, push=False, merge_spends=False, sign=True
    ) as action_scope:
        await wallet.generate_signed_transaction(
            [uint64(13)], [ph], action_scope, coins={g_coin}, extra_conditions=(e_announcement,)
        )
    [tx_g] = action_scope.side_effects.transactions
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
    assert eligible_coins[0].coin.amount == e_coin.amount


# we have two coins in this test. They have different birth heights (and
# timestamps)
# coin1: amount=1, confirmed_height=10, timestamp=1000
# coin2: amount=2, confirmed_height=20, timestamp=2000
# the mempool is at height 21 and timestamp 2010
@pytest.mark.anyio
@pytest.mark.parametrize(
    "cond1,cond2,expected",
    [
        # ASSERT HEIGHT ABSOLUTE
        (
            [co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 30],
            [co.ASSERT_HEIGHT_ABSOLUTE, 30],
            Err.IMPOSSIBLE_HEIGHT_ABSOLUTE_CONSTRAINTS,
        ),
        (
            [co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 31],
            [co.ASSERT_HEIGHT_ABSOLUTE, 30],
            None,
        ),
        (
            [co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 21],
            [co.ASSERT_HEIGHT_ABSOLUTE, 20],
            Err.ASSERT_BEFORE_HEIGHT_ABSOLUTE_FAILED,
        ),
        # ASSERT SECONDS ABSOLUTE
        (
            [co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 3000],
            [co.ASSERT_SECONDS_ABSOLUTE, 3000],
            Err.IMPOSSIBLE_SECONDS_ABSOLUTE_CONSTRAINTS,
        ),
        (
            [co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 3001],
            [co.ASSERT_SECONDS_ABSOLUTE, 3000],
            Err.ASSERT_SECONDS_ABSOLUTE_FAILED,
        ),
        (
            [co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 2001],
            [co.ASSERT_SECONDS_ABSOLUTE, 2000],
            Err.ASSERT_BEFORE_SECONDS_ABSOLUTE_FAILED,
        ),
        # ASSERT HEIGHT RELATIVE
        # coin1: height=10
        # coin2: height=20
        (
            [co.ASSERT_BEFORE_HEIGHT_RELATIVE, 15],
            [co.ASSERT_HEIGHT_RELATIVE, 5],
            Err.IMPOSSIBLE_HEIGHT_ABSOLUTE_CONSTRAINTS,
        ),
        (
            [co.ASSERT_BEFORE_HEIGHT_RELATIVE, 26],
            [co.ASSERT_HEIGHT_RELATIVE, 15],
            None,
        ),
        (
            [co.ASSERT_BEFORE_HEIGHT_RELATIVE, 16],
            [co.ASSERT_HEIGHT_RELATIVE, 5],
            None,
        ),
        # ASSERT SECONDS RELATIVE
        # coin1: timestamp=1000
        # coin2: timestamp=2000
        (
            [co.ASSERT_BEFORE_SECONDS_RELATIVE, 1500],
            [co.ASSERT_SECONDS_RELATIVE, 500],
            Err.IMPOSSIBLE_SECONDS_ABSOLUTE_CONSTRAINTS,
        ),
        # we don't have a pending cache for seconds timelocks, so these fail
        # immediately
        (
            [co.ASSERT_BEFORE_SECONDS_RELATIVE, 2501],
            [co.ASSERT_SECONDS_RELATIVE, 1500],
            Err.ASSERT_SECONDS_RELATIVE_FAILED,
        ),
        (
            [co.ASSERT_BEFORE_SECONDS_RELATIVE, 1501],
            [co.ASSERT_SECONDS_RELATIVE, 500],
            Err.ASSERT_SECONDS_RELATIVE_FAILED,
        ),
        # ASSERT HEIGHT RELATIVE and ASSERT HEIGHT ABSOLUTE
        # coin1: height=10
        # coin2: height=20
        (
            [co.ASSERT_BEFORE_HEIGHT_RELATIVE, 20],
            [co.ASSERT_HEIGHT_ABSOLUTE, 30],
            Err.IMPOSSIBLE_HEIGHT_ABSOLUTE_CONSTRAINTS,
        ),
        (
            [co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 30],
            [co.ASSERT_HEIGHT_RELATIVE, 10],
            Err.IMPOSSIBLE_HEIGHT_ABSOLUTE_CONSTRAINTS,
        ),
        (
            [co.ASSERT_BEFORE_HEIGHT_RELATIVE, 21],
            [co.ASSERT_HEIGHT_ABSOLUTE, 30],
            None,
        ),
        (
            [co.ASSERT_BEFORE_HEIGHT_ABSOLUTE, 31],
            [co.ASSERT_HEIGHT_RELATIVE, 10],
            None,
        ),
        # ASSERT SECONDS ABSOLUTE and ASSERT SECONDS RELATIVE
        (
            [co.ASSERT_BEFORE_SECONDS_RELATIVE, 2000],
            [co.ASSERT_SECONDS_ABSOLUTE, 3000],
            Err.IMPOSSIBLE_SECONDS_ABSOLUTE_CONSTRAINTS,
        ),
        (
            [co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 3000],
            [co.ASSERT_SECONDS_RELATIVE, 1000],
            Err.IMPOSSIBLE_SECONDS_ABSOLUTE_CONSTRAINTS,
        ),
        # we don't have a pending cache for seconds timelocks, so these fail
        # immediately
        (
            [co.ASSERT_BEFORE_SECONDS_RELATIVE, 2001],
            [co.ASSERT_SECONDS_ABSOLUTE, 3000],
            Err.ASSERT_SECONDS_ABSOLUTE_FAILED,
        ),
        (
            [co.ASSERT_BEFORE_SECONDS_ABSOLUTE, 3001],
            [co.ASSERT_SECONDS_RELATIVE, 1000],
            Err.ASSERT_SECONDS_RELATIVE_FAILED,
        ),
    ],
)
async def test_mempool_timelocks(cond1: list[object], cond2: list[object], expected: Optional[Err]) -> None:
    coins = []
    test_coin_records = {}

    coin = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, uint64(1))
    coins.append(coin)
    test_coin_records[coin.name()] = CoinRecord(coin, uint32(10), uint32(0), False, uint64(1000))
    coin = Coin(IDENTITY_PUZZLE_HASH, IDENTITY_PUZZLE_HASH, uint64(2))
    coins.append(coin)
    test_coin_records[coin.name()] = CoinRecord(coin, uint32(20), uint32(0), False, uint64(2000))

    async def get_coin_records(coin_ids: Collection[bytes32]) -> list[CoinRecord]:
        ret: list[CoinRecord] = []
        for name in coin_ids:
            r = test_coin_records.get(name)
            if r is not None:
                ret.append(r)
        return ret

    mempool_manager = await instantiate_mempool_manager(
        get_coin_records, block_height=uint32(21), block_timestamp=uint64(2010)
    )

    coin_spends = [
        make_spend(coins[0], IDENTITY_PUZZLE, Program.to([cond1])),
        make_spend(coins[1], IDENTITY_PUZZLE, Program.to([cond2])),
    ]

    bundle = SpendBundle(coin_spends, G2Element())
    bundle_name = bundle.name()
    try:
        result = await add_spendbundle(mempool_manager, bundle, bundle_name)
        print(result)
        if expected is not None:
            assert result == (None, MempoolInclusionStatus.FAILED, expected)
        else:
            assert result[0] is not None
            assert result[1] != MempoolInclusionStatus.FAILED
    except ValidationError as e:
        assert e.code == expected


TEST_FILL_RATE_ITEM_COST = 144_720_020
TEST_COST_PER_BYTE = 12_000
TEST_BLOCK_OVERHEAD = QUOTE_BYTES * TEST_COST_PER_BYTE + QUOTE_EXECUTION_COST


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.parametrize(
    "max_block_clvm_cost, expected_block_items, expected_block_cost",
    [
        # Here we set the block cost limit to twice the test items' cost, so we
        # expect both test items to get included in the block.
        # NOTE: The expected block cost is smaller than the sum of items' costs
        # because of the spend bundle aggregation that creates the block
        # bundle, in addition to a small block compression effect that we
        # can't completely avoid.
        (TEST_FILL_RATE_ITEM_COST * 2, 2, TEST_FILL_RATE_ITEM_COST * 2 - 107_980),
        # Here we set the block cost limit to twice the test items' cost - 1,
        # so we expect only one of the two test items to get included in the block.
        # NOTE: The cost difference here is because get_conditions_from_spendbundle
        # does not include the block overhead.
        (TEST_FILL_RATE_ITEM_COST * 2 - 1, 1, TEST_FILL_RATE_ITEM_COST + TEST_BLOCK_OVERHEAD),
    ],
)
async def test_fill_rate_block_validation(
    blockchain_constants: ConsensusConstants,
    max_block_clvm_cost: uint64,
    expected_block_items: int,
    expected_block_cost: uint64,
) -> None:
    """
    This test covers the case where we set the fill rate to 100% and ensure
        that we wouldn't generate a block that exceed the maximum block cost limit.
    In the first scenario, we set the block cost limit to match the test items'
        costs sum, expecting both test items to get included in the block.
    In the second scenario, we reduce the maximum block cost limit by one,
        expecting only one of the two test items to get included in the block.
    """

    async def send_to_mempool(full_node: FullNodeSimulator, spend_bundle: SpendBundle) -> None:
        res = await full_node.send_transaction(wallet_protocol.SendTransaction(spend_bundle))
        assert res is not None and ProtocolMessageTypes(res.type) == ProtocolMessageTypes.transaction_ack
        res_parsed = wallet_protocol.TransactionAck.from_bytes(res.data)
        assert res_parsed.status == MempoolInclusionStatus.SUCCESS.value

    async def fill_mempool_with_test_sbs(
        full_node_api: FullNodeSimulator,
    ) -> list[tuple[bytes32, SerializedProgram, bytes32]]:
        coins_and_puzzles = []
        # Create different puzzles and use different (parent) coins to reduce
        # the effects of block compression as much as possible.
        for i in (1, 2):
            puzzle = SerializedProgram.to((1, [[ConditionOpcode.REMARK, bytes([i] * 12_000)]]))
            ph = puzzle.get_tree_hash()
            for _ in range(2):
                await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(ph))
            coin_records = await full_node_api.full_node.coin_store.get_coin_records_by_puzzle_hash(False, ph)
            coin = next(cr.coin for cr in coin_records if cr.coin.amount == 250_000_000_000)
            coins_and_puzzles.append((coin, puzzle))
        sbs_info = []
        for coin, puzzle in coins_and_puzzles:
            coin_spend = make_spend(coin, puzzle, SerializedProgram.to([]))
            sb = SpendBundle([coin_spend], G2Element())
            await send_to_mempool(full_node_api, sb)
            sbs_info.append((coin.name(), puzzle, sb.name()))
        return sbs_info

    constants = blockchain_constants.replace(MAX_BLOCK_COST_CLVM=max_block_clvm_cost)
    async with setup_simulators_and_wallets(1, 0, constants) as setup:
        full_node_api = setup.simulators[0].peer_api
        assert full_node_api.full_node._mempool_manager is not None
        # We have to alter the following values here as they're not exposed elsewhere
        # and without them we won't be able to get the test bundle in.
        # This defaults to `MAX_BLOCK_COST_CLVM // 2`
        full_node_api.full_node._mempool_manager.max_tx_clvm_cost = max_block_clvm_cost
        # This defaults to `MAX_BLOCK_COST_CLVM - BLOCK_OVERHEAD`
        full_node_api.full_node._mempool_manager.mempool.mempool_info = dataclasses.replace(
            full_node_api.full_node._mempool_manager.mempool.mempool_info,
            max_block_clvm_cost=CLVMCost(max_block_clvm_cost),
        )
        sbs_info = await fill_mempool_with_test_sbs(full_node_api)
        # This check is here just to make sure our bundles have the expected cost
        for sb_info in sbs_info:
            _, _, sb_name = sb_info
            mi = full_node_api.full_node.mempool_manager.get_mempool_item(sb_name)
            assert mi is not None
            assert mi.cost == TEST_FILL_RATE_ITEM_COST
        # Farm the block to make sure we're passing block validation
        current_peak = full_node_api.full_node.blockchain.get_peak()
        assert current_peak is not None
        await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(IDENTITY_PUZZLE_HASH))
        # Check that our resulting block is what we expect
        peak = full_node_api.full_node.blockchain.get_peak()
        assert peak is not None
        # Check for the peak change after farming the block
        assert peak.prev_hash == current_peak.header_hash
        # Check our coin(s)
        for i in range(expected_block_items):
            coin_name, puzzle, _ = sbs_info[i]
            rps_res = await full_node_api.request_puzzle_solution(
                wallet_protocol.RequestPuzzleSolution(coin_name, peak.height)
            )
            assert rps_res is not None
            rps_res_parsed = wallet_protocol.RespondPuzzleSolution.from_bytes(rps_res.data)
            assert rps_res_parsed.response.puzzle == puzzle
        # Check the block cost
        rb_res = await full_node_api.request_block(RequestBlock(peak.height, True))
        assert rb_res is not None
        rb_res_parsed = RespondBlock.from_bytes(rb_res.data)
        assert rb_res_parsed.block.transactions_info is not None
        assert rb_res_parsed.block.transactions_info.cost == expected_block_cost


@pytest.mark.parametrize("optimized_path", [True, False])
@pytest.mark.anyio
async def test_height_added_to_mempool(optimized_path: bool) -> None:
    """
    This test covers scenarios when the mempool is updated or rebuilt, to make
    sure that mempool items maintain correct height added to mempool values.
    We control whether we're updating the mempool or rebuilding it, through the
    `optimized_path` param.
    """
    mempool_manager = await instantiate_mempool_manager(get_coin_records_for_test_coins)
    assert mempool_manager.peak is not None
    assert mempool_manager.peak.height == TEST_HEIGHT
    assert mempool_manager.peak.header_hash == height_hash(TEST_HEIGHT)
    # Create a mempool item and keep track of its height added to mempool
    _, sb_name, _ = await generate_and_add_spendbundle(
        mempool_manager, [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    )
    mi = mempool_manager.get_mempool_item(sb_name)
    assert mi is not None
    original_height = mi.height_added_to_mempool
    # Let's get a new peak that doesn't include our item, and make sure the
    # height added to mempool remains correct.
    test_new_peak = TestBlockRecord(
        header_hash=height_hash(TEST_HEIGHT + 1),
        height=uint32(TEST_HEIGHT + 1),
        timestamp=uint64(TEST_TIMESTAMP + 42),
        prev_transaction_block_height=TEST_HEIGHT,
        prev_transaction_block_hash=height_hash(TEST_HEIGHT),
    )
    if optimized_path:
        # Spend an unrelated coin to get the mempool updated
        spent_coins = [TEST_COIN_ID2]
    else:
        # Trigger the slow path to get the mempool rebuilt
        spent_coins = None
    await mempool_manager.new_peak(test_new_peak, spent_coins)
    assert mempool_manager.peak.height == TEST_HEIGHT + 1
    assert mempool_manager.peak.header_hash == height_hash(TEST_HEIGHT + 1)
    # Make sure our item is still in the mempool, and that its height added to
    # mempool value is still correct.
    mempool_item = mempool_manager.get_mempool_item(sb_name)
    assert mempool_item is not None
    assert mempool_item.height_added_to_mempool == original_height


# This is a test utility to provide a simple view of the coin table for the
# mempool manager.
class TestCoins:
    coin_records: dict[bytes32, CoinRecord]
    lineage_info: dict[bytes32, UnspentLineageInfo]

    def __init__(self, coins: list[Coin], lineage: dict[bytes32, Coin]) -> None:
        self.coin_records = {}
        for c in coins:
            self.coin_records[c.name()] = CoinRecord(c, uint32(0), uint32(0), False, TEST_TIMESTAMP)
        self.lineage_info = {}
        for ph, c in lineage.items():
            self.lineage_info[ph] = UnspentLineageInfo(
                c.name(), c.amount, c.parent_coin_info, uint64(1337), bytes32([42] * 32)
            )

    def spend_coin(self, coin_id: bytes32, height: uint32 = uint32(10)) -> None:
        self.coin_records[coin_id] = dataclasses.replace(self.coin_records[coin_id], spent_block_index=height)

    def update_lineage(self, puzzle_hash: bytes32, coin: Optional[Coin]) -> None:
        if coin is None:
            self.lineage_info.pop(puzzle_hash)
        else:
            assert coin.puzzle_hash == puzzle_hash
            prev = self.lineage_info[puzzle_hash]
            self.lineage_info[puzzle_hash] = UnspentLineageInfo(
                coin.name(), coin.amount, coin.parent_coin_info, prev.coin_amount, prev.coin_id
            )

    async def get_coin_records(self, coin_ids: Collection[bytes32]) -> list[CoinRecord]:
        ret = []
        for coin_id in coin_ids:
            rec = self.coin_records.get(coin_id)
            if rec is not None:
                ret.append(rec)

        return ret

    async def get_unspent_lineage_info(self, ph: bytes32) -> Optional[UnspentLineageInfo]:
        return self.lineage_info.get(ph)


# creates a CoinSpend of a made up
def make_singleton_spend(launcher_id: bytes32, parent_parent_id: bytes32 = bytes32([3] * 32)) -> CoinSpend:
    from chia_rs import supports_fast_forward

    from chia.wallet.lineage_proof import LineageProof
    from chia.wallet.puzzles.singleton_top_layer_v1_1 import (
        puzzle_for_singleton,
        solution_for_singleton,
    )

    singleton_puzzle = SerializedProgram.from_program(puzzle_for_singleton(launcher_id, Program.to(1)))

    PARENT_COIN = Coin(parent_parent_id, singleton_puzzle.get_tree_hash(), uint64(1))
    COIN = Coin(PARENT_COIN.name(), singleton_puzzle.get_tree_hash(), uint64(1))

    lineage_proof = LineageProof(parent_parent_id, IDENTITY_PUZZLE_HASH, uint64(1))

    inner_solution = Program.to([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, uint64(1)]])
    singleton_solution = SerializedProgram.from_program(
        solution_for_singleton(lineage_proof, uint64(1), inner_solution)
    )

    ret = CoinSpend(COIN, singleton_puzzle, singleton_solution)

    # we make sure the spend actually supports fast forward
    assert supports_fast_forward(ret)
    assert ret.coin.puzzle_hash == ret.puzzle_reveal.get_tree_hash()
    return ret


async def setup_mempool(coins: TestCoins) -> MempoolManager:
    mempool_manager = MempoolManager(
        coins.get_coin_records,
        coins.get_unspent_lineage_info,
        DEFAULT_CONSTANTS,
    )
    test_block_record = create_test_block_record(height=uint32(10), timestamp=uint64(12345678))
    await mempool_manager.new_peak(test_block_record, None)
    return mempool_manager


# adds a new peak to the memepool manager with the specified coin IDs spent
async def advance_mempool(
    mempool: MempoolManager, spent_coins: list[bytes32], *, use_optimization: bool = True
) -> None:
    br = mempool.peak
    assert br is not None

    if use_optimization:
        next_height = uint32(br.height + 1)
    else:
        next_height = uint32(br.height + 2)

    assert br.timestamp is not None
    prev_block_hash = br.header_hash
    br = create_test_block_record(height=next_height, timestamp=uint64(br.timestamp + 10))

    if use_optimization:
        assert prev_block_hash == br.prev_transaction_block_hash
    else:
        assert prev_block_hash != br.prev_transaction_block_hash

    await mempool.new_peak(br, spent_coins)
    invariant_check_mempool(mempool.mempool)


@pytest.mark.anyio
@pytest.mark.parametrize("spend_singleton", [True, False])
@pytest.mark.parametrize("spend_plain", [True, False])
@pytest.mark.parametrize("use_optimization", [True, False])
@pytest.mark.parametrize("reverse_spend_order", [True, False])
async def test_new_peak_ff_eviction(
    spend_singleton: bool, spend_plain: bool, use_optimization: bool, reverse_spend_order: bool
) -> None:
    LAUNCHER_ID = bytes32([1] * 32)
    singleton_spend = make_singleton_spend(LAUNCHER_ID)

    coin_spend = make_spend(
        TEST_COIN,
        IDENTITY_PUZZLE,
        Program.to([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1336]]),
    )
    bundle = SpendBundle([singleton_spend, coin_spend], G2Element())

    coins = TestCoins([singleton_spend.coin, TEST_COIN], {singleton_spend.coin.puzzle_hash: singleton_spend.coin})

    mempool_manager = await setup_mempool(coins)

    bundle_add_info = await mempool_manager.add_spend_bundle(
        bundle,
        make_test_conds(spend_ids=[(singleton_spend.coin, ELIGIBLE_FOR_FF), (TEST_COIN, 0)], cost=1000000),
        bundle.name(),
        first_added_height=uint32(1),
    )

    assert bundle_add_info.status == MempoolInclusionStatus.SUCCESS
    item = mempool_manager.get_mempool_item(bundle.name())
    assert item is not None
    assert item.bundle_coin_spends[singleton_spend.coin.name()].eligible_for_fast_forward
    assert item.bundle_coin_spends[singleton_spend.coin.name()].latest_singleton_coin == singleton_spend.coin.name()

    spent_coins: list[bytes32] = []

    if spend_singleton:
        # pretend that we melted the singleton, the FF spend
        coins.update_lineage(singleton_spend.coin.puzzle_hash, None)
        coins.spend_coin(singleton_spend.coin.name(), uint32(11))
        spent_coins.append(singleton_spend.coin.name())

    if spend_plain:
        # pretend that we spend singleton, the FF spend
        coins.spend_coin(coin_spend.coin.name(), uint32(11))
        spent_coins.append(coin_spend.coin.name())

    assert bundle_add_info.status == MempoolInclusionStatus.SUCCESS
    invariant_check_mempool(mempool_manager.mempool)

    if reverse_spend_order:
        spent_coins.reverse()

    await advance_mempool(mempool_manager, spent_coins, use_optimization=use_optimization)

    # make sure the mempool item is evicted
    if spend_singleton or spend_plain:
        assert mempool_manager.get_mempool_item(bundle.name()) is None
    else:
        item = mempool_manager.get_mempool_item(bundle.name())
        assert item is not None
        assert item.bundle_coin_spends[singleton_spend.coin.name()].eligible_for_fast_forward
        assert item.bundle_coin_spends[singleton_spend.coin.name()].latest_singleton_coin == singleton_spend.coin.name()


@pytest.mark.anyio
@pytest.mark.parametrize("use_optimization", [True, False])
async def test_multiple_ff(use_optimization: bool) -> None:
    # create two different singleton spends of the same singleton, that support
    # fast forward. Then update the latest singleton coin and ensure both
    # entries in the mempool are updated accordingly

    PARENT_PARENT1 = bytes32([4] * 32)
    PARENT_PARENT2 = bytes32([5] * 32)
    PARENT_PARENT3 = bytes32([6] * 32)

    # two different spends of the same singleton. both can be fast-forwarded
    LAUNCHER_ID = bytes32([1] * 32)
    singleton_spend1 = make_singleton_spend(LAUNCHER_ID, PARENT_PARENT1)
    singleton_spend2 = make_singleton_spend(LAUNCHER_ID, PARENT_PARENT2)

    # in the next block, this will be the latest singleton coin
    singleton_spend3 = make_singleton_spend(LAUNCHER_ID, PARENT_PARENT3)

    coin_spend = make_spend(
        TEST_COIN,
        IDENTITY_PUZZLE,
        Program.to([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1336]]),
    )
    bundle = SpendBundle([singleton_spend1, singleton_spend2, coin_spend], G2Element())

    # the singleton puzzle hash resulves to the most recent singleton coin, number 2
    # pretend that coin1 is spent
    singleton_ph = singleton_spend2.coin.puzzle_hash
    coins = TestCoins([singleton_spend1.coin, singleton_spend2.coin, TEST_COIN], {singleton_ph: singleton_spend2.coin})

    mempool_manager = await setup_mempool(coins)

    bundle_add_info = await mempool_manager.add_spend_bundle(
        bundle,
        make_test_conds(
            spend_ids=[
                (singleton_spend1.coin, ELIGIBLE_FOR_FF),
                (singleton_spend2.coin, ELIGIBLE_FOR_FF),
                (TEST_COIN, 0),
            ],
            cost=1000000,
        ),
        bundle.name(),
        first_added_height=uint32(1),
    )
    assert bundle_add_info.status == MempoolInclusionStatus.SUCCESS
    invariant_check_mempool(mempool_manager.mempool)

    item = mempool_manager.get_mempool_item(bundle.name())
    assert item is not None
    assert item.bundle_coin_spends[singleton_spend1.coin.name()].eligible_for_fast_forward
    assert item.bundle_coin_spends[singleton_spend2.coin.name()].eligible_for_fast_forward
    assert not item.bundle_coin_spends[coin_spend.coin.name()].eligible_for_fast_forward

    # spend the singleton coin2 and make coin3 the latest version
    coins.update_lineage(singleton_ph, singleton_spend3.coin)
    coins.spend_coin(singleton_spend2.coin.name(), uint32(11))

    await advance_mempool(mempool_manager, [singleton_spend2.coin.name()], use_optimization=use_optimization)

    # we can still fast-forward the singleton spends, the bundle should still be valid
    item = mempool_manager.get_mempool_item(bundle.name())
    assert item is not None
    spend = item.bundle_coin_spends[singleton_spend1.coin.name()]
    assert spend.latest_singleton_coin == singleton_spend3.coin.name()
    spend = item.bundle_coin_spends[singleton_spend2.coin.name()]
    assert spend.latest_singleton_coin == singleton_spend3.coin.name()


@pytest.mark.anyio
@pytest.mark.parametrize("use_optimization", [True, False])
async def test_advancing_ff(use_optimization: bool) -> None:
    # add a FF spend under coin1, advance it twice
    # the second time we have to search for it with a linear search, because
    # it's filed under the original coin

    PARENT_PARENT1 = bytes32([4] * 32)
    PARENT_PARENT2 = bytes32([5] * 32)
    PARENT_PARENT3 = bytes32([6] * 32)

    # two different spends of the same singleton. both can be fast-forwarded
    LAUNCHER_ID = bytes32([1] * 32)
    spend_a = make_singleton_spend(LAUNCHER_ID, PARENT_PARENT1)
    spend_b = make_singleton_spend(LAUNCHER_ID, PARENT_PARENT2)
    spend_c = make_singleton_spend(LAUNCHER_ID, PARENT_PARENT3)

    coin_spend = make_spend(
        TEST_COIN,
        IDENTITY_PUZZLE,
        Program.to([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1336]]),
    )
    bundle = SpendBundle([spend_a, coin_spend], G2Element())

    # the singleton puzzle hash resulves to the most recent singleton coin, number 2
    # pretend that coin1 is spent
    singleton_ph = spend_a.coin.puzzle_hash
    coins = TestCoins([spend_a.coin, spend_b.coin, spend_c.coin, TEST_COIN], {singleton_ph: spend_a.coin})

    mempool_manager = await setup_mempool(coins)

    bundle_add_info = await mempool_manager.add_spend_bundle(
        bundle,
        make_test_conds(spend_ids=[(spend_a.coin, ELIGIBLE_FOR_FF), (TEST_COIN, 0)], cost=1000000),
        bundle.name(),
        first_added_height=uint32(1),
    )
    assert bundle_add_info.status == MempoolInclusionStatus.SUCCESS
    invariant_check_mempool(mempool_manager.mempool)

    item = mempool_manager.get_mempool_item(bundle.name())
    assert item is not None
    spend = item.bundle_coin_spends[spend_a.coin.name()]
    assert spend.eligible_for_fast_forward
    assert spend.latest_singleton_coin == spend_a.coin.name()

    coins.update_lineage(singleton_ph, spend_b.coin)
    coins.spend_coin(spend_a.coin.name(), uint32(11))

    await advance_mempool(mempool_manager, [spend_a.coin.name()])

    item = mempool_manager.get_mempool_item(bundle.name())
    assert item is not None
    spend = item.bundle_coin_spends[spend_a.coin.name()]
    assert spend.eligible_for_fast_forward
    assert spend.latest_singleton_coin == spend_b.coin.name()

    coins.update_lineage(singleton_ph, spend_c.coin)
    coins.spend_coin(spend_b.coin.name(), uint32(12))

    await advance_mempool(mempool_manager, [spend_b.coin.name()], use_optimization=use_optimization)

    item = mempool_manager.get_mempool_item(bundle.name())
    assert item is not None
    spend = item.bundle_coin_spends[spend_a.coin.name()]
    assert spend.eligible_for_fast_forward
    assert spend.latest_singleton_coin == spend_c.coin.name()
