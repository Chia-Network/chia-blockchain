from __future__ import annotations

import copy
import dataclasses
from typing import Any, Optional

import pytest
from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64
from chiabip158 import PyBIP158

from chia._tests.clvm.test_puzzles import public_key_for_index, secret_exponent_for_index
from chia._tests.core.mempool.test_mempool_manager import (
    IDENTITY_PUZZLE,
    IDENTITY_PUZZLE_HASH,
    TEST_COIN,
    TEST_COIN2,
    TEST_COIN3,
    TEST_COIN_ID,
    TEST_COIN_ID2,
    TEST_COIN_ID3,
    TEST_FF_SINGLETON_AMOUNT,
    TEST_FF_SINGLETON_NAME,
    TEST_FF_SINGLETON_PH,
    TEST_FF_SINGLETON_SPEND,
    TEST_HEIGHT,
    TestBlockRecord,
    height_hash,
    make_test_conds,
    mempool_item_from_spendbundle,
    mk_item,
    spend_bundle_from_conditions,
)
from chia._tests.util.key_tool import KeyTool
from chia._tests.util.spend_sim import SimClient, SpendSim, sim_and_client
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.eligible_coin_spends import (
    EligibleCoinSpends,
    UnspentLineageInfo,
    perform_the_fast_forward,
    update_item_on_spent_singleton,
)
from chia.types.internal_mempool_item import InternalMempoolItem
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.mempool_item import BundleCoinSpend, MempoolItem
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.wallet.puzzles import p2_conditions, p2_delegated_puzzle_or_hidden_puzzle
from chia.wallet.puzzles import singleton_top_layer_v1_1 as singleton_top_layer


@pytest.mark.anyio
async def test_process_fast_forward_spends_nothing_to_do() -> None:
    """
    This tests the case when we don't have an eligible coin, so there is
    nothing to fast forward and the item remains unchanged
    """

    async def get_unspent_lineage_info_for_puzzle_hash(_: bytes32) -> Optional[UnspentLineageInfo]:
        assert False  # pragma: no cover

    sk = AugSchemeMPL.key_gen(b"b" * 32)
    g1 = sk.get_g1()
    sig = AugSchemeMPL.sign(sk, b"foobar", g1)
    conditions = [[ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), b"foobar"]]
    sb = spend_bundle_from_conditions(conditions, TEST_COIN, sig)
    item = mempool_item_from_spendbundle(sb)
    # This coin is not eligible for fast forward
    assert item.bundle_coin_spends[TEST_COIN_ID].ff_latest_version is None
    internal_mempool_item = InternalMempoolItem(sb, item.conds, item.height_added_to_mempool, item.bundle_coin_spends)
    original_version = dataclasses.replace(internal_mempool_item)
    eligible_coin_spends = EligibleCoinSpends()
    bundle_coin_spends = await eligible_coin_spends.process_fast_forward_spends(
        mempool_item=internal_mempool_item,
        get_unspent_lineage_info_for_puzzle_hash=get_unspent_lineage_info_for_puzzle_hash,
        height=TEST_HEIGHT,
        constants=DEFAULT_CONSTANTS,
    )
    assert eligible_coin_spends == EligibleCoinSpends()
    assert bundle_coin_spends == original_version.bundle_coin_spends


@pytest.mark.anyio
async def test_process_fast_forward_spends_unknown_ff() -> None:
    """
    This tests the case when we process for the first time but we are unable
    to lookup the latest version from the DB
    """

    async def get_unspent_lineage_info_for_puzzle_hash(puzzle_hash: bytes32) -> Optional[UnspentLineageInfo]:
        if puzzle_hash == IDENTITY_PUZZLE_HASH:
            return None
        assert False  # pragma: no cover

    test_coin = Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, uint64(1))
    test_coin_name = test_coin.name()
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, 1]]
    sb = spend_bundle_from_conditions(conditions, test_coin)
    item = mempool_item_from_spendbundle(sb)
    # The coin is eligible for fast forward
    assert item.bundle_coin_spends[test_coin_name].ff_latest_version == test_coin_name
    internal_mempool_item = InternalMempoolItem(sb, item.conds, item.height_added_to_mempool, item.bundle_coin_spends)
    eligible_coin_spends = EligibleCoinSpends()
    # We have no fast forward records yet, so we'll process this coin for the
    # first time here, but the DB lookup will return None
    with pytest.raises(ValueError, match="Cannot proceed with singleton spend fast forward."):
        await eligible_coin_spends.process_fast_forward_spends(
            mempool_item=internal_mempool_item,
            get_unspent_lineage_info_for_puzzle_hash=get_unspent_lineage_info_for_puzzle_hash,
            height=TEST_HEIGHT,
            constants=DEFAULT_CONSTANTS,
        )


