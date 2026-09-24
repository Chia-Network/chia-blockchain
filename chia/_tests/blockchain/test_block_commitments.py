from __future__ import annotations

import logging
from itertools import pairwise

import pytest
from chia_rs import FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block, _validate_and_add_block_no_error
from chia._tests.conftest import ConsensusMode
from chia._tests.core.node_height import node_height_exactly
from chia._tests.util.blockchain import create_blockchain
from chia._tests.util.setup_nodes import setup_two_nodes
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.blockchain_mmr import BlockchainMMRManager
from chia.consensus.challenge_tree import (
    compute_challenge_merkle_root,
    extract_slot_challenge_data,
    get_challenge_start_height,
)
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.get_block_challenge import get_block_challenge, pre_sp_tx_block_height
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.full_node.full_node_store import FullNodeStore
from chia.protocols import full_node_protocol
from chia.protocols.timelord_protocol import NewInfusionPointVDF
from chia.simulator.block_tools import load_block_list, make_unfinished_block, test_constants
from chia.types.peer_info import PeerInfo
from chia.util.block_cache import BlockCache
from chia.util.errors import Err

log = logging.getLogger(__name__)


class TestCommitments:
    """Tests for blocks with HARD_FORK2_HEIGHT=0 (all blocks have new commitments)"""

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_add_fork_height_zero_blocks(
        self, fork_height2_0_1000_blocks: list[FullBlock], consensus_mode: ConsensusMode
    ) -> None:
        """Test that all 1000 blocks with fork height 0 can be added to the blockchain"""
        blocks = fork_height2_0_1000_blocks
        constants = test_constants.replace(
            HARD_FORK2_HEIGHT=uint32(0),
            HARD_FORK_HEIGHT=uint32(0),
            PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
        )
        async with create_blockchain(constants, 2) as (blockchain, _):
            full_node_store = FullNodeStore(constants)
            peak = None
            peak_full_block = None
            passed_sp_or_slot = False
            saw_delayed_ses = False
            for i, block in enumerate(blocks):
                next_sub_slot_iters, next_difficulty = get_next_sub_slot_iters_and_difficulty(
                    constants, True, peak, blockchain
                )
                for sub_slot in block.finished_sub_slots:
                    assert (
                        full_node_store.new_finished_sub_slot(
                            sub_slot,
                            blockchain,
                            peak,
                            next_sub_slot_iters,
                            next_difficulty,
                            peak_full_block,
                        )
                        is not None
                    )
                if block.height in {50, 200, 499}:
                    reward_chain_block = block.reward_chain_block.replace(header_mmr_root=None)
                    block_no_mmr = block.replace(
                        reward_chain_block=reward_chain_block,
                        foliage=block.foliage.replace(reward_block_hash=reward_chain_block.get_hash()),
                    )
                    await _validate_and_add_block(blockchain, block_no_mmr, expected_error=Err.INVALID_HEADER_MMR_ROOT)
                if (
                    len(block.finished_sub_slots) > 0
                    and block.finished_sub_slots[0].challenge_chain.subepoch_summary_hash is not None
                ):
                    slot = block.finished_sub_slots[0].replace(
                        challenge_chain=block.finished_sub_slots[0].challenge_chain.replace(subepoch_summary_hash=None)
                    )
                    block_no_challenge_root = block.replace(finished_sub_slots=[slot])
                    # changing the subepoch_summary_hash will cause INVALID_POSPACE error
                    # because it changes the block challenge
                    await _validate_and_add_block(
                        blockchain, block_no_challenge_root, expected_error=Err.INVALID_POSPACE
                    )

                if i > 0 and (
                    len(block.finished_sub_slots) > 0
                    or block.reward_chain_block.signage_point_index
                    != blocks[i - 1].reward_chain_block.signage_point_index
                ):
                    passed_sp_or_slot = True
                await _validate_and_add_block_no_error(blockchain, block)
                log.info(f"Successfully added {block.height}")
                assert (not passed_sp_or_slot) or (block.reward_chain_block.header_mmr_root is not None)
                peak = blockchain.get_peak()
                assert peak is not None
                peak_full_block = block
                saw_delayed_ses = saw_delayed_ses or (
                    peak.sub_epoch_summary_included is not None and peak.height % constants.SUB_EPOCH_BLOCKS != 0
                )

            peak = blockchain.get_peak()
            assert peak is not None
            assert peak.header_hash == block.header_hash
            assert peak.height == blocks[-1].height
            assert saw_delayed_ses
            print(f"Successfully added all {len(blocks)} blocks with fork_height=0")

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_verify_fork_transition_point(
        self, fork_height2_500_1000_blocks: list[FullBlock], consensus_mode: ConsensusMode
    ) -> None:
        blocks = fork_height2_500_1000_blocks
        constants = test_constants.replace(
            HARD_FORK2_HEIGHT=uint32(500),
            HARD_FORK_HEIGHT=uint32(0),
            PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
        )

        passed_fork = False
        previous_ses_end: uint32 | None = None
        saw_pre_hf2_ses = False
        post_hf2_ses_roots = 0
        async with create_blockchain(constants, 2) as (blockchain, _):
            for _, block in enumerate(blocks):
                if not passed_fork:
                    pre_sp_tx_height = pre_sp_tx_block_height(
                        constants=constants,
                        blocks=blockchain,
                        prev_b_hash=block.prev_header_hash,
                        sp_index=block.reward_chain_block.signage_point_index,
                        finished_sub_slots=len(block.finished_sub_slots),
                    )
                    passed_fork = pre_sp_tx_height >= 500

                if passed_fork and block.height in {50, 200, 499, 550, 700}:
                    reward_chain_block = block.reward_chain_block.replace(header_mmr_root=bytes32.zeros)
                    block_no_mmr = block.replace(
                        reward_chain_block=reward_chain_block,
                        foliage=block.foliage.replace(reward_block_hash=reward_chain_block.get_hash()),
                    )
                    await _validate_and_add_block(blockchain, block_no_mmr, expected_error=Err.INVALID_HEADER_MMR_ROOT)
                if (
                    len(block.finished_sub_slots) > 0
                    and block.finished_sub_slots[0].challenge_chain.subepoch_summary_hash is not None
                ):
                    slot = block.finished_sub_slots[0].replace(
                        challenge_chain=block.finished_sub_slots[0].challenge_chain.replace(
                            subepoch_summary_hash=bytes32.zeros
                        )
                    )
                    block_no_challenge_root = block.replace(finished_sub_slots=[slot])
                    # changing the subepoch_summary_hash will cause INVALID_POSPACE error
                    # because it changes the block challenge
                    await _validate_and_add_block(
                        blockchain, block_no_challenge_root, expected_error=Err.INVALID_POSPACE
                    )
                await _validate_and_add_block_no_error(blockchain, block)
                log.info(f"Successfully added {block.height}")
                if not passed_fork:
                    assert block.reward_chain_block.header_mmr_root is None
                else:
                    assert block.reward_chain_block.header_mmr_root is not None

                peak = blockchain.get_peak()
                assert peak is not None and peak.header_hash == block.header_hash
                if peak.sub_epoch_summary_included is not None:
                    trigger = blockchain.height_to_block_record(uint32(block.height - 1))
                    range_end = get_challenge_start_height(constants, blockchain, trigger)
                    if previous_ses_end is None:
                        assert peak.sub_epoch_summary_included.challenge_merkle_root is None
                    elif peak.sub_epoch_summary_included.challenge_merkle_root is None:
                        saw_pre_hf2_ses = True
                    else:
                        assert peak.sub_epoch_summary_included.challenge_merkle_root == compute_challenge_merkle_root(
                            blockchain,
                            range_end,
                            previous_ses_end,
                        )
                        post_hf2_ses_roots += 1
                    previous_ses_end = range_end

                log.info(f"Successfully added {block.height}")

        assert saw_pre_hf2_ses
        assert post_hf2_ses_roots >= 3

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_same_sp_blocks_cross_ses_lifecycle(
        self, fork_height2_500_1000_blocks: list[FullBlock], self_hostname: str, db_version: int
    ) -> None:
        blocks = fork_height2_500_1000_blocks
        constants = test_constants.replace(
            HARD_FORK2_HEIGHT=uint32(500),
            HARD_FORK_HEIGHT=uint32(0),
            PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
        )
        _, _, block_records = load_block_list(blocks, constants)
        canonical_blocks = BlockCache(
            block_records,
            BlockchainMMRManager(constants.GENESIS_CHALLENGE),
        )
        ses_carriers = [
            block
            for block in blocks
            if len(block.finished_sub_slots) > 0
            and block.finished_sub_slots[0].challenge_chain.subepoch_summary_hash is not None
        ]

        def trigger_boundary(carrier: FullBlock) -> uint32:
            trigger = canonical_blocks.height_to_block_record(uint32(carrier.height - 1))
            return get_challenge_start_height(constants, canonical_blocks, trigger)

        def has_challenge_root(carrier: FullBlock) -> bool:
            ses = block_records[carrier.header_hash].sub_epoch_summary_included
            return ses is not None and ses.challenge_merkle_root is not None

        current_index = next(index for index, carrier in enumerate(ses_carriers) if has_challenge_root(carrier))
        previous_carrier, current_carrier, following_carrier = ses_carriers[current_index - 1 : current_index + 2]
        current_start = trigger_boundary(previous_carrier)
        current_end = trigger_boundary(current_carrier)
        following_start = current_end
        following_end = trigger_boundary(following_carrier)

        block_a, block_b = next(
            (block_a, block_b)
            for block_a, block_b in pairwise(blocks)
            if current_end <= block_a.height
            and block_b.height < current_carrier.height
            and len(block_a.finished_sub_slots) == 0
            and len(block_b.finished_sub_slots) == 0
            and not block_a.is_transaction_block()
            and not block_b.is_transaction_block()
            and block_a.reward_chain_block.signage_point_index == block_b.reward_chain_block.signage_point_index
            and block_a.total_iters < block_b.total_iters
        )
        shared_parent_hash = block_a.prev_header_hash
        unfinished_a = make_unfinished_block(block_a, constants)
        unfinished_b = make_unfinished_block(block_b, constants).replace(
            foliage=block_b.foliage.replace(prev_block_hash=shared_parent_hash)
        )
        assert unfinished_a.prev_header_hash == unfinished_b.prev_header_hash == shared_parent_hash

        def infusion_request(block: FullBlock) -> NewInfusionPointVDF:
            return NewInfusionPointVDF(
                block.reward_chain_block.get_unfinished().get_hash(),
                block.reward_chain_block.challenge_chain_ip_vdf,
                block.challenge_chain_ip_proof,
                block.reward_chain_block.reward_chain_ip_vdf,
                block.reward_chain_ip_proof,
                block.reward_chain_block.infused_challenge_chain_ip_vdf,
                block.infused_challenge_chain_ip_proof,
            )

        current_root = compute_challenge_merkle_root(canonical_blocks, current_end, current_start)
        following_root = compute_challenge_merkle_root(canonical_blocks, following_end, following_start)
        prospective_end = get_challenge_start_height(
            constants,
            canonical_blocks,
            canonical_blocks.block_record(unfinished_a.prev_header_hash),
            unfinished_a.reward_chain_block.pos_ss_cc_challenge_hash,
        )
        prospective_root = compute_challenge_merkle_root(canonical_blocks, prospective_end, current_start)
        assert current_start < prospective_end == current_end
        assert not (current_start <= block_a.height < current_end)
        assert not (current_start <= block_b.height < current_end)
        assert following_start <= block_a.height < following_end
        assert following_start <= block_b.height < following_end
        block_a_challenge = get_block_challenge(
            constants,
            block_a,
            canonical_blocks,
            False,
            block_records[block_a.header_hash].overflow,
            False,
        )
        block_b_challenge = get_block_challenge(
            constants,
            block_b,
            canonical_blocks,
            False,
            block_records[block_b.header_hash].overflow,
            False,
        )
        assert block_a_challenge == block_b_challenge
        current_slots = extract_slot_challenge_data(canonical_blocks, current_start, current_end)
        following_slots = extract_slot_challenge_data(canonical_blocks, following_start, following_end)
        assert all(slot.challenge_hash != block_a_challenge for slot in current_slots)
        matching_slots = [slot for slot in following_slots if slot.challenge_hash == block_a_challenge]
        assert len(matching_slots) == 1
        challenge_block_count = sum(
            get_block_challenge(
                constants,
                blocks[height],
                canonical_blocks,
                height == 0,
                block_records[blocks[height].header_hash].overflow,
                False,
            )
            == block_a_challenge
            for height in range(following_start, following_end)
        )
        assert matching_slots[0].block_count == challenge_block_count

        async with setup_two_nodes(constants, db_version, self_hostname) as (
            full_node_1,
            full_node_2,
            _,
            _,
            _,
        ):
            nodes = [full_node_1.full_node, full_node_2.full_node]
            for block in blocks[: int(block_a.height)]:
                for node in nodes:
                    await node.add_block(block)

            for node, unfinished_blocks in zip(nodes, ([unfinished_a, unfinished_b], [unfinished_b, unfinished_a])):
                for unfinished_block in unfinished_blocks:
                    await node.add_unfinished_block(unfinished_block, None)
                assert node.full_node_store.get_unfinished_block(unfinished_a.partial_hash) == unfinished_a
                assert node.full_node_store.get_unfinished_block(unfinished_b.partial_hash) == unfinished_b

                prospective_a = next_sub_epoch_summary(
                    constants,
                    node.blockchain,
                    block_records[block_a.header_hash].required_iters,
                    unfinished_a,
                    can_finish_soon=True,
                    with_challenge_root=True,
                )
                prospective_b = next_sub_epoch_summary(
                    constants,
                    node.blockchain,
                    block_records[block_b.header_hash].required_iters,
                    unfinished_b,
                    can_finish_soon=True,
                    with_challenge_root=True,
                )
                assert prospective_a is not None
                assert prospective_b is not None
                assert prospective_a.challenge_merkle_root == prospective_b.challenge_merkle_root == prospective_root

            for block, request in (
                (block_a, infusion_request(block_a)),
                (block_b, infusion_request(block_b)),
            ):
                for node in nodes:
                    await node.new_infusion_point_vdf(request)
                    peak = await node.blockchain.get_full_peak()
                    assert peak is not None
                    assert peak.header_hash == block.header_hash
                    if block is block_b:
                        assert peak.prev_header_hash == block_a.header_hash

            for block in blocks[int(block_b.height) + 1 : int(following_carrier.height) + 1]:
                for node in nodes:
                    await node.add_block(block)
                if block.height in {current_carrier.height, following_carrier.height}:
                    expected_root = current_root if block.height == current_carrier.height else following_root
                    for node in nodes:
                        block_record = node.blockchain.block_record(block.header_hash)
                        assert block_record.sub_epoch_summary_included is not None
                        assert block_record.sub_epoch_summary_included.challenge_merkle_root == expected_root


