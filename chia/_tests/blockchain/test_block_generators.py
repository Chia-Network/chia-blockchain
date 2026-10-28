from __future__ import annotations

import pytest
from chia_rs import (
    INTERNED_SPEND_LIST,
    FullBlock,
    get_flags_for_height_and_constants,
    max_canonical_blob_size,
    tree_hash_2026,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64
from pytest_mock import MockerFixture

import chia.simulator.block_tools as block_tools_module
from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block_no_error
from chia._tests.util.blockchain import create_blockchain
from chia.consensus.block_generator_info import get_transactions_generator_bytes
from chia.consensus.blockchain_mmr import BlockchainMMRManager
from chia.consensus.generator_validation import compute_generator_root, validate_generator_root
from chia.consensus.get_block_challenge import pre_sp_tx_block_height
from chia.consensus.multiprocess_validation import _run_block
from chia.full_node.hard_fork_utils import get_flags
from chia.simulator.block_tools import BlockTools, load_block_list, make_unfinished_block, test_constants
from chia.util.block_cache import BlockCache
from chia.util.errors import Err
from chia.util.hash import std_hash


@pytest.mark.anyio
@pytest.mark.parametrize("start_height", [10, 550])
@pytest.mark.parametrize("force_overflow", [False, True])
async def test_injected_transaction_at_nonzero_hf2(
    fork_height2_500_block_tools: BlockTools,
    fork_height2_500_1000_blocks: list[FullBlock],
    start_height: int,
    force_overflow: bool,
    mocker: MockerFixture,
) -> None:
    bt = fork_height2_500_block_tools
    blocks = fork_height2_500_1000_blocks[:start_height]
    wallet = bt.get_farmer_wallet_tool()
    coin = next(
        coin for block in blocks for coin in block.get_included_reward_coins() if coin.puzzle_hash == bt.farmer_ph
    )
    bundle = wallet.generate_signed_transaction(uint64(coin.amount), wallet.get_new_puzzlehash(), coin)
    cost_spy = mocker.spy(block_tools_module, "compute_block_cost")
    generator_spy = mocker.spy(bt, "setup_new_gen")
    result = bt.get_consecutive_blocks(
        1,
        blocks,
        transaction_data=bundle,
        guarantee_transaction_block=True,
        force_overflow=force_overflow,
    )
    assert generator_spy.call_count == 1
    assert generator_spy.call_args.kwargs["transaction_data"] is bundle
    assert cost_spy.call_count == 1
    block = result[-1]
    _, _, records = load_block_list(result, bt.constants)
    cache = BlockCache(records, BlockchainMMRManager(bt.constants.GENESIS_CHALLENGE))
    prev_tx_height = pre_sp_tx_block_height(
        bt.constants,
        cache,
        prev_b_hash=block.prev_header_hash,
        sp_index=block.reward_chain_block.signage_point_index,
        finished_sub_slots=len(block.finished_sub_slots),
    )
    assert (prev_tx_height >= bt.constants.HARD_FORK2_HEIGHT) == (start_height == 550)
    assert block.version == (1 if start_height == 550 else 0)
    assert block.transactions_info is not None
    error, error_msg, conditions = _run_block(block, [], prev_tx_height, bt.constants)
    assert error is None, error_msg
    assert conditions is not None
    assert conditions.validated_signature
    assert conditions.cost == block.transactions_info.cost
    assert [spend.coin_id for spend in conditions.spends] == [coin.name()]


@pytest.mark.anyio
async def test_generator_refs_at_sf9(
    fork_height2_500_block_tools: BlockTools,
    fork_height2_500_1000_blocks: list[FullBlock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bt = fork_height2_500_block_tools
    monkeypatch.setattr(bt, "constants", bt.constants.replace(SOFT_FORK9_HEIGHT=uint32(500)))
    _, _, records = load_block_list(fork_height2_500_1000_blocks[:10], bt.constants)
    curr = records[fork_height2_500_1000_blocks[9].header_hash]
    block_refs = [uint32(0)]
    for prev_tx_height in (499, 500):
        generator = bt.setup_new_gen(
            [],
            uint32(curr.height + 1),
            None,
            None,
            [],
            prev_tx_height=uint32(prev_tx_height),
            dummy_block_references=True,
            include_transactions=False,
            transaction_data=None,
            block_refs=block_refs,
        )
        if prev_tx_height < 500:
            assert generator is not None
            assert generator.block_refs == block_refs
        else:
            assert generator is None
        assert block_refs == [uint32(0)]


@pytest.mark.anyio
@pytest.mark.parametrize("force_overflow", [False, True])
async def test_generated_transactions_across_forks(
    fork_height2_500_block_tools: BlockTools,
    monkeypatch: pytest.MonkeyPatch,
    mocker: MockerFixture,
    force_overflow: bool,
) -> None:
    bt = fork_height2_500_block_tools
    constants = bt.constants.replace(
        HARD_FORK_HEIGHT=uint32(10), HARD_FORK2_HEIGHT=uint32(20), SOFT_FORK9_HEIGHT=uint32(40)
    )
    monkeypatch.setattr(bt, "constants", constants)
    generator_spy = mocker.spy(bt, "setup_new_gen")
    cost_spy = mocker.spy(block_tools_module, "compute_block_cost")
    blocks = bt.get_consecutive_blocks(
        80,
        seed=b"cached-generators",
        include_transactions=True,
        dummy_block_references=True,
        force_overflow=force_overflow,
    )

    # Non-transaction candidates reuse the pending generator instead of signing
    # and executing another spend bundle. Inclusion must invalidate the cache.
    transaction_blocks = [block for block in blocks[1:] if block.is_transaction_block()]
    assert len(transaction_blocks) <= generator_spy.call_count < len(blocks) - 1
    assert cost_spy.call_count == generator_spy.call_count
    flags = {
        get_flags_for_height_and_constants(call.kwargs["prev_tx_height"], constants)
        for call in generator_spy.call_args_list
    }
    assert len(flags) == 3
    assert any(flag & INTERNED_SPEND_LIST for flag in flags)
    assert any(not flag & INTERNED_SPEND_LIST for flag in flags)

    # Validate the whole chain, including costs, serialization, signatures and
    # coin availability. Reusing a consumed generator would double-spend here.
    async with create_blockchain(constants, 2) as (blockchain, _):
        for block in blocks:
            generator = get_transactions_generator_bytes(block)
            if generator is not None:
                assert block.transactions_info is not None
                interned = (await get_flags(constants, blockchain, block)) & INTERNED_SPEND_LIST
                expected_root = tree_hash_2026(generator) if interned else std_hash(generator)
                assert block.transactions_info.generator_root == expected_root
                wrong_root = std_hash(generator) if interned else bytes32.zeros
                assert wrong_root != expected_root
                unfinished = make_unfinished_block(block, constants)
                assert unfinished.transactions_info is not None
                bad_block = unfinished.replace(
                    transactions_info=unfinished.transactions_info.replace(generator_root=wrong_root)
                )
                _, error = await blockchain.validate_unfinished_block_header(bad_block)
                assert error == Err.INVALID_TRANSACTIONS_GENERATOR_HASH
            await _validate_and_add_block_no_error(blockchain, block)


def test_generator_root_activation() -> None:
    from chia_rs import solution_generator, solution_generator_2026

    constants = test_constants.replace(HARD_FORK2_HEIGHT=uint32(10))
    legacy = solution_generator([])
    interned = solution_generator_2026([])
    assert compute_generator_root(legacy, get_flags_for_height_and_constants(9, constants), constants) == std_hash(
        legacy
    )
    root = tree_hash_2026(interned)
    assert compute_generator_root(interned, get_flags_for_height_and_constants(10, constants), constants) == root
    assert root != std_hash(interned)
    assert validate_generator_root(interned, root, constants, uint32(10))
    assert not validate_generator_root(interned, std_hash(interned), constants, uint32(10))
    assert not validate_generator_root(b"malformed", root, constants, uint32(10))


def test_generator_root_ignores_interned_encoding() -> None:
    constants = test_constants.replace(HARD_FORK2_HEIGHT=uint32(0))
    canonical = bytes.fromhex("fdff32303236 01 01 41 03 00 02 01")
    overlong = bytes.fromhex("fdff32303236 01 8001 41 03 00 02 01")
    assert std_hash(canonical) != std_hash(overlong)
    root = compute_generator_root(canonical, get_flags_for_height_and_constants(0, constants), constants)
    assert validate_generator_root(overlong, root, constants, uint32(0))


def test_generator_root_rejects_oversized_generator() -> None:
    constants = test_constants.replace(HARD_FORK2_HEIGHT=uint32(0))
    cap = max_canonical_blob_size(constants.MAX_BLOCK_COST_CLVM, constants.COST_PER_BYTE)
    oversized = bytes(cap + 1)
    with pytest.raises(ValueError, match="max_canonical_blob_size"):
        compute_generator_root(oversized, get_flags_for_height_and_constants(0, constants), constants)
    assert not validate_generator_root(oversized, bytes32.zeros, constants, uint32(0))


@pytest.mark.parametrize(
    "prev_tx_height, pre_sp_tx_height, fork_height",
    [(None, 0, 0), (None, 0, 10), (9, 9, 10), (10, 9, 10), (10, 10, 10)],
)
@pytest.mark.parametrize("has_generator", [False, True])
def test_foliage_generator_root(
    prev_tx_height: int | None,
    pre_sp_tx_height: int,
    fork_height: int,
    has_generator: bool,
    mocker: MockerFixture,
) -> None:
    from chia_rs import G1Element, G2Element, PoolTarget, solution_generator, solution_generator_2026
    from chia_rs.sized_ints import uint128

    from chia.consensus.block_creation import compute_block_fee, create_foliage
    from chia.types.generator_types import NewBlockGenerator

    constants = test_constants.replace(HARD_FORK2_HEIGHT=uint32(fork_height))
    interned = pre_sp_tx_height >= fork_height
    generator = solution_generator_2026([]) if interned else solution_generator([])
    blocks = mocker.Mock()
    prev_block = None
    if prev_tx_height is not None:
        # The reward-accounting height may cross HF2 while the SP activation height has not.
        prev_block = mocker.Mock(
            height=uint32(prev_tx_height),
            is_transaction_block=True,
            total_iters=uint128(1),
            fees=uint64(0),
            header_hash=bytes32.zeros,
            pool_puzzle_hash=bytes32.zeros,
            farmer_puzzle_hash=bytes32.zeros,
        )
        blocks.block_record.return_value = mocker.Mock(is_transaction_block=True)
    reward_block = mocker.Mock()
    reward_block.get_hash.return_value = bytes32.zeros
    reward_block.proof_of_space.pool_public_key = G1Element()
    reward_block.proof_of_space.plot_public_key = G1Element()
    _, _, info = create_foliage(
        constants,
        reward_block,
        NewBlockGenerator(generator) if has_generator else None,
        prev_block,
        blocks,
        uint128(2),
        uint32(pre_sp_tx_height),
        uint64(1),
        bytes32.zeros,
        PoolTarget(bytes32.zeros, uint32(0)),
        lambda *_: G2Element(),
        lambda *_: G2Element(),
        b"generator-root",
        compute_block_fee,
    )
    assert info is not None
    expected = tree_hash_2026(generator) if interned else std_hash(generator)
    assert info.generator_root == (expected if has_generator else bytes32.zeros)
    if has_generator:
        assert validate_generator_root(generator, info.generator_root, constants, uint32(pre_sp_tx_height))