@pytest.mark.anyio
async def test_process_fast_forward_spends_latest_unspent() -> None:
    """
    This tests the case when we are the latest singleton version already, so
    we don't need to fast forward, we just need to set the next version from
    our additions to chain ff spends.
    """
    test_amount = uint64(3)
    test_coin = Coin(TEST_COIN_ID, IDENTITY_PUZZLE_HASH, test_amount)
    test_coin_name = test_coin.name()
    test_unspent_lineage_info = UnspentLineageInfo(
        coin_id=test_coin_name,
        coin_amount=test_coin.amount,
        parent_id=test_coin.parent_coin_info,
        parent_amount=test_coin.amount,
        parent_parent_id=TEST_COIN_ID,
    )

    async def get_unspent_lineage_info_for_puzzle_hash(puzzle_hash: bytes32) -> Optional[UnspentLineageInfo]:
        if puzzle_hash == IDENTITY_PUZZLE_HASH:
            return test_unspent_lineage_info
        assert False  # pragma: no cover

    # At this point, spends are considered *potentially* eligible for singleton
    # fast forward mainly when their amount is odd and they don't have conditions
    # that disqualify them
    conditions = [[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, test_amount]]
    sb = spend_bundle_from_conditions(conditions, test_coin)
    item = mempool_item_from_spendbundle(sb)
    assert item.bundle_coin_spends[test_coin_name].ff_latest_version == test_coin_name
    internal_mempool_item = InternalMempoolItem(sb, item.conds, item.height_added_to_mempool, item.bundle_coin_spends)
    original_version = dataclasses.replace(internal_mempool_item)
    eligible_coin_spends = EligibleCoinSpends()
    bundle_coin_spends = await eligible_coin_spends.process_fast_forward_spends(
        mempool_item=internal_mempool_item,
        get_unspent_lineage_info_for_puzzle_hash=get_unspent_lineage_info_for_puzzle_hash,
        height=TEST_HEIGHT,
        constants=DEFAULT_CONSTANTS,
    )
    child_coin = item.bundle_coin_spends[test_coin_name].additions[0]
    expected_fast_forward_spends = {
        IDENTITY_PUZZLE_HASH: UnspentLineageInfo(
            coin_id=child_coin.name(),
            coin_amount=child_coin.amount,
            parent_id=test_coin_name,
            parent_amount=test_coin.amount,
            parent_parent_id=test_coin.parent_coin_info,
        )
    }
    # We have set the next version from our additions to chain ff spends
    assert eligible_coin_spends.fast_forward_spends == expected_fast_forward_spends
    # We didn't need to fast forward the item so it stays as is
    assert bundle_coin_spends == original_version.bundle_coin_spends


def test_perform_the_fast_forward() -> None:
    """
    This test attempts to spend a coin that is already spent and the current
    unspent version is its grandchild. We fast forward the test coin spend into
    a spend of that latest unspent
    """
    test_child_coin = Coin(TEST_FF_SINGLETON_NAME, TEST_FF_SINGLETON_PH, TEST_FF_SINGLETON_AMOUNT)
    latest_unspent_coin = Coin(test_child_coin.name(), TEST_FF_SINGLETON_PH, TEST_FF_SINGLETON_AMOUNT)
    test_coin_spend = TEST_FF_SINGLETON_SPEND
    test_spend_data = BundleCoinSpend(test_coin_spend, False, TEST_FF_SINGLETON_NAME, [test_child_coin])
    test_unspent_lineage_info = UnspentLineageInfo(
        coin_id=latest_unspent_coin.name(),
        coin_amount=TEST_FF_SINGLETON_AMOUNT,
        parent_id=latest_unspent_coin.parent_coin_info,
        parent_amount=TEST_FF_SINGLETON_AMOUNT,
        parent_parent_id=test_child_coin.parent_coin_info,
    )
    # Start from a fresh state of fast forward spends
    fast_forward_spends: dict[bytes32, UnspentLineageInfo] = {}
    # Perform the fast forward on the test coin (the grandparent)
    new_coin_spend, patched_additions = perform_the_fast_forward(
        test_unspent_lineage_info, test_spend_data, fast_forward_spends
    )
    # Make sure the new coin we got is the grandchild (latest unspent version)
    assert new_coin_spend.coin == latest_unspent_coin
    # Make sure the puzzle reveal is intact
    assert new_coin_spend.puzzle_reveal == test_coin_spend.puzzle_reveal
    # Make sure the solution got patched
    assert new_coin_spend.solution != test_coin_spend.solution
    # Make sure the additions got patched
    expected_child_coin = Coin(latest_unspent_coin.name(), TEST_FF_SINGLETON_PH, TEST_FF_SINGLETON_AMOUNT)
    assert patched_additions == [expected_child_coin]
    # Make sure the new fast forward state got updated with the latest unspent
    # becoming the new child, with its parent being the version we just spent
    # (previously latest unspent)
    expected_unspent_lineage_info = UnspentLineageInfo(
        coin_id=expected_child_coin.name(),
        coin_amount=TEST_FF_SINGLETON_AMOUNT,
        parent_id=latest_unspent_coin.name(),
        parent_amount=TEST_FF_SINGLETON_AMOUNT,
        parent_parent_id=latest_unspent_coin.parent_coin_info,
    )
    assert fast_forward_spends == {TEST_FF_SINGLETON_PH: expected_unspent_lineage_info}


def sign_delegated_puz(del_puz: Program, coin: Coin) -> G2Element:
    synthetic_secret_key: PrivateKey = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_secret_key(
        PrivateKey.from_bytes(secret_exponent_for_index(1).to_bytes(32, "big")),
        p2_delegated_puzzle_or_hidden_puzzle.DEFAULT_HIDDEN_PUZZLE_HASH,
    )
    return AugSchemeMPL.sign(
        synthetic_secret_key, (del_puz.get_tree_hash() + coin.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA)
    )


async def make_and_send_spend_bundle(
    sim: SpendSim,
    sim_client: SimClient,
    coin_spends: list[CoinSpend],
    is_eligible_for_ff: bool = True,
    *,
    is_launcher_coin: bool = False,
    signing_puzzle: Optional[Program] = None,
    signing_coin: Optional[Coin] = None,
    aggsig: G2Element = G2Element(),
) -> tuple[MempoolInclusionStatus, Optional[Err]]:
    if is_launcher_coin or not is_eligible_for_ff:
        assert signing_puzzle is not None
        assert signing_coin is not None
        signature = sign_delegated_puz(signing_puzzle, signing_coin)
        signature += aggsig
    else:
        signature = aggsig
    spend_bundle = SpendBundle(coin_spends, signature)
    status, error = await sim_client.push_tx(spend_bundle)
    if error is None:
        await sim.farm_block()
    return status, error


