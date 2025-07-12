from __future__ import annotations

from typing import Optional

import pytest
from chia_rs import Coin, ConsensusConstants, FullBlock, additions_and_removals, get_flags_for_height_and_constants
from chia_rs.sized_ints import uint64

from chia.simulator.block_tools import BlockTools

# These test targets are used to trigger a build of the test chains.
# On CI we clone the test-cache repository to load the chains from, so they
# don't need to be re-generated.

# When running tests in parallel (with pytest-xdist) it's faster to first
# generate all the chains, so the same chains aren't being created in parallel.

# The cached test chains are stored in ~/.chia/blocks

# To generate the chains, run:

# pytest -m build_test_chains


@pytest.mark.build_test_chains
def test_trigger_default_400(default_400_blocks: list[FullBlock]) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_default_1000(default_1000_blocks: list[FullBlock]) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_pre_genesis_empty_1000(pre_genesis_empty_slots_1000_blocks: list[FullBlock]) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_default_1500(default_1500_blocks: list[FullBlock]) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_default_10000(
    default_10000_blocks: list[FullBlock],
    test_long_reorg_blocks: list[FullBlock],
    test_long_reorg_blocks_light: list[FullBlock],
    test_long_reorg_1500_blocks: list[FullBlock],
    test_long_reorg_1500_blocks_light: list[FullBlock],
) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_default_2000_compact(default_2000_blocks_compact: list[FullBlock]) -> None:
    pass


@pytest.mark.build_test_chains
def test_trigger_default_10000_compact(default_10000_blocks_compact: list[FullBlock]) -> None:
    pass


def validate_coins(constants: ConsensusConstants, blocks: list[FullBlock]) -> None:
    unspent_coins: set[Coin] = set()
    for block in blocks:
        rewards = block.get_included_reward_coins()

        if block.transactions_generator is not None:
            flags = get_flags_for_height_and_constants(block.height, constants)
            additions, removals = additions_and_removals(
                bytes(block.transactions_generator),
                [],
                flags,
                constants,
            )

            for _, rem in removals:
                try:
                    unspent_coins.remove(rem)
                except KeyError:  # pragma: no cover
                    print(f"at height: {block.height} removal: {rem} does not exist")
                    print("coinset: ", unspent_coins)
                    raise

            for add, _ in additions:
                unspent_coins.add(add)

        for add in rewards:
            unspent_coins.add(add)


def validate_chain(
    bt: BlockTools,
    blocks: list[FullBlock],
    *,
    seed: bytes = b"",
    empty_sub_slots: int = 0,
    normalized_to_identity_cc_eos: bool = False,
    normalized_to_identity_icc_eos: bool = False,
    normalized_to_identity_cc_sp: bool = False,
    normalized_to_identity_cc_ip: bool = False,
    block_list_input: Optional[list[FullBlock]] = None,
    time_per_block: Optional[float] = None,
    dummy_block_references: bool = False,
    include_transactions: bool = False,
) -> None:
    validate_coins(bt.constants, blocks)

    # make sure that the blocks we found on-disk are consistent with
    # the ones we would have generated
    input_length = len(block_list_input) if block_list_input else 0

    # 80 blocks is a balance between capturing all features of the
    # chains (such as block references) versus the cost of
    # generating and comparing blocks.
    request_length = min(80, len(blocks) - input_length)

    expected_blocks: list[FullBlock] = bt.get_consecutive_blocks(
        request_length,
        block_list_input=block_list_input,
        time_per_block=time_per_block,
        seed=seed,
        skip_slots=empty_sub_slots,
        normalized_to_identity_cc_eos=normalized_to_identity_cc_eos,
        normalized_to_identity_icc_eos=normalized_to_identity_icc_eos,
        normalized_to_identity_cc_sp=normalized_to_identity_cc_sp,
        normalized_to_identity_cc_ip=normalized_to_identity_cc_ip,
        dummy_block_references=dummy_block_references,
        include_transactions=include_transactions,
        genesis_timestamp=uint64(1234567890),
    )
    assert len(expected_blocks) - request_length == input_length
    # if this assert fails, and changing the test chains was
    # intentional, please also update the test chain cache.
    # run: pytest -m build_test_chains
    for i in range(input_length, len(expected_blocks)):
        print(f"i: {i}")
        if blocks[i] != expected_blocks[i]:  # pragma: no cover
            print(
                f"Block {i} in the block cache on disk differs "
                "from what BlockTools generated. Please make sure "
                "your test blocks are up-to-date"
            )
            print(f"disk:\n{blocks[i]}")
            print(f"block-tools:\n{expected_blocks[i]}")
        assert blocks[i] == expected_blocks[i]