class TestSyncWithCommitments:
    """Tests for syncing blocks with different fork heights between nodes"""

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_sync_fork_height_zero_blocks(
        self, fork_height2_0_1000_blocks: list[FullBlock], self_hostname: str, db_version: int
    ) -> None:
        """Test syncing 1000 blocks with fork height 0 between two nodes"""
        blocks = fork_height2_0_1000_blocks
        constants = test_constants.replace(
            HARD_FORK2_HEIGHT=uint32(0),
            HARD_FORK_HEIGHT=uint32(0),
            PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
        )

        async with setup_two_nodes(constants, db_version, self_hostname) as (
            full_node_1,
            full_node_2,
            server_1,
            server_2,
            _,
        ):
            # Add all blocks to node 1
            for block in blocks:
                await full_node_1.full_node.add_block(block)

            res = await full_node_1.request_proof_of_weight(
                full_node_protocol.RequestProofOfWeight(uint32(blocks[-1].height), blocks[-1].header_hash)
            )
            assert res is not None
            assert full_node_2.full_node.weight_proof_handler is not None
            validated, _, _ = await full_node_2.full_node.weight_proof_handler.validate_weight_proof(
                full_node_protocol.RespondProofOfWeight.from_bytes(res.data).wp
            )
            assert validated is True
            # Connect node 2 to node 1
            await server_2.start_client(
                PeerInfo(self_hostname, server_1.get_port()),
                on_connect=full_node_2.full_node.on_connect,
            )

            # Node 2 should sync all blocks from node 1
            await time_out_assert(300, node_height_exactly, True, full_node_1, len(blocks) - 1)
            await time_out_assert(300, node_height_exactly, True, full_node_2, len(blocks) - 1)

            # Verify both nodes have same peak
            peak_1 = full_node_1.full_node.blockchain.get_peak()
            peak_2 = full_node_2.full_node.blockchain.get_peak()
            assert peak_1 is not None and peak_2 is not None
            assert peak_1.header_hash == peak_2.header_hash
            log.info(f"Successfully synced {len(blocks)} blocks with fork_height=0 between two nodes")

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_sync_fork_height_500_blocks(
        self, fork_height2_500_1000_blocks: list[FullBlock], self_hostname: str, db_version: int
    ) -> None:
        """Test syncing 1000 blocks with fork height 500 between two nodes"""
        blocks = fork_height2_500_1000_blocks
        constants = test_constants.replace(
            HARD_FORK2_HEIGHT=uint32(500),
            HARD_FORK_HEIGHT=uint32(0),
            PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
        )

        async with setup_two_nodes(constants, db_version, self_hostname) as (
            full_node_1,
            full_node_2,
            server_1,
            server_2,
            _,
        ):
            # Add all blocks to node 1
            for block in blocks:
                await full_node_1.full_node.add_block(block)
                log.info(f"Successfully added {block.height}")

            # Connect node 2 to node 1
            await server_2.start_client(
                PeerInfo(self_hostname, server_1.get_port()),
                on_connect=full_node_2.full_node.on_connect,
            )

            # Node 2 should sync all blocks from node 1
            await time_out_assert(300, node_height_exactly, True, full_node_1, len(blocks) - 1)
            await time_out_assert(300, node_height_exactly, True, full_node_2, len(blocks) - 1)

            # Verify both nodes have same peak
            peak_1 = full_node_1.full_node.blockchain.get_peak()
            peak_2 = full_node_2.full_node.blockchain.get_peak()
            assert peak_1 is not None and peak_2 is not None
            assert peak_1.header_hash == peak_2.header_hash

            log.info(f"Successfully synced {len(blocks)} blocks with fork_height=500 between two nodes")