async def get_singleton_and_remaining_coins(sim: SpendSim) -> tuple[Coin, list[Coin]]:
    coins = await sim.all_non_reward_coins()
    singletons = [coin for coin in coins if coin.amount & 1]
    assert len(singletons) == 1
    singleton = singletons[0]
    coins.remove(singleton)
    return singleton, coins


def make_singleton_coin_spend(
    parent_coin_spend: CoinSpend,
    coin_to_spend: Coin,
    inner_puzzle: Program,
    inner_conditions: list[list[Any]],
    is_eve_spend: bool = False,
) -> tuple[CoinSpend, Program]:
    lineage_proof = singleton_top_layer.lineage_proof_for_coinsol(parent_coin_spend)
    delegated_puzzle = Program.to((1, inner_conditions))
    inner_solution = Program.to([[], delegated_puzzle, []])
    solution = singleton_top_layer.solution_for_singleton(lineage_proof, uint64(coin_to_spend.amount), inner_solution)
    if is_eve_spend:
        # Parent here is the launcher coin
        puzzle_reveal = SerializedProgram.from_program(
            singleton_top_layer.puzzle_for_singleton(parent_coin_spend.coin.name(), inner_puzzle)
        )
    else:
        puzzle_reveal = parent_coin_spend.puzzle_reveal
    return make_spend(coin_to_spend, puzzle_reveal, solution), delegated_puzzle


async def prepare_singleton_eve(
    sim: SpendSim, sim_client: SimClient, is_eligible_for_ff: bool, start_amount: uint64, singleton_amount: uint64
) -> tuple[Program, CoinSpend, Program]:
    # Generate starting info
    key_lookup = KeyTool()
    pk = G1Element.from_bytes(public_key_for_index(1, key_lookup))
    starting_puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_pk(pk)
    if is_eligible_for_ff:
        # This program allows us to control conditions through solutions
        inner_puzzle = Program.to(13)
    else:
        inner_puzzle = starting_puzzle
    inner_puzzle_hash = inner_puzzle.get_tree_hash()
    # Get our starting standard coin created
    await sim.farm_block(starting_puzzle.get_tree_hash())
    records = await sim_client.get_coin_records_by_puzzle_hash(starting_puzzle.get_tree_hash())
    starting_coin = records[0].coin
    # Launching
    conditions, launcher_coin_spend = singleton_top_layer.launch_conditions_and_coinsol(
        coin=starting_coin, inner_puzzle=inner_puzzle, comment=[], amount=start_amount
    )
    # Keep a remaining coin with an even amount
    conditions.append(
        Program.to([ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, starting_coin.amount - start_amount - 1])
    )
    # Create a solution for standard transaction
    delegated_puzzle = p2_conditions.puzzle_for_conditions(conditions)
    full_solution = p2_delegated_puzzle_or_hidden_puzzle.solution_for_conditions(conditions)
    starting_coin_spend = make_spend(starting_coin, starting_puzzle, full_solution)
    await make_and_send_spend_bundle(
        sim,
        sim_client,
        [starting_coin_spend, launcher_coin_spend],
        is_eligible_for_ff,
        is_launcher_coin=True,
        signing_puzzle=delegated_puzzle,
        signing_coin=starting_coin,
    )
    eve_coin, _ = await get_singleton_and_remaining_coins(sim)
    inner_conditions = [[ConditionOpcode.CREATE_COIN, inner_puzzle_hash, singleton_amount]]
    eve_coin_spend, eve_signing_puzzle = make_singleton_coin_spend(
        parent_coin_spend=launcher_coin_spend,
        coin_to_spend=eve_coin,
        inner_puzzle=inner_puzzle,
        inner_conditions=inner_conditions,
        is_eve_spend=True,
    )
    return inner_puzzle, eve_coin_spend, eve_signing_puzzle


async def prepare_and_test_singleton(
    sim: SpendSim, sim_client: SimClient, is_eligible_for_ff: bool, start_amount: uint64, singleton_amount: uint64
) -> tuple[Coin, CoinSpend, Program, Coin]:
    inner_puzzle, eve_coin_spend, eve_signing_puzzle = await prepare_singleton_eve(
        sim, sim_client, is_eligible_for_ff, start_amount, singleton_amount
    )
    # At this point we don't have any unspent singleton
    singleton_puzzle_hash = eve_coin_spend.coin.puzzle_hash
    unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
        singleton_puzzle_hash
    )
    assert unspent_lineage_info is None
    eve_coin = eve_coin_spend.coin
    await make_and_send_spend_bundle(
        sim, sim_client, [eve_coin_spend], is_eligible_for_ff, signing_puzzle=eve_signing_puzzle, signing_coin=eve_coin
    )
    # Now we spent eve and we have an unspent singleton that we can test with
    singleton, [remaining_coin] = await get_singleton_and_remaining_coins(sim)
    assert singleton.amount == singleton_amount
    singleton_puzzle_hash = eve_coin.puzzle_hash
    unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
        singleton_puzzle_hash
    )
    assert unspent_lineage_info == UnspentLineageInfo(
        coin_id=singleton.name(),
        coin_amount=singleton.amount,
        parent_id=eve_coin.name(),
        parent_amount=eve_coin.amount,
        parent_parent_id=eve_coin.parent_coin_info,
    )
    return singleton, eve_coin_spend, inner_puzzle, remaining_coin


