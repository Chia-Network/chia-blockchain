# flake8: noqa: F811, F401
import asyncio
import logging
from secrets import token_bytes

import pytest
from pytest import raises

from chia.consensus.blockchain import ReceiveBlockResult
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.consensus.pot_iterations import is_overflow_block
from chia.full_node.full_node_store import FullNodeStore
from chia.full_node.signage_point import SignagePoint
from chia.protocols.timelord_protocol import NewInfusionPointVDF
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.block_cache import BlockCache
from chia.util.block_tools import get_signage_point
from chia.util.hash import std_hash
from chia.util.ints import uint8, uint32, uint64, uint128
from tests.core.fixtures import default_1000_blocks, empty_blockchain  # noqa: F401
from tests.setup_nodes import bt, test_constants

log = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


class TestFullNodeStore:
    @pytest.mark.asyncio
    async def test_basic_store(self, empty_blockchain, normalized_to_identity: bool = False):
        blockchain = empty_blockchain
        blocks = bt.get_consecutive_blocks(
            10,
            seed=b"1234",
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )

        store = await FullNodeStore.create(test_constants)

        unfinished_blocks = []
        for block in blocks:
            unfinished_blocks.append(
                UnfinishedBlock(
                    block.finished_sub_slots,
                    block.reward_chain_block.get_unfinished(),
                    block.challenge_chain_sp_proof,
                    block.reward_chain_sp_proof,
                    block.foliage,
                    block.foliage_transaction_block,
                    block.transactions_info,
                    block.transactions_generator,
                    [],
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

        # Add/get unfinished block
        for height, unf_block in enumerate(unfinished_blocks):
            assert store.get_unfinished_block(unf_block.partial_hash) is None
            store.add_unfinished_block(height, unf_block, PreValidationResult(None, uint64(123532), None))
            assert store.get_unfinished_block(unf_block.partial_hash) == unf_block
            store.remove_unfinished_block(unf_block.partial_hash)
            assert store.get_unfinished_block(unf_block.partial_hash) is None

        blocks = bt.get_consecutive_blocks(
            1,
            skip_slots=5,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
        )
        sub_slots = blocks[0].finished_sub_slots
        assert len(sub_slots) == 5

        assert (
            store.get_finished_sub_slots(
                BlockCache({}),
                None,
                sub_slots[0].challenge_chain.challenge_chain_end_of_slot_vdf.challenge,
            )
            == []
        )
        # Test adding non-connecting sub-slots genesis
        assert store.get_sub_slot(test_constants.GENESIS_CHALLENGE) is None
        assert store.get_sub_slot(sub_slots[0].challenge_chain.get_hash()) is None
        assert store.get_sub_slot(sub_slots[1].challenge_chain.get_hash()) is None
        assert store.new_finished_sub_slot(sub_slots[1], {}, None, None) is None
        assert store.new_finished_sub_slot(sub_slots[2], {}, None, None) is None

        # Test adding sub-slots after genesis
        assert store.new_finished_sub_slot(sub_slots[0], {}, None, None) is not None
        assert store.get_sub_slot(sub_slots[0].challenge_chain.get_hash())[0] == sub_slots[0]
        assert store.get_sub_slot(sub_slots[1].challenge_chain.get_hash()) is None
        assert store.new_finished_sub_slot(sub_slots[1], {}, None, None) is not None
        for i in range(len(sub_slots)):
            assert store.new_finished_sub_slot(sub_slots[i], {}, None, None) is not None
            assert store.get_sub_slot(sub_slots[i].challenge_chain.get_hash())[0] == sub_slots[i]

        assert store.get_finished_sub_slots(BlockCache({}), None, sub_slots[-1].challenge_chain.get_hash()) == sub_slots
        assert store.get_finished_sub_slots(BlockCache({}), None, std_hash(b"not a valid hash")) is None

        assert (
            store.get_finished_sub_slots(BlockCache({}), None, sub_slots[-2].challenge_chain.get_hash())
            == sub_slots[:-1]
        )

        # Test adding genesis peak
        await blockchain.receive_block(blocks[0])
        peak = blockchain.get_peak()
        peak_full_block = blockchain.get_full_peak()
        if peak.overflow:
            store.new_peak(peak, peak_full_block, sub_slots[-2], sub_slots[-1], False, {})
        else:
            store.new_peak(peak, peak_full_block, None, sub_slots[-1], False, {})

        assert store.get_sub_slot(sub_slots[0].challenge_chain.get_hash()) is None
        assert store.get_sub_slot(sub_slots[1].challenge_chain.get_hash()) is None
        assert store.get_sub_slot(sub_slots[2].challenge_chain.get_hash()) is None
        if peak.overflow:
            assert store.get_sub_slot(sub_slots[3].challenge_chain.get_hash())[0] == sub_slots[3]
        else:
            assert store.get_sub_slot(sub_slots[3].challenge_chain.get_hash()) is None
        assert store.get_sub_slot(sub_slots[4].challenge_chain.get_hash())[0] == sub_slots[4]

        assert (
            store.get_finished_sub_slots(
                blockchain,
                peak,
                sub_slots[-1].challenge_chain.get_hash(),
            )
            == []
        )

        # Test adding non genesis peak directly
        blocks = bt.get_consecutive_blocks(
            2,
            skip_slots=2,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )
        blocks = bt.get_consecutive_blocks(
            3,
            block_list_input=blocks,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )
        for block in blocks:
            await blockchain.receive_block(block)
            sb = blockchain.block_record(block.header_hash)
            sp_sub_slot, ip_sub_slot = await blockchain.get_sp_and_ip_sub_slots(block.header_hash)
            res = store.new_peak(sb, block, sp_sub_slot, ip_sub_slot, False, blockchain)
            assert res[0] is None

        # Add reorg blocks
        blocks_reorg = bt.get_consecutive_blocks(
            20,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )
        for block in blocks_reorg:
            res, _, _ = await blockchain.receive_block(block)
            if res == ReceiveBlockResult.NEW_PEAK:
                sb = blockchain.block_record(block.header_hash)
                sp_sub_slot, ip_sub_slot = await blockchain.get_sp_and_ip_sub_slots(block.header_hash)
                res = store.new_peak(sb, block, sp_sub_slot, ip_sub_slot, True, blockchain)
                assert res[0] is None

        # Add slots to the end
        blocks_2 = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks_reorg,
            skip_slots=2,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )
        for slot in blocks_2[-1].finished_sub_slots:
            store.new_finished_sub_slot(slot, blockchain, blockchain.get_peak(), await blockchain.get_full_peak())

        assert store.get_sub_slot(sub_slots[3].challenge_chain.get_hash()) is None
        assert store.get_sub_slot(sub_slots[4].challenge_chain.get_hash()) is None

        # Test adding signage point
        peak = blockchain.get_peak()
        ss_start_iters = peak.ip_sub_slot_total_iters(test_constants)
        for i in range(1, test_constants.NUM_SPS_SUB_SLOT - test_constants.NUM_SP_INTERVALS_EXTRA):
            sp = get_signage_point(
                test_constants,
                blockchain,
                peak,
                ss_start_iters,
                uint8(i),
                [],
                peak.sub_slot_iters,
            )
            assert store.new_signage_point(i, blockchain, peak, peak.sub_slot_iters, sp)

        blocks = blocks_reorg
        while True:
            blocks = bt.get_consecutive_blocks(
                1,
                block_list_input=blocks,
                normalized_to_identity_cc_eos=normalized_to_identity,
                normalized_to_identity_icc_eos=normalized_to_identity,
                normalized_to_identity_cc_ip=normalized_to_identity,
                normalized_to_identity_cc_sp=normalized_to_identity,
            )
            res, _, _ = await blockchain.receive_block(blocks[-1])
            if res == ReceiveBlockResult.NEW_PEAK:
                sb = blockchain.block_record(blocks[-1].header_hash)
                sp_sub_slot, ip_sub_slot = await blockchain.get_sp_and_ip_sub_slots(blocks[-1].header_hash)

                res = store.new_peak(sb, blocks[-1], sp_sub_slot, ip_sub_slot, True, blockchain)
                assert res[0] is None
                if sb.overflow and sp_sub_slot is not None:
                    assert sp_sub_slot != ip_sub_slot
                    break

        peak = blockchain.get_peak()
        assert peak.overflow
        # Overflow peak should result in 2 finished sub slots
        assert len(store.finished_sub_slots) == 2

        # Add slots to the end, except for the last one, which we will use to test invalid SP
        blocks_2 = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks,
            skip_slots=3,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )
        for slot in blocks_2[-1].finished_sub_slots[:-1]:
            store.new_finished_sub_slot(slot, blockchain, blockchain.get_peak(), await blockchain.get_full_peak())
        finished_sub_slots = blocks_2[-1].finished_sub_slots
        assert len(store.finished_sub_slots) == 4

        # Test adding signage points for overflow blocks (sp_sub_slot)
        ss_start_iters = peak.sp_sub_slot_total_iters(test_constants)
        # for i in range(peak.signage_point_index, test_constants.NUM_SPS_SUB_SLOT):
        #     if i < peak.signage_point_index:
        #         continue
        #     latest = peak
        #     while latest.total_iters > peak.sp_total_iters(test_constants):
        #         latest = blockchain.blocks[latest.prev_hash]
        #     sp = get_signage_point(
        #         test_constants,
        #         blockchain.blocks,
        #         latest,
        #         ss_start_iters,
        #         uint8(i),
        #         [],
        #         peak.sub_slot_iters,
        #     )
        #     assert store.new_signage_point(i, blockchain.blocks, peak, peak.sub_slot_iters, sp)

        # Test adding signage points for overflow blocks (ip_sub_slot)
        for i in range(1, test_constants.NUM_SPS_SUB_SLOT - test_constants.NUM_SP_INTERVALS_EXTRA):
            sp = get_signage_point(
                test_constants,
                blockchain,
                peak,
                peak.ip_sub_slot_total_iters(test_constants),
                uint8(i),
                [],
                peak.sub_slot_iters,
            )
            assert store.new_signage_point(i, blockchain, peak, peak.sub_slot_iters, sp)

        # Test adding future signage point, a few slots forward (good)
        saved_sp_hash = None
        for slot_offset in range(1, len(finished_sub_slots)):
            for i in range(
                1,
                test_constants.NUM_SPS_SUB_SLOT - test_constants.NUM_SP_INTERVALS_EXTRA,
            ):
                sp = get_signage_point(
                    test_constants,
                    blockchain,
                    peak,
                    peak.ip_sub_slot_total_iters(test_constants) + slot_offset * peak.sub_slot_iters,
                    uint8(i),
                    finished_sub_slots[:slot_offset],
                    peak.sub_slot_iters,
                )
                assert sp.cc_vdf is not None
                saved_sp_hash = sp.cc_vdf.output.get_hash()
                assert store.new_signage_point(i, blockchain, peak, peak.sub_slot_iters, sp)

        # Test adding future signage point (bad)
        for i in range(1, test_constants.NUM_SPS_SUB_SLOT - test_constants.NUM_SP_INTERVALS_EXTRA):
            sp = get_signage_point(
                test_constants,
                blockchain,
                peak,
                peak.ip_sub_slot_total_iters(test_constants) + len(finished_sub_slots) * peak.sub_slot_iters,
                uint8(i),
                finished_sub_slots[: len(finished_sub_slots)],
                peak.sub_slot_iters,
            )
            assert not store.new_signage_point(i, blockchain, peak, peak.sub_slot_iters, sp)

        # Test adding past signage point
        sp = SignagePoint(
            blocks[1].reward_chain_block.challenge_chain_sp_vdf,
            blocks[1].challenge_chain_sp_proof,
            blocks[1].reward_chain_block.reward_chain_sp_vdf,
            blocks[1].reward_chain_sp_proof,
        )
        assert not store.new_signage_point(
            blocks[1].reward_chain_block.signage_point_index,
            {},
            peak,
            blockchain.block_record(blocks[1].header_hash).sp_sub_slot_total_iters(test_constants),
            sp,
        )

        # Get signage point by index
        assert (
            store.get_signage_point_by_index(
                finished_sub_slots[0].challenge_chain.get_hash(),
                4,
                finished_sub_slots[0].reward_chain.get_hash(),
            )
            is not None
        )

        assert (
            store.get_signage_point_by_index(finished_sub_slots[0].challenge_chain.get_hash(), 4, std_hash(b"1"))
            is None
        )

        # Get signage point by hash
        assert store.get_signage_point(saved_sp_hash) is not None
        assert store.get_signage_point(std_hash(b"2")) is None

        # Test adding signage points before genesis
        store.initialize_genesis_sub_slot()
        assert len(store.finished_sub_slots) == 1
        for i in range(1, test_constants.NUM_SPS_SUB_SLOT - test_constants.NUM_SP_INTERVALS_EXTRA):
            sp = get_signage_point(
                test_constants,
                BlockCache({}, {}),
                None,
                uint128(0),
                uint8(i),
                [],
                peak.sub_slot_iters,
            )
            assert store.new_signage_point(i, {}, None, peak.sub_slot_iters, sp)

        blocks_3 = bt.get_consecutive_blocks(
            1,
            skip_slots=2,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )
        for slot in blocks_3[-1].finished_sub_slots:
            store.new_finished_sub_slot(slot, {}, None, None)
        assert len(store.finished_sub_slots) == 3
        finished_sub_slots = blocks_3[-1].finished_sub_slots

        for slot_offset in range(1, len(finished_sub_slots) + 1):
            for i in range(
                1,
                test_constants.NUM_SPS_SUB_SLOT - test_constants.NUM_SP_INTERVALS_EXTRA,
            ):
                sp = get_signage_point(
                    test_constants,
                    BlockCache({}, {}),
                    None,
                    slot_offset * peak.sub_slot_iters,
                    uint8(i),
                    finished_sub_slots[:slot_offset],
                    peak.sub_slot_iters,
                )
                assert store.new_signage_point(i, {}, None, peak.sub_slot_iters, sp)

        # Test adding signage points after genesis
        blocks_4 = bt.get_consecutive_blocks(
            1,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )
        blocks_5 = bt.get_consecutive_blocks(
            1,
            block_list_input=blocks_4,
            skip_slots=1,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )

        # If this is not the case, fix test to find a block that is
        assert (
            blocks_4[-1].reward_chain_block.signage_point_index
            < test_constants.NUM_SPS_SUB_SLOT - test_constants.NUM_SP_INTERVALS_EXTRA
        )
        await blockchain.receive_block(blocks_4[-1])
        sb = blockchain.block_record(blocks_4[-1].header_hash)
        store.new_peak(sb, blocks_4[-1], None, None, False, blockchain)
        for i in range(
            sb.signage_point_index + test_constants.NUM_SP_INTERVALS_EXTRA,
            test_constants.NUM_SPS_SUB_SLOT,
        ):
            if is_overflow_block(test_constants, uint8(i)):
                finished_sub_slots = blocks_5[-1].finished_sub_slots
            else:
                finished_sub_slots = []

            sp = get_signage_point(
                test_constants,
                blockchain,
                sb,
                uint128(0),
                uint8(i),
                finished_sub_slots,
                peak.sub_slot_iters,
            )
            assert store.new_signage_point(i, empty_blockchain, sb, peak.sub_slot_iters, sp)

        # Test future EOS cache
        store.initialize_genesis_sub_slot()
        blocks = bt.get_consecutive_blocks(
            1,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
        )
        await blockchain.receive_block(blocks[-1])
        while True:
            blocks = bt.get_consecutive_blocks(
                1,
                block_list_input=blocks,
                normalized_to_identity_cc_eos=normalized_to_identity,
                normalized_to_identity_icc_eos=normalized_to_identity,
                normalized_to_identity_cc_ip=normalized_to_identity,
                normalized_to_identity_cc_sp=normalized_to_identity,
            )
            await blockchain.receive_block(blocks[-1])
            sb = blockchain.block_record(blocks[-1].header_hash)
            if sb.first_in_sub_slot:
                break
        assert len(blocks) >= 2
        dependant_sub_slots = blocks[-1].finished_sub_slots
        peak = blockchain.get_peak()
        peak_full_block = await blockchain.get_full_peak()
        for block in blocks[:-2]:
            sb = blockchain.block_record(block.header_hash)
            sp_sub_slot, ip_sub_slot = await blockchain.get_sp_and_ip_sub_slots(block.header_hash)
            peak = sb
            peak_full_block = block
            res = store.new_peak(sb, block, sp_sub_slot, ip_sub_slot, False, blockchain)
            assert res[0] is None

        assert store.new_finished_sub_slot(dependant_sub_slots[0], blockchain, peak, peak_full_block) is None
        block = blocks[-2]
        sb = blockchain.block_record(block.header_hash)
        sp_sub_slot, ip_sub_slot = await blockchain.get_sp_and_ip_sub_slots(block.header_hash)
        res = store.new_peak(sb, block, sp_sub_slot, ip_sub_slot, False, blockchain)
        assert res[0] == dependant_sub_slots[0]
        assert res[1] == res[2] == []

        # Test future IP cache
        store.initialize_genesis_sub_slot()
        blocks = bt.get_consecutive_blocks(
            60,
            normalized_to_identity_cc_ip=normalized_to_identity,
            normalized_to_identity_cc_sp=normalized_to_identity,
            normalized_to_identity_cc_eos=normalized_to_identity,
            normalized_to_identity_icc_eos=normalized_to_identity,
        )

        for block in blocks[:5]:
            await blockchain.receive_block(block)
            sb = blockchain.block_record(block.header_hash)

            sp_sub_slot, ip_sub_slot = await blockchain.get_sp_and_ip_sub_slots(block.header_hash)
            res = store.new_peak(sb, block, sp_sub_slot, ip_sub_slot, False, blockchain)
            assert res[0] is None

        case_0, case_1 = False, False
        for i in range(5, len(blocks) - 1):
            prev_block = blocks[i]
            block = blocks[i + 1]
            new_ip = NewInfusionPointVDF(
                block.reward_chain_block.get_unfinished().get_hash(),
                block.reward_chain_block.challenge_chain_ip_vdf,
                block.challenge_chain_ip_proof,
                block.reward_chain_block.reward_chain_ip_vdf,
                block.reward_chain_ip_proof,
                block.reward_chain_block.infused_challenge_chain_ip_vdf,
                block.infused_challenge_chain_ip_proof,
            )
            store.add_to_future_ip(new_ip)

            await blockchain.receive_block(prev_block)
            sp_sub_slot, ip_sub_slot = await blockchain.get_sp_and_ip_sub_slots(prev_block.header_hash)
            sb = blockchain.block_record(prev_block.header_hash)
            res = store.new_peak(sb, prev_block, sp_sub_slot, ip_sub_slot, False, blockchain)
            if len(block.finished_sub_slots) == 0:
                case_0 = True
                assert res[2] == [new_ip]
            else:
                case_1 = True
                assert res[2] == []
                found_ips = []
                for ss in block.finished_sub_slots:
                    found_ips += store.new_finished_sub_slot(ss, blockchain, sb, prev_block)
                assert found_ips == [new_ip]

        # If flaky, increase the number of blocks created
        assert case_0 and case_1

    @pytest.mark.asyncio
    async def test_basic_store_compact_blockchain(self, empty_blockchain):
        await self.test_basic_store(empty_blockchain, True)

    @pytest.mark.asyncio
    async def test_long_chain_slots(self, empty_blockchain, default_1000_blocks):
        blockchain = empty_blockchain
        store = await FullNodeStore.create(test_constants)
        blocks = default_1000_blocks
        peak = None
        peak_full_block = None
        for block in blocks:
            for sub_slot in block.finished_sub_slots:
                assert store.new_finished_sub_slot(sub_slot, blockchain, peak, peak_full_block) is not None
            res, _, _ = await blockchain.receive_block(block)
            assert res == ReceiveBlockResult.NEW_PEAK
            peak = blockchain.get_peak()
            peak_full_block = await blockchain.get_full_peak()
            sp_sub_slot, ip_sub_slot = await blockchain.get_sp_and_ip_sub_slots(peak.header_hash)
            store.new_peak(peak, peak_full_block, sp_sub_slot, ip_sub_slot, False, blockchain)
