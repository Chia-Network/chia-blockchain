from __future__ import annotations

import pytest
from chia_rs import BlockRecord, get_flags_for_height_and_constants
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.consensus.get_block_challenge import pre_sp_tx_block_height
from chia.full_node.hard_fork_utils import get_flags
from chia.simulator.block_tools import BlockTools, load_block_list, test_constants
from chia.util.block_cache import BlockCache


class MockBlocksProtocol(BlockCache):
    """Mock implementation of BlocksProtocol for testing get_flags."""

    async def get_block_record_from_db(self, header_hash: bytes32) -> BlockRecord | None:
        return self.try_block_record(header_hash)

    async def lookup_block_generators(self, header_hash: bytes32, generator_refs: set[uint32]) -> dict[uint32, bytes]:
        return {}

    def add_block_record(self, block_record: BlockRecord) -> None:
        self.add_block(block_record)


@pytest.mark.anyio
async def test_get_flags_outside_transition_period(bt: BlockTools) -> None:
    """Test get_flags when block is outside the transition period."""
    block_list = bt.get_consecutive_blocks(
        10,
        block_list_input=[],
        guarantee_transaction_block=True,
    )
    _, _, blocks = load_block_list(block_list, bt.constants)
    block = block_list[-1]
    mock_blocks = MockBlocksProtocol(blocks)

    # Before hard fork: block.height < HARD_FORK2_HEIGHT, expects 0
    constants = test_constants.replace(HARD_FORK2_HEIGHT=uint32(1000))
    assert block.height < constants.HARD_FORK2_HEIGHT
    result = await get_flags(constants, mock_blocks, block)
    assert result == 0

    # After transition period: block.height >= HARD_FORK2_HEIGHT + SUB_EPOCH_BLOCKS
    constants = test_constants.replace(
        HARD_FORK2_HEIGHT=uint32(0),
        SUB_EPOCH_BLOCKS=uint32(min(5, block.height)),
    )
    assert block.height >= constants.HARD_FORK2_HEIGHT + constants.SUB_EPOCH_BLOCKS
    result = await get_flags(constants, mock_blocks, block)
    assert result == get_flags_for_height_and_constants(block.height, constants)


@pytest.mark.anyio
async def test_get_flags_during_transition_period(bt: BlockTools) -> None:
    """When block.height is in the transition period, get_flags should walk
    the chain and return flags based on the latest tx block before signage point."""
    # We need more blocks to ensure we're in the transition period
    block_list = bt.get_consecutive_blocks(
        15,
        block_list_input=[],
        guarantee_transaction_block=True,
    )
    _, _, blocks = load_block_list(block_list, bt.constants)
    mock_blocks = MockBlocksProtocol(blocks)

    # Configure constants so that the block is in the transition period
    # HARD_FORK2_HEIGHT <= block.height < HARD_FORK2_HEIGHT + SUB_EPOCH_BLOCKS
    block = block_list[-1]
    # Set HARD_FORK2_HEIGHT to be close to block height but leave room for transition
    constants = test_constants.replace(
        HARD_FORK2_HEIGHT=uint32(max(0, block.height - 5)),
        SUB_EPOCH_BLOCKS=test_constants.SUB_EPOCH_BLOCKS,
    )

    # Ensure we're in the transition period
    assert block.height >= constants.HARD_FORK2_HEIGHT
    assert block.height < constants.HARD_FORK2_HEIGHT + constants.SUB_EPOCH_BLOCKS

    result = await get_flags(constants, mock_blocks, block)

    # The result should be based on the height of the latest tx block before the signage point
    expected_height = pre_sp_tx_block_height(
        constants=constants,
        blocks=mock_blocks,
        prev_b_hash=block.prev_header_hash,
        sp_index=block.reward_chain_block.signage_point_index,
        finished_sub_slots=len(block.finished_sub_slots),
    )
    expected = get_flags_for_height_and_constants(expected_height, constants)
    assert result == expected