@pytest.mark.anyio
async def test_singleton_fast_forward_solo() -> None:
    """
    We don't allow a spend bundle with *only* fast forward spends, since those
    are difficult to evict from the mempool. They would always be valid as long as
    the singleton exists.
    """
    SINGLETON_AMOUNT = uint64(1337)
    async with sim_and_client() as (sim, sim_client):
        singleton, eve_coin_spend, inner_puzzle, _ = await prepare_and_test_singleton(
            sim, sim_client, True, SINGLETON_AMOUNT, SINGLETON_AMOUNT
        )
        singleton_puzzle_hash = eve_coin_spend.coin.puzzle_hash
        inner_puzzle_hash = inner_puzzle.get_tree_hash()
        inner_conditions: list[list[Any]] = [
            [ConditionOpcode.CREATE_COIN, inner_puzzle_hash, SINGLETON_AMOUNT],
        ]
        singleton_coin_spend, _ = make_singleton_coin_spend(eve_coin_spend, singleton, inner_puzzle, inner_conditions)
        # spending the eve coin is not eligible for fast forward, so we need to make this spend first, to test FF
        await make_and_send_spend_bundle(sim, sim_client, [singleton_coin_spend], aggsig=G2Element())
        unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
            singleton_puzzle_hash
        )
        singleton_child, _ = await get_singleton_and_remaining_coins(sim)
        assert singleton_child.amount == SINGLETON_AMOUNT
        assert unspent_lineage_info == UnspentLineageInfo(
            coin_id=singleton_child.name(),
            coin_amount=singleton_child.amount,
            parent_id=eve_coin_spend.coin.name(),
            parent_amount=singleton.amount,
            parent_parent_id=eve_coin_spend.coin.parent_coin_info,
        )

        inner_conditions = [[ConditionOpcode.CREATE_COIN, inner_puzzle_hash, SINGLETON_AMOUNT]]
        # this is a FF spend that isn't combined with any other spend. It's not allowed
        singleton_coin_spend, _ = make_singleton_coin_spend(eve_coin_spend, singleton, inner_puzzle, inner_conditions)
        status, error = await sim_client.push_tx(SpendBundle([singleton_coin_spend], G2Element()))
        assert error is Err.INVALID_SPEND_BUNDLE
        assert status == MempoolInclusionStatus.FAILED


@pytest.mark.anyio
@pytest.mark.parametrize("is_eligible_for_ff", [True, False])
async def test_singleton_fast_forward_different_block(is_eligible_for_ff: bool) -> None:
    """
    This tests uses the `is_eligible_for_ff` parameter to cover both when a
    singleton is eligible for fast forward and when it's not, as we attempt to
    spend an earlier version of it, in a different block, and watch it either
    get properly fast forwarded to the latest unspent (when it's eligible) or
    get correctly rejected as a double spend (when it's not eligible)
    """
    START_AMOUNT = uint64(1337)
    # We're decrementing the next iteration's amount for testing purposes
    SINGLETON_AMOUNT = uint64(1335)
    async with sim_and_client() as (sim, sim_client):
        singleton, eve_coin_spend, inner_puzzle, remaining_coin = await prepare_and_test_singleton(
            sim, sim_client, is_eligible_for_ff, START_AMOUNT, SINGLETON_AMOUNT
        )
        # Let's spend this first version, to create a bigger singleton child
        singleton_puzzle_hash = eve_coin_spend.coin.puzzle_hash
        inner_puzzle_hash = inner_puzzle.get_tree_hash()

        sk = AugSchemeMPL.key_gen(b"1" * 32)
        g1 = sk.get_g1()
        sig = AugSchemeMPL.sign(sk, b"foobar", g1)
        inner_conditions: list[list[Any]] = [
            [ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), b"foobar"],
            [ConditionOpcode.CREATE_COIN, inner_puzzle_hash, SINGLETON_AMOUNT],
        ]
        singleton_coin_spend, singleton_signing_puzzle = make_singleton_coin_spend(
            eve_coin_spend, singleton, inner_puzzle, inner_conditions
        )
        # Spend also a remaining coin
        remaining_spend_solution = SerializedProgram.from_program(
            Program.to([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, remaining_coin.amount]])
        )
        remaining_coin_spend = CoinSpend(remaining_coin, IDENTITY_PUZZLE, remaining_spend_solution)
        await make_and_send_spend_bundle(
            sim,
            sim_client,
            [remaining_coin_spend, singleton_coin_spend],
            is_eligible_for_ff,
            signing_puzzle=singleton_signing_puzzle,
            signing_coin=singleton,
            aggsig=sig,
        )
        unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
            singleton_puzzle_hash
        )
        singleton_child, [remaining_coin] = await get_singleton_and_remaining_coins(sim)
        assert singleton_child.amount == SINGLETON_AMOUNT
        assert unspent_lineage_info == UnspentLineageInfo(
            coin_id=singleton_child.name(),
            coin_amount=singleton_child.amount,
            parent_id=singleton.name(),
            parent_amount=singleton.amount,
            parent_parent_id=eve_coin_spend.coin.name(),
        )
        # Now let's spend the first version again (despite being already spent by now)
        remaining_spend_solution = SerializedProgram.from_program(
            Program.to([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, remaining_coin.amount]])
        )
        remaining_coin_spend = CoinSpend(remaining_coin, IDENTITY_PUZZLE, remaining_spend_solution)
        status, error = await make_and_send_spend_bundle(
            sim,
            sim_client,
            [remaining_coin_spend, singleton_coin_spend],
            is_eligible_for_ff,
            signing_puzzle=singleton_signing_puzzle,
            signing_coin=singleton,
            aggsig=sig,
        )
        if is_eligible_for_ff:
            # Instead of rejecting this as double spend, we perform a fast forward,
            # spending the singleton child as a result, and creating the latest
            # version which is the grandchild in this scenario
            assert status == MempoolInclusionStatus.SUCCESS
            assert error is None
            unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
                singleton_puzzle_hash
            )
            singleton_grandchild, [remaining_coin] = await get_singleton_and_remaining_coins(sim)
            assert unspent_lineage_info == UnspentLineageInfo(
                coin_id=singleton_grandchild.name(),
                coin_amount=singleton_grandchild.amount,
                parent_id=singleton_child.name(),
                parent_amount=singleton_child.amount,
                parent_parent_id=singleton.name(),
            )
        else:
            # As this singleton is not eligible for fast forward, attempting to
            # spend one of its earlier versions is considered a double spend
            assert status == MempoolInclusionStatus.FAILED
            assert error == Err.DOUBLE_SPEND