def test_mmr_manager_deep_copy() -> None:
    # Create original MMR manager
    mmr1 = BlockchainMMRManager(test_constants.GENESIS_CHALLENGE)

    # Add some blocks to it
    mmr1.add_block_to_mmr(bytes32([1] * 32), bytes32([0] * 32), uint32(0))
    mmr1.add_block_to_mmr(bytes32([2] * 32), bytes32([1] * 32), uint32(1))
    mmr1.add_block_to_mmr(bytes32([3] * 32), bytes32([2] * 32), uint32(2))

    original_height = mmr1._last_height
    original_root = mmr1.compute_current_mmr_root()

    # Create a copy
    mmr2 = mmr1.copy()

    # Verify initial state matches
    assert mmr2._last_height == original_height
    assert mmr2.compute_current_mmr_root() == original_root

    # Mutate the copy
    mmr2.add_block_to_mmr(bytes32([4] * 32), bytes32([3] * 32), uint32(3))
    mmr2.add_block_to_mmr(bytes32([5] * 32), bytes32([4] * 32), uint32(4))

    # Verify original is unchanged (deep copy worked)
    assert mmr1._last_height == original_height
    assert mmr1.compute_current_mmr_root() == original_root

    # Verify copy has new state
    assert mmr2._last_height == uint32(4)
    assert mmr2.compute_current_mmr_root() != original_root

    # Verify they are truly independent objects
    assert mmr1._mmr is not mmr2._mmr