def test_validate_default_400(bt: BlockTools, default_400_blocks: list[FullBlock]) -> None:
    validate_chain(bt, default_400_blocks, seed=b"400")


def test_validate_default_1000(bt: BlockTools, default_1000_blocks: list[FullBlock]) -> None:
    validate_chain(bt, default_1000_blocks, seed=b"1000")


def test_validate_pre_genesis_empty_1000(bt: BlockTools, pre_genesis_empty_slots_1000_blocks: list[FullBlock]) -> None:
    validate_chain(bt, pre_genesis_empty_slots_1000_blocks, seed=b"empty_slots", empty_sub_slots=1)


def test_validate_default_1500(bt: BlockTools, default_1500_blocks: list[FullBlock]) -> None:
    validate_chain(bt, default_1500_blocks, seed=b"1500")


def test_validate_default_10000(
    bt: BlockTools,
    default_10000_blocks: list[FullBlock],
) -> None:
    validate_chain(
        bt,
        default_10000_blocks,
        seed=b"10000",
        dummy_block_references=True,
    )


def test_validate_default_2000_compact(bt: BlockTools, default_2000_blocks_compact: list[FullBlock]) -> None:
    validate_chain(
        bt,
        default_2000_blocks_compact,
        normalized_to_identity_cc_eos=True,
        normalized_to_identity_icc_eos=True,
        normalized_to_identity_cc_ip=True,
        normalized_to_identity_cc_sp=True,
        seed=b"2000_compact",
    )


def test_validate_default_10000_compact(bt: BlockTools, default_10000_blocks_compact: list[FullBlock]) -> None:
    validate_chain(
        bt,
        default_10000_blocks_compact,
        normalized_to_identity_cc_eos=True,
        normalized_to_identity_icc_eos=True,
        normalized_to_identity_cc_ip=True,
        normalized_to_identity_cc_sp=True,
        seed=b"1000_compact",
    )


def test_validate_long_reorg_blocks(
    bt: BlockTools, test_long_reorg_blocks: list[FullBlock], default_10000_blocks: list[FullBlock]
) -> None:
    validate_chain(
        bt,
        test_long_reorg_blocks,
        block_list_input=default_10000_blocks[:500],
        seed=b"reorg_blocks",
        time_per_block=8,
        dummy_block_references=True,
        include_transactions=True,
    )


def test_validate_long_reorg_blocks_light(
    bt: BlockTools, test_long_reorg_blocks_light: list[FullBlock], default_10000_blocks: list[FullBlock]
) -> None:
    validate_chain(
        bt,
        test_long_reorg_blocks_light,
        block_list_input=default_10000_blocks[:500],
        seed=b"reorg_blocks2",
        dummy_block_references=True,
        include_transactions=True,
    )


def test_validate_long_reorg_1500_blocks(
    bt: BlockTools, test_long_reorg_1500_blocks: list[FullBlock], default_10000_blocks: list[FullBlock]
) -> None:
    validate_chain(
        bt,
        test_long_reorg_1500_blocks,
        block_list_input=default_10000_blocks[:1500],
        seed=b"reorg_blocks",
        time_per_block=8,
        dummy_block_references=True,
        include_transactions=True,
    )


def test_validate_long_reorg_1500_blocks_light(
    bt: BlockTools, test_long_reorg_1500_blocks_light: list[FullBlock], default_10000_blocks: list[FullBlock]
) -> None:
    validate_chain(
        bt,
        test_long_reorg_1500_blocks_light,
        block_list_input=default_10000_blocks[:1500],
        seed=b"reorg_blocks2",
        dummy_block_references=True,
        include_transactions=True,
    )