@pytest.mark.anyio
async def test_singleton_fast_forward_same_block() -> None:
    """
    This tests covers sending multiple transactions that spend an already spent
    singleton version, all in the same block, to make sure they get properly
    fast forwarded and chained down to a latest unspent version
    """
    START_AMOUNT = uint64(1337)
    # We're decrementing the next iteration's amount for testing purposes
    SINGLETON_AMOUNT = uint64(1335)
    async with sim_and_client() as (sim, sim_client):
        singleton, eve_coin_spend, inner_puzzle, remaining_coin = await prepare_and_test_singleton(
            sim, sim_client, True, START_AMOUNT, SINGLETON_AMOUNT
        )
        # Let's spend this first version, to create a bigger singleton child
        singleton_puzzle_hash = eve_coin_spend.coin.puzzle_hash
        inner_puzzle_hash = inner_puzzle.get_tree_hash()
        sk = AugSchemeMPL.key_gen(b"9" * 32)
        g1 = sk.get_g1()
        sig = AugSchemeMPL.sign(sk, b"foobar", g1)
        inner_conditions: list[list[Any]] = [
            [ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), b"foobar"],
            [ConditionOpcode.CREATE_COIN, inner_puzzle_hash, SINGLETON_AMOUNT],
        ]
        singleton_coin_spend, _ = make_singleton_coin_spend(eve_coin_spend, singleton, inner_puzzle, inner_conditions)
        # Spend also a remaining coin. Change amount to create a new coin ID.
        # The test assumes any odd amount is a singleton, so we must keep it
        # even
        remaining_spend_solution = SerializedProgram.from_program(
            Program.to([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, remaining_coin.amount - 2]])
        )
        remaining_coin_spend = CoinSpend(remaining_coin, IDENTITY_PUZZLE, remaining_spend_solution)
        await make_and_send_spend_bundle(sim, sim_client, [remaining_coin_spend, singleton_coin_spend], aggsig=sig)
        unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
            singleton_puzzle_hash
        )
        singleton_child, [remaining_coin] = await get_singleton_and_remaining_coins(sim)
        assert singleton_child.amount == SINGLETON_AMOUNT
        assert unspent_lineage_info == UnspentLineageInfo(
            coin_id=singleton_child.name(),
            coin_amount=singleton_child.amount,
            parent_id=singleton.name(),
            parent_amount=singleton.amount,
            parent_parent_id=eve_coin_spend.coin.name(),
        )
        # Now let's send 3 arbitrary spends of the already spent singleton in
        # one block. They should all properly fast forward

        sk = AugSchemeMPL.key_gen(b"a" * 32)
        g1 = sk.get_g1()
        sig = AugSchemeMPL.sign(sk, b"foobar", g1)
        for i in range(3):
            # This cost adjustment allows us to maintain the order of spends due to fee per
            # cost and amounts dynamics
            cost_factor = (i + 1) * 5
            inner_conditions = [[ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), b"foobar"] for _ in range(cost_factor)]
            aggsig = G2Element()
            for _ in range(cost_factor):
                aggsig += sig
            inner_conditions.append([ConditionOpcode.CREATE_COIN, inner_puzzle_hash, SINGLETON_AMOUNT])
            singleton_coin_spend, _ = make_singleton_coin_spend(
                eve_coin_spend, singleton, inner_puzzle, inner_conditions
            )
            remaining_coin_spend = CoinSpend(remaining_coin, IDENTITY_PUZZLE, remaining_spend_solution)
            status, error = await sim_client.push_tx(SpendBundle([singleton_coin_spend, remaining_coin_spend], aggsig))
            assert error is None
            assert status == MempoolInclusionStatus.SUCCESS

        # Farm a block to process all these spend bundles
        await sim.farm_block()
        unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
            singleton_puzzle_hash
        )
        latest_singleton, [remaining_coin] = await get_singleton_and_remaining_coins(sim)
        assert unspent_lineage_info is not None
        # The unspent coin ID should reflect the latest version
        assert unspent_lineage_info.coin_id == latest_singleton.name()
        # The latest version should have the last random amount
        assert latest_singleton.amount == SINGLETON_AMOUNT
        # The unspent coin amount should reflect the latest version
        assert unspent_lineage_info.coin_amount == latest_singleton.amount
        # The unspent parent ID should reflect the latest version's parent
        assert unspent_lineage_info.parent_id == latest_singleton.parent_coin_info
        # The one before it should have the second last random amount
        assert unspent_lineage_info.parent_amount == SINGLETON_AMOUNT


