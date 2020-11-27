import asyncio
from secrets import token_bytes
from pathlib import Path
import sqlite3

import aiosqlite
import pytest
from pytest import raises

from src.full_node.full_node_store import FullNodeStore
from src.types.sized_bytes import bytes32
from src.types.unfinished_block import UnfinishedBlock
from src.util.ints import uint32, uint64
from tests.setup_nodes import test_constants, bt
from tests.full_node.fixtures import empty_blockchain


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestFullNodeStore:
    @pytest.mark.asyncio
    async def test_basic_store(self, empty_blockchain):
        blocks = bt.get_consecutive_blocks(10)

        store = await FullNodeStore.create(test_constants)

        unfinished_blocks = []
        for block in blocks:
            unfinished_blocks.append(
                UnfinishedBlock(
                    block.finished_sub_slots,
                    block.reward_chain_sub_block.get_unfinished(),
                    block.challenge_chain_sp_proof,
                    block.reward_chain_sp_proof,
                    block.foliage_sub_block,
                    block.foliage_block,
                    block.transactions_info,
                    block.transactions_generator,
                )
            )

        # Add/get candidate block
        assert store.get_candidate_block(unfinished_blocks[0].get_hash()) is None
        for height, unf_block in enumerate(unfinished_blocks):
            store.add_candidate_block(unf_block.get_hash(), height, unf_block)

        assert store.get_candidate_block(unfinished_blocks[4].get_hash()) == unfinished_blocks[4]
        store.clear_candidate_blocks_below(uint32(8))
        assert store.get_candidate_block(unfinished_blocks[5].get_hash()) is None
        assert store.get_candidate_block(unfinished_blocks[8].get_hash()) is not None

        # Test seen unfinished blocks
        h_hash_1 = bytes32(token_bytes(32))
        assert not store.seen_unfinished_block(h_hash_1)
        assert store.seen_unfinished_block(h_hash_1)
        store.clear_seen_unfinished_blocks()
        assert not store.seen_unfinished_block(h_hash_1)

        # Disconnected blocks
        assert store.get_disconnected_block(blocks[0].prev_header_hash) is None
        for block in blocks:
            store.add_disconnected_block(block)
            assert store.get_disconnected_block_by_prev(block.prev_header_hash) == block
            assert store.get_disconnected_block(block.header_hash) == block

        # Add/get unfinished block
        for height, unf_block in enumerate(unfinished_blocks):
            assert store.get_unfinished_block(unf_block.partial_hash) is None
            store.add_unfinished_block(height, unf_block)
            assert store.get_unfinished_block(unf_block.partial_hash) == unf_block
            store.remove_unfinished_block(unf_block.partial_hash)
            assert store.get_unfinished_block(unf_block.partial_hash) is None

        blocks = bt.get_consecutive_blocks(1, skip_slots=5)
        sub_slots = blocks[0].finished_sub_slots
        assert len(sub_slots) == 5

        # Test adding non-connecting sub-slots genesis
        assert store.get_sub_slot(test_constants.FIRST_CC_CHALLENGE) is None
        assert store.get_sub_slot(sub_slots[0].challenge_chain.get_hash()) is None
        assert store.get_sub_slot(sub_slots[1].challenge_chain.get_hash()) is None
        assert not store.new_finished_sub_slot(sub_slots[1], {}, None)
        assert not store.new_finished_sub_slot(sub_slots[2], {}, None)

        # Test adding sub-slots after genesis
        assert store.new_finished_sub_slot(sub_slots[0], {}, None)
        assert store.get_sub_slot(sub_slots[0].challenge_chain.get_hash())[0] == sub_slots[0]
        assert store.get_sub_slot(sub_slots[1].challenge_chain.get_hash()) is None
        assert store.new_finished_sub_slot(sub_slots[1], {}, None)
        for i in range(len(sub_slots)):
            assert store.new_finished_sub_slot(sub_slots[i], {}, None)
            assert store.get_sub_slot(sub_slots[i].challenge_chain.get_hash())[0] == sub_slots[i]

        assert store.get_finished_sub_slots(None, {}, sub_slots[-1].challenge_chain.get_hash(), False) == sub_slots
        with raises(ValueError):
            store.get_finished_sub_slots(None, {}, sub_slots[-1].challenge_chain.get_hash(), True)

        assert store.get_finished_sub_slots(None, {}, sub_slots[-2].challenge_chain.get_hash(), False) == sub_slots[:-1]

        # Test adding genesis peak
        await empty_blockchain.receive_block(blocks[0])
        peak = empty_blockchain.get_peak()
        if peak.overflow:
            store.new_peak(peak, sub_slots[-1], sub_slots[-2], False, {})
        else:
            store.new_peak(peak, sub_slots[-1], None, False, {})

        assert store.get_sub_slot(sub_slots[0].challenge_chain.get_hash()) is None
        assert store.get_sub_slot(sub_slots[1].challenge_chain.get_hash()) is None
        assert store.get_sub_slot(sub_slots[2].challenge_chain.get_hash()) is None
        assert store.get_sub_slot(sub_slots[3].challenge_chain.get_hash())[0] == sub_slots[3]
        assert store.get_sub_slot(sub_slots[4].challenge_chain.get_hash())[0] == sub_slots[4]

        assert (
            store.get_finished_sub_slots(
                peak, empty_blockchain.sub_blocks, sub_slots[-1].challenge_chain.get_hash(), False
            )
            == []
        )

        # Test adding non genesis peak directly
        blocks = bt.get_consecutive_blocks(2, skip_slots=2)
        for block in blocks:
            await empty_blockchain.receive_block(block)
            sb = empty_blockchain.sub_blocks[block.header_hash]