@pytest.mark.anyio
async def test_mempool_items_immutability_on_ff() -> None:
    """
    This tests processing singleton fast forward spends for mempool items using
    modified copies, without altering those original mempool items.
    """
    SINGLETON_AMOUNT = uint64(1337)
    async with sim_and_client() as (sim, sim_client):
        singleton, eve_coin_spend, inner_puzzle, remaining_coin = await prepare_and_test_singleton(
            sim, sim_client, True, SINGLETON_AMOUNT, SINGLETON_AMOUNT
        )
        singleton_name = singleton.name()
        singleton_puzzle_hash = eve_coin_spend.coin.puzzle_hash
        inner_puzzle_hash = inner_puzzle.get_tree_hash()
        sk = AugSchemeMPL.key_gen(b"1" * 32)
        g1 = sk.get_g1()
        sig = AugSchemeMPL.sign(sk, b"foobar", g1)
        inner_conditions: list[list[Any]] = [
            [ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), b"foobar"],
            [ConditionOpcode.CREATE_COIN, inner_puzzle_hash, SINGLETON_AMOUNT],
        ]
        singleton_coin_spend, singleton_signing_puzzle = make_singleton_coin_spend(
            eve_coin_spend, singleton, inner_puzzle, inner_conditions
        )
        remaining_spend_solution = SerializedProgram.from_program(
            Program.to([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, remaining_coin.amount]])
        )
        remaining_coin_spend = CoinSpend(remaining_coin, IDENTITY_PUZZLE, remaining_spend_solution)
        await make_and_send_spend_bundle(
            sim,
            sim_client,
            [remaining_coin_spend, singleton_coin_spend],
            signing_puzzle=singleton_signing_puzzle,
            signing_coin=singleton,
            aggsig=sig,
        )
        unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
            singleton_puzzle_hash
        )
        singleton_child, [remaining_coin] = await get_singleton_and_remaining_coins(sim)
        singleton_child_name = singleton_child.name()
        assert singleton_child.amount == SINGLETON_AMOUNT
        assert unspent_lineage_info == UnspentLineageInfo(
            coin_id=singleton_child_name,
            coin_amount=singleton_child.amount,
            parent_id=singleton_name,
            parent_amount=singleton.amount,
            parent_parent_id=eve_coin_spend.coin.name(),
        )
        # Now let's spend the first version again (despite being already spent
        # by now) to exercise its fast forward.
        remaining_spend_solution = SerializedProgram.from_program(
            Program.to([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, remaining_coin.amount]])
        )
        remaining_coin_spend = CoinSpend(remaining_coin, IDENTITY_PUZZLE, remaining_spend_solution)
        sb = SpendBundle([remaining_coin_spend, singleton_coin_spend], sig)
        sb_name = sb.name()
        status, error = await sim_client.push_tx(sb)
        assert status == MempoolInclusionStatus.SUCCESS
        assert error is None
        original_item = copy.copy(sim_client.service.mempool_manager.get_mempool_item(sb_name))
        original_filter = sim_client.service.mempool_manager.get_filter()
        # Let's trigger the fast forward by creating a mempool bundle
        result = await sim.mempool_manager.create_bundle_from_mempool(
            sim_client.service.block_records[-1].header_hash,
        )
        assert result is not None
        bundle, _ = result
        # Make sure the mempool bundle we created contains the result of our
        # fast forward, instead of our original spend.
        assert any(cs.coin.name() == singleton_child_name for cs in bundle.coin_spends)
        assert not any(cs.coin.name() == singleton_name for cs in bundle.coin_spends)
        # We should have processed our item without modifying it in-place
        new_item = copy.copy(sim_client.service.mempool_manager.get_mempool_item(sb_name))
        new_filter = sim_client.service.mempool_manager.get_filter()
        assert new_item == original_item
        assert new_filter == original_filter
        sb_filter = PyBIP158(bytearray(original_filter))
        items_not_in_sb_filter = sim_client.service.mempool_manager.get_items_not_in_filter(sb_filter)
        assert len(items_not_in_sb_filter) == 0


@pytest.mark.anyio
async def test_double_spend_ff_spend_no_latest_unspent() -> None:
    """
    This test covers the scenario where we receive a spend bundle with a
    singleton fast forward spend that has currently no unspent coin.
    """
    test_amount = uint64(1337)
    async with sim_and_client() as (sim, sim_client):
        # Prepare a singleton spend
        singleton, eve_coin_spend, inner_puzzle, _ = await prepare_and_test_singleton(
            sim, sim_client, True, start_amount=test_amount, singleton_amount=test_amount
        )
        singleton_name = singleton.name()
        singleton_puzzle_hash = eve_coin_spend.coin.puzzle_hash
        inner_puzzle_hash = inner_puzzle.get_tree_hash()
        sk = AugSchemeMPL.key_gen(b"9" * 32)
        g1 = sk.get_g1()
        sig = AugSchemeMPL.sign(sk, b"foobar", g1)
        inner_conditions: list[list[Any]] = [
            [ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), b"foobar"],
            [ConditionOpcode.CREATE_COIN, inner_puzzle_hash, test_amount],
        ]
        singleton_coin_spend, _ = make_singleton_coin_spend(eve_coin_spend, singleton, inner_puzzle, inner_conditions)
        # Get its current latest unspent info
        unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
            singleton_puzzle_hash
        )
        assert unspent_lineage_info == UnspentLineageInfo(
            coin_id=singleton_name,
            coin_amount=test_amount,
            parent_id=eve_coin_spend.coin.name(),
            parent_amount=eve_coin_spend.coin.amount,
            parent_parent_id=eve_coin_spend.coin.parent_coin_info,
        )
        # Let's remove this latest unspent coin from the coin store
        async with sim_client.service.coin_store.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("DELETE FROM coin_record WHERE coin_name = ?", (unspent_lineage_info.coin_id,))
        # This singleton no longer has a latest unspent coin
        unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
            singleton_puzzle_hash
        )
        assert unspent_lineage_info is None
        # Let's attempt to spend this singleton and get get it fast forwarded
        status, error = await make_and_send_spend_bundle(sim, sim_client, [singleton_coin_spend], aggsig=sig)
        # It fails validation because it doesn't currently have a latest unspent
        assert status == MempoolInclusionStatus.FAILED
        assert error == Err.DOUBLE_SPEND


@pytest.mark.parametrize("optimized_path", [True, False])
@pytest.mark.anyio
async def test_items_eviction_on_new_peak_with_melted_singleton(optimized_path: bool) -> None:
    """
    This test covers the scenario where a singleton gets melted and we receive
    it as a spent coin on new peak, to make sure all existing mempool items
    with spends that belong to this singleton, get removed from the mempool.
    """
    test_amount = uint64(1337)
    async with sim_and_client() as (sim, sim_client):
        # Prepare a singleton spend
        singleton, eve_coin_spend, inner_puzzle, remaining_coin = await prepare_and_test_singleton(
            sim, sim_client, True, start_amount=test_amount, singleton_amount=test_amount
        )
        singleton_name = singleton.name()
        inner_puzzle_hash = inner_puzzle.get_tree_hash()
        sk = AugSchemeMPL.key_gen(b"9" * 32)
        g1 = sk.get_g1()
        sig = AugSchemeMPL.sign(sk, b"foobar", g1)
        inner_conditions: list[list[Any]] = [
            [ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), b"foobar"],
            [ConditionOpcode.CREATE_COIN, inner_puzzle_hash, test_amount],
        ]
        singleton_coin_spend, _ = make_singleton_coin_spend(eve_coin_spend, singleton, inner_puzzle, inner_conditions)
        # Let's spend it to create a new version
        remaining_spend_solution = SerializedProgram.from_program(
            Program.to([[ConditionOpcode.CREATE_COIN, IDENTITY_PUZZLE_HASH, remaining_coin.amount]])
        )
        remaining_coin_spend = CoinSpend(remaining_coin, IDENTITY_PUZZLE, remaining_spend_solution)
        status, error = await make_and_send_spend_bundle(
            sim, sim_client, [singleton_coin_spend, remaining_coin_spend], aggsig=sig
        )
        assert error is None
        assert status == MempoolInclusionStatus.SUCCESS
        unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
            singleton.puzzle_hash
        )
        singleton_child, [remaining_coin] = await get_singleton_and_remaining_coins(sim)
        singleton_child_name = singleton_child.name()
        assert singleton_child.amount == test_amount
        assert unspent_lineage_info == UnspentLineageInfo(
            coin_id=singleton_child_name,
            coin_amount=singleton_child.amount,
            parent_id=singleton_name,
            parent_amount=singleton.amount,
            parent_parent_id=eve_coin_spend.coin.name(),
        )
        sb_names = []
        # Send 3 items that spend the original (spent) singleton version
        for i in range(3):
            inner_conditions = [[ConditionOpcode.AGG_SIG_UNSAFE, bytes(g1), b"foobar"] for _ in range(i + 1)]
            aggsig = G2Element()
            for _ in range(i + 1):
                aggsig += sig
            inner_conditions.append([ConditionOpcode.CREATE_COIN, inner_puzzle_hash, test_amount])
            singleton_coin_spend, _ = make_singleton_coin_spend(
                eve_coin_spend, singleton, inner_puzzle, inner_conditions
            )
            remaining_coin_spend = CoinSpend(remaining_coin, IDENTITY_PUZZLE, remaining_spend_solution)
            sb = SpendBundle([singleton_coin_spend, remaining_coin_spend], aggsig)
            await sim_client.push_tx(sb)
            sb_names.append(sb.name())
        for sb_name in sb_names:
            mi = sim.mempool_manager.mempool.get_item_by_id(sb_name)
            assert mi is not None
            assert singleton_name in mi.bundle_coin_spends
        # Now let's form a new peak with this singleton marked as a spent coin
        # Before calling new peak, let's remove the singleton from the coin
        # store, so that when we process spent coins, we check if this
        # singleton still has a latest unspent and we don't find any, so we
        # concluded that it melted.
        async with sim_client.service.coin_store.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("DELETE FROM coin_record WHERE coin_name = ?", (singleton_child_name,))
        # Ensure this singleton no longer has a latest unspent coin
        unspent_lineage_info = await sim_client.service.coin_store.get_unspent_lineage_info_for_puzzle_hash(
            singleton.puzzle_hash
        )
        assert unspent_lineage_info is None
        current_peak = sim_client.service.block_records[-1]
        test_new_peak = TestBlockRecord(
            header_hash=height_hash(current_peak.height + 1),
            height=uint32(current_peak.height + 1),
            timestamp=uint64(current_peak.timestamp + 10),
            prev_transaction_block_height=current_peak.height,
            prev_transaction_block_hash=current_peak.header_hash,
        )
        if optimized_path:
            # Mark the singleton's latest version as spent
            spent_coins = [singleton_child_name]
        else:
            # Trigger a rebuild of the mempool (slow path)
            spent_coins = None
        await sim.mempool_manager.new_peak(test_new_peak, spent_coins)
        # Make sure all items with spends that belong to this singleton got removed
        for sb_name in sb_names:
            assert sim.mempool_manager.mempool.get_item_by_id(sb_name) is None


@pytest.mark.anyio
async def test_revisit_item_with_related_ff_spends_singleton_melts() -> None:
    """
    This test covers calling `revisit_item_with_related_ff_spends` with a
    melted singleton as a spent coin, to make sure that mempool items
    that spend any of the singleton's versions get marked for removal.
    """

    async def get_unspent_lineage_info_for_puzzle_hash(puzzle_hash: bytes32) -> Optional[UnspentLineageInfo]:
        if puzzle_hash == IDENTITY_PUZZLE_HASH:
            return None
        assert False  # pragma: no cover

    singleton_latest_unspent = TEST_COIN3
    singleton_latest_unspent_id = TEST_COIN_ID3
    another_coin = TEST_COIN2
    # Create a test item with an older version of the singleton
    test_item = mk_item([singleton_latest_unspent, another_coin])
    test_item.bundle_coin_spends[singleton_latest_unspent_id] = dataclasses.replace(
        test_item.bundle_coin_spends[singleton_latest_unspent_id], ff_latest_version=singleton_latest_unspent_id
    )
    # Calling `revisit_item_with_related_ff_spends` with the singleton's
    # latest version as a spent coin should mark our test item for removal.
    item_spends_to_update = await update_item_on_spent_singleton(
        mempool_item=test_item,
        spent_coin_id=singleton_latest_unspent_id,
        get_unspent_lineage_info_for_puzzle_hash=get_unspent_lineage_info_for_puzzle_hash,
        height=uint32(5),
        constants=DEFAULT_CONSTANTS,
    )
    # We mark this item for removal without updating it
    assert item_spends_to_update is None
    assert test_item.bundle_coin_spends[singleton_latest_unspent_id].ff_latest_version == singleton_latest_unspent_id


@pytest.mark.anyio
async def test_revisit_item_with_related_ff_spends_singleton_stays() -> None:
    """
    This test covers calling `revisit_item_with_related_ff_spends` with a
    singleton that got spent into a new version, to make sure that mempool
    items that spend any of this singleton's previous versions get updated
    with this latest unspent version.
    """
    singleton_child_coin = Coin(TEST_FF_SINGLETON_NAME, TEST_FF_SINGLETON_PH, TEST_FF_SINGLETON_AMOUNT)
    singleton_child_coin_id = singleton_child_coin.name()
    latest_unspent_coin = Coin(singleton_child_coin_id, TEST_FF_SINGLETON_PH, TEST_FF_SINGLETON_AMOUNT)
    latest_unspent_id = latest_unspent_coin.name()
    unspent_lineage_info_after_current_one = UnspentLineageInfo(
        coin_id=latest_unspent_id,
        coin_amount=TEST_FF_SINGLETON_AMOUNT,
        parent_id=singleton_child_coin_id,
        parent_amount=TEST_FF_SINGLETON_AMOUNT,
        parent_parent_id=TEST_FF_SINGLETON_NAME,
    )

    async def get_unspent_lineage_info_for_puzzle_hash(puzzle_hash: bytes32) -> UnspentLineageInfo | None:
        # This is latest version after the current latest unspent gets spent
        if puzzle_hash == TEST_FF_SINGLETON_PH:
            return unspent_lineage_info_after_current_one
        assert False  # pragma: no cover

    # Create a test item with an older version of the singleton
    other_coin = TEST_COIN2
    other_coin_id = TEST_COIN_ID2
    conds = make_test_conds(cost=123456789, spend_ids=[TEST_FF_SINGLETON_NAME, other_coin_id])
    other_coin_spend = make_spend(other_coin, IDENTITY_PUZZLE, SerializedProgram.to([]))
    sb = SpendBundle([TEST_FF_SINGLETON_SPEND, other_coin_spend], G2Element())
    bundle_coin_spends = {
        TEST_FF_SINGLETON_NAME: BundleCoinSpend(
            coin_spend=TEST_FF_SINGLETON_SPEND,
            eligible_for_dedup=False,
            ff_latest_version=TEST_FF_SINGLETON_NAME,
            additions=[singleton_child_coin],
        ),
        other_coin_id: BundleCoinSpend(
            coin_spend=other_coin_spend, eligible_for_dedup=False, ff_latest_version=None, additions=[]
        ),
    }
    test_item = MempoolItem(sb, uint64(0), conds, sb.name(), uint32(0), bundle_coin_spends=bundle_coin_spends)
    # Calling `revisit_item_with_related_ff_spends` with the singleton's
    # latest version as a spent coin should give us an updated internal item.
    item_spends_to_update = await update_item_on_spent_singleton(
        mempool_item=test_item,
        spent_coin_id=TEST_FF_SINGLETON_NAME,
        get_unspent_lineage_info_for_puzzle_hash=get_unspent_lineage_info_for_puzzle_hash,
        height=uint32(5),
        constants=DEFAULT_CONSTANTS,
    )
    # We updated the singleton spend with the latest unspent version
    assert item_spends_to_update == [(latest_unspent_id, TEST_FF_SINGLETON_NAME, test_item.name)]
    assert test_item.bundle_coin_spends[TEST_FF_SINGLETON_NAME].ff_latest_version == latest_unspent_id
