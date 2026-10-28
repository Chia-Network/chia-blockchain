from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from itertools import pairwise
from pathlib import Path

import pytest
from chia_rs import (
    BlockRecord,
    ConsensusConstants,
    FullBlock,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block, _validate_and_add_block_no_error
from chia._tests.conftest import ConsensusMode
from chia._tests.core.node_height import node_height_exactly
from chia._tests.util.blockchain import create_blockchain
from chia._tests.util.setup_nodes import setup_two_nodes
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.block_creation import unfinished_block_to_full_block_with_mmr
from chia.consensus.block_generator_info import block_has_transactions_generator
from chia.consensus.block_height_map import BlockHeightMap
from chia.consensus.blockchain import AddBlockResult, Blockchain
from chia.consensus.blockchain_mmr import BlockchainMMRManager
from chia.consensus.challenge_tree import (
    compute_challenge_merkle_root,
    extract_slot_challenge_data,
    get_challenge_start_height,
)
from chia.consensus.coin_commitments import EMPTY_MERKLE_SET_ROOT, compute_mmr_leaf
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.get_block_challenge import get_block_challenge, pre_sp_tx_block_height
from chia.consensus.make_sub_epoch_summary import next_sub_epoch_summary
from chia.consensus.mmr import MerkleMountainRange
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.full_node_store import FullNodeStore
from chia.full_node.mmr_store import MMRStore
from chia.protocols import full_node_protocol
from chia.protocols.outbound_message import Message, NodeType
from chia.protocols.timelord_protocol import NewInfusionPointVDF, NewUnfinishedBlockTimelord
from chia.simulator.add_blocks_in_batches import add_blocks_in_batches
from chia.simulator.block_tools import (
    BlockTools,
    create_block_tools_async,
    load_block_list,
    make_unfinished_block,
    test_constants,
)
from chia.types.blockchain_format.coin import Coin
from chia.types.peer_info import PeerInfo
from chia.types.validation_state import ValidationState
from chia.util.block_cache import BlockCache
from chia.util.db_wrapper import DBWrapper2, generate_in_memory_db_uri
from chia.util.errors import Err
from chia.util.inline_executor import InlineExecutor
from chia.util.keychain import Keychain

log = logging.getLogger(__name__)


def _registered_mmr_manager(
    blocks: list[FullBlock], genesis_challenge: bytes32, aggregate_from: uint32
) -> BlockchainMMRManager:
    """
    An MMR manager with every block's coin commitment registered, so it can
    serve as a root oracle over `blocks` (composite leaves need the
    commitment; the header hash alone is not a leaf). These fixture chains
    carry no transaction generators, so every commitment is the empty root.
    """
    mmr_manager = BlockchainMMRManager(genesis_challenge, aggregate_from=aggregate_from)
    for block in blocks:
        assert not block_has_transactions_generator(block)
        mmr_manager.register_block_commitment(block.header_hash, EMPTY_MERKLE_SET_ROOT)
    return mmr_manager


def _late_parent_candidate(
    blocks: list[FullBlock],
    block_records: dict[bytes32, BlockRecord],
    block_cache: BlockCache,
    constants: ConsensusConstants,
    *,
    minimum_height: uint32,
    minimum_signage_point_index: uint8 = uint8(0),
) -> FullBlock:
    candidate = next(
        (
            block
            for block in blocks[2:]
            if block.height >= minimum_height
            if block.reward_chain_block.signage_point_index >= minimum_signage_point_index
            if block.reward_chain_block.header_mmr_root is not None
            if block_cache.get_mmr_root_for_block(
                block.prev_header_hash,
                block_records[block.header_hash].sp_total_iters(constants),
            )
            != block_cache.get_mmr_root_for_block(
                block_records[block.prev_header_hash].prev_hash,
                block_records[block.header_hash].sp_total_iters(constants),
            )
        ),
        None,
    )
    assert candidate is not None, "generated chain has no post-HF2 stale-parent MMR cutoff"
    return candidate


def _infusion_request(block: FullBlock) -> NewInfusionPointVDF:
    return NewInfusionPointVDF(
        block.reward_chain_block.get_unfinished().get_hash(),
        block.reward_chain_block.challenge_chain_ip_vdf,
        block.challenge_chain_ip_proof,
        block.reward_chain_block.reward_chain_ip_vdf,
        block.reward_chain_ip_proof,
        block.reward_chain_block.infused_challenge_chain_ip_vdf,
        block.infused_challenge_chain_ip_proof,
    )


class TestCommitments:
    """Tests for blocks with HARD_FORK2_HEIGHT=0 (all blocks have new commitments)"""

    @pytest.mark.anyio
    async def test_add_fork_height_zero_blocks(self, fork_height2_0_1000_blocks: list[FullBlock]) -> None:
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
            saw_delayed_ses = False
            for block in blocks:
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

                await _validate_and_add_block_no_error(blockchain, block)
                log.info(f"Successfully added {block.height}")
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
    async def test_verify_fork_transition_point(self, fork_height2_500_1000_blocks: list[FullBlock]) -> None:
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
    async def test_timelord_mmr_omitted_before_fork_activation(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        self_hostname: str,
        db_version: int,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        blocks = fork_height2_500_1000_blocks
        constants = test_constants.replace(
            HARD_FORK2_HEIGHT=uint32(501),
            HARD_FORK_HEIGHT=uint32(0),
            PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
        )
        chain_constants = constants.replace(HARD_FORK2_HEIGHT=uint32(500))
        _, _, block_records = load_block_list(blocks, chain_constants)
        block_cache = BlockCache(
            block_records,
            _registered_mmr_manager(blocks, constants.GENESIS_CHALLENGE, constants.HARD_FORK2_HEIGHT),
        )
        candidate = next(
            (
                block
                for block in blocks
                if block.height >= constants.HARD_FORK2_HEIGHT
                if pre_sp_tx_block_height(
                    constants=constants,
                    blocks=block_cache,
                    prev_b_hash=block.prev_header_hash,
                    sp_index=block.reward_chain_block.signage_point_index,
                    finished_sub_slots=len(block.finished_sub_slots),
                )
                < constants.HARD_FORK2_HEIGHT
                if block_cache.get_mmr_root_for_block(
                    block.prev_header_hash,
                    block_records[block.header_hash].sp_total_iters(constants),
                )
                is not None
            ),
            None,
        )
        assert candidate is not None, (
            "generated chain has no delayed HF2 activation candidate with an available MMR root"
        )
        unfinished = make_unfinished_block(candidate, constants).replace(version=uint8(0))

        async with setup_two_nodes(constants, db_version, self_hostname) as (full_node, _, _, _, _):
            for block in blocks[: int(candidate.height)]:
                await full_node.full_node.add_block(block)

            assert (
                pre_sp_tx_block_height(
                    constants=constants,
                    blocks=full_node.full_node.blockchain,
                    prev_b_hash=candidate.prev_header_hash,
                    sp_index=candidate.reward_chain_block.signage_point_index,
                    finished_sub_slots=len(candidate.finished_sub_slots),
                )
                < constants.HARD_FORK2_HEIGHT
            )

            timelord_requests: list[NewUnfinishedBlockTimelord] = []

            async def capture_timelord_request(
                messages: list[Message],
                node_type: NodeType,
                *_args: object,
            ) -> None:
                if node_type == NodeType.TIMELORD:
                    timelord_requests.extend(
                        NewUnfinishedBlockTimelord.from_bytes(message.data) for message in messages
                    )

            monkeypatch.setattr(full_node.full_node.server, "send_to_all", capture_timelord_request)
            await full_node.full_node.add_unfinished_block(unfinished, None)

        assert len(timelord_requests) == 1
        assert timelord_requests[0].header_mmr_root is None

    @pytest.mark.anyio
    async def test_same_sp_competing_blocks_preserve_ses_challenge_root(
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
                (block_a, _infusion_request(block_a)),
                (block_b, _infusion_request(block_b)),
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
    async def test_sync_chain_with_stale_unfinished_parent(
        self,
        default_1000_blocks: list[FullBlock],
        self_hostname: str,
        db_version: int,
        consensus_mode: ConsensusMode,
    ) -> None:
        constants = test_constants.replace(
            HARD_FORK2_HEIGHT=uint32(default_1000_blocks[-1].height + 1),
            HARD_FORK_HEIGHT=uint32(0),
            PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
        )
        async with setup_two_nodes(constants, db_version, self_hostname) as (
            full_node_1,
            full_node_2,
            server_1,
            server_2,
            block_tools,
        ):
            blocks = block_tools.get_consecutive_blocks(
                200,
                block_list_input=default_1000_blocks,
                seed=b"late-parent-sync",
            )
            _, _, block_records = load_block_list(blocks, constants)
            candidate_blocks = BlockCache(
                block_records,
                _registered_mmr_manager(blocks, constants.GENESIS_CHALLENGE, constants.HARD_FORK2_HEIGHT),
            )
            candidate = _late_parent_candidate(
                blocks,
                block_records,
                candidate_blocks,
                constants,
                minimum_height=uint32(constants.HARD_FORK2_HEIGHT + 20),
            )
            candidate_record = block_records[candidate.header_hash]
            parent = block_records[candidate.prev_header_hash]
            grandparent = blocks[int(candidate.height) - 2]
            unfinished = make_unfinished_block(candidate, constants).replace(
                foliage=candidate.foliage.replace(prev_block_hash=grandparent.header_hash)
            )

            race_block = unfinished_block_to_full_block_with_mmr(
                unfinished,
                candidate.reward_chain_block.challenge_chain_ip_vdf,
                candidate.challenge_chain_ip_proof,
                candidate.reward_chain_block.reward_chain_ip_vdf,
                candidate.reward_chain_ip_proof,
                candidate.reward_chain_block.infused_challenge_chain_ip_vdf,
                candidate.infused_challenge_chain_ip_proof,
                candidate.finished_sub_slots,
                parent,
                candidate_blocks,
                candidate_record.sp_total_iters(constants),
                uint64(candidate.weight - parent.weight),
                constants,
            )
            blocks = [*blocks[: int(candidate.height)], race_block]
            await add_blocks_in_batches(blocks, full_node_1.full_node)
            await server_2.start_client(
                PeerInfo(self_hostname, server_1.get_port()),
                on_connect=full_node_2.full_node.on_connect,
            )

            await time_out_assert(300, node_height_exactly, True, full_node_2, int(candidate.height))
            assert full_node_2.full_node.blockchain.get_peak() == full_node_1.full_node.blockchain.get_peak()

    @pytest.mark.anyio
    async def test_sync_fork_height_zero_blocks(
        self,
        fork_height2_0_1000_blocks: list[FullBlock],
        self_hostname: str,
        db_version: int,
    ) -> None:
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
            await server_2.start_client(
                PeerInfo(self_hostname, server_1.get_port()),
                on_connect=full_node_2.full_node.on_connect,
            )

            await time_out_assert(300, node_height_exactly, True, full_node_1, len(blocks) - 1)
            await time_out_assert(300, node_height_exactly, True, full_node_2, len(blocks) - 1)

            peak_1 = full_node_1.full_node.blockchain.get_peak()
            peak_2 = full_node_2.full_node.blockchain.get_peak()
            assert peak_1 is not None and peak_2 is not None
            assert peak_1.header_hash == peak_2.header_hash
            log.info(f"Successfully synced {len(blocks)} blocks with fork_height=0 between two nodes")

    @pytest.mark.anyio
    async def test_sync_fork_height_500_blocks(
        self,
        fork_height2_500_1000_blocks: list[FullBlock],
        self_hostname: str,
        db_version: int,
    ) -> None:
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
            for block in blocks:
                await full_node_1.full_node.add_block(block)

            await server_2.start_client(
                PeerInfo(self_hostname, server_1.get_port()),
                on_connect=full_node_2.full_node.on_connect,
            )

            await time_out_assert(300, node_height_exactly, True, full_node_1, len(blocks) - 1)
            await time_out_assert(300, node_height_exactly, True, full_node_2, len(blocks) - 1)

            peak_1 = full_node_1.full_node.blockchain.get_peak()
            peak_2 = full_node_2.full_node.blockchain.get_peak()
            assert peak_1 is not None and peak_2 is not None
            assert peak_1.header_hash == peak_2.header_hash
            log.info(f"Successfully synced {len(blocks)} blocks with fork_height=500 between two nodes")

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_canonical_block_between_fork_batches(
        self, hf2_bt: BlockTools, self_hostname: str, db_version: int, consensus_mode: ConsensusMode
    ) -> None:
        """
        short_sync_batch keeps one ForkInfo across batches but releases the
        chain lock between them, so a canonical block from another peer can
        commit in between and drop the fork's pending leaves. The next batch
        skips the fork blocks it already ran and must restore their leaves
        for its header MMR checks and for the reorg that appends them.
        """
        bt = hf2_bt
        canonical = bt.get_consecutive_blocks(32)
        fork = bt.get_consecutive_blocks(25, block_list_input=canonical[:10], seed=b"fork-between-batches")
        assert fork[14].weight < canonical[30].weight
        assert fork[-1].weight > canonical[31].weight

        async with setup_two_nodes(bt.constants, db_version, self_hostname) as (full_node_1, _, _, _, _):
            node = full_node_1.full_node
            await add_blocks_in_batches(canonical[:31], node)

            fork_info = ForkInfo(9, 9, canonical[9].header_hash)
            blockchain = AugmentedBlockchain(node.blockchain)
            vs = ValidationState(bt.constants.SUB_SLOT_ITERS_STARTING, bt.constants.DIFFICULTY_STARTING, None)
            peer_info = PeerInfo(self_hostname, 0)
            success, _ = await node.add_block_batch(fork[10:15], peer_info, fork_info, vs, blockchain)
            assert success
            assert node.blockchain.mmr_manager.has_block_leaf(fork[10].header_hash)

            # another peer's canonical block commits between the batches
            await node.add_block(canonical[31])
            assert not node.blockchain.mmr_manager.has_block_leaf(fork[10].header_hash)

            # the next batch overlaps the previous one (short_sync_batch's
            # ranges repeat the last block) and overtakes the canonical chain
            success, _ = await node.add_block_batch(fork[14:], peer_info, fork_info, vs, blockchain)
            assert success
            peak = node.blockchain.get_peak()
            assert peak is not None and peak.header_hash == fork[-1].header_hash
            assert node.blockchain.mmr_manager.compute_current_mmr_root() == await _expected_canonical_mmr_root(
                node.blockchain
            )

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_fork_prefix_replayed_between_fork_batches(
        self, hf2_bt: BlockTools, self_hostname: str, db_version: int, consensus_mode: ConsensusMode
    ) -> None:
        """
        After a canonical commit drops the fork's pending leaves, a block
        building on a mid-branch fork block replays only that branch prefix.
        The next batch must still restore the leaves of the rest of the branch.
        """
        bt = hf2_bt
        canonical = bt.get_consecutive_blocks(32)
        fork = bt.get_consecutive_blocks(25, block_list_input=canonical[:10], seed=b"fork-between-batches")
        assert fork[14].weight < canonical[30].weight
        assert fork[-1].weight > canonical[31].weight
        sibling = bt.get_consecutive_blocks(1, block_list_input=fork[:12], seed=b"fork-sibling")[-1]
        assert sibling.prev_header_hash == fork[11].header_hash
        assert sibling.header_hash != fork[12].header_hash

        async with setup_two_nodes(bt.constants, db_version, self_hostname) as (full_node_1, _, _, _, _):
            node = full_node_1.full_node
            await add_blocks_in_batches(canonical[:31], node)

            fork_info = ForkInfo(9, 9, canonical[9].header_hash)
            blockchain = AugmentedBlockchain(node.blockchain)
            vs = ValidationState(bt.constants.SUB_SLOT_ITERS_STARTING, bt.constants.DIFFICULTY_STARTING, None)
            peer_info = PeerInfo(self_hostname, 0)
            success, _ = await node.add_block_batch(fork[10:15], peer_info, fork_info, vs, blockchain)
            assert success

            # another peer's canonical block commits between the batches
            await node.add_block(canonical[31])
            assert not node.blockchain.mmr_manager.has_block_leaf(fork[10].header_hash)

            # a gossiped child of fork[11] replays fork[10..11] only
            await node.add_block(sibling)
            assert not node.blockchain.contains_block(sibling.header_hash, sibling.height)
            assert await node.blockchain.get_block_record_from_db(sibling.header_hash) is not None
            assert node.blockchain.mmr_manager.has_block_leaf(fork[10].header_hash)
            assert not node.blockchain.mmr_manager.has_block_leaf(fork[13].header_hash)

            success, _ = await node.add_block_batch(fork[14:], peer_info, fork_info, vs, blockchain)
            assert success
            peak = node.blockchain.get_peak()
            assert peak is not None and peak.header_hash == fork[-1].header_hash
            assert node.blockchain.mmr_manager.compute_current_mmr_root() == await _expected_canonical_mmr_root(
                node.blockchain
            )


def test_mmr_manager_deep_copy() -> None:
    # Create original MMR manager
    mmr1 = BlockchainMMRManager(test_constants.GENESIS_CHALLENGE)

    # Add some blocks to it
    for height in range(3):
        block_hash = bytes32([height + 1] * 32)
        mmr1.register_block_commitment(block_hash, EMPTY_MERKLE_SET_ROOT)
        mmr1.add_block_to_mmr(block_hash, bytes32([height] * 32), uint32(height))

    original_height = mmr1._last_height
    original_root = mmr1.compute_current_mmr_root()

    # Create a copy
    mmr2 = mmr1.copy()

    # Verify initial state matches
    assert mmr2._last_height == original_height
    assert mmr2.compute_current_mmr_root() == original_root

    # Mutate the copy
    for height in range(3, 5):
        block_hash = bytes32([height + 1] * 32)
        mmr2.register_block_commitment(block_hash, EMPTY_MERKLE_SET_ROOT)
        mmr2.add_block_to_mmr(block_hash, bytes32([height] * 32), uint32(height))

    # Verify original is unchanged (deep copy worked)
    assert mmr1._last_height == original_height
    assert mmr1.compute_current_mmr_root() == original_root

    # Verify copy has new state
    assert mmr2._last_height == uint32(4)
    assert mmr2.compute_current_mmr_root() != original_root

    # Verify they are truly independent objects
    assert mmr1._mmr is not mmr2._mmr


HF2_CONSTANTS = test_constants.replace(
    HARD_FORK2_HEIGHT=uint32(0),
    HARD_FORK_HEIGHT=uint32(0),
    PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
)


@pytest.fixture(scope="module")
async def hf2_bt(get_keychain: Keychain, anyio_backend: str, testrun_uid: str) -> AsyncIterator[BlockTools]:
    async with create_block_tools_async(constants=HF2_CONSTANTS, keychain=get_keychain, testrun_uid=testrun_uid) as bt:
        yield bt


async def _open_blockchain(constants: ConsensusConstants, db_wrapper: DBWrapper2, blockchain_dir: Path) -> Blockchain:
    coin_store = await CoinStore.create(db_wrapper)
    block_store = await BlockStore.create(db_wrapper)
    mmr_store = await MMRStore.create(db_wrapper)
    height_map = await BlockHeightMap.create(blockchain_dir, db_wrapper)
    return await Blockchain.create(
        coin_store, block_store, height_map, constants, InlineExecutor(), mmr_store=mmr_store
    )


async def _expected_canonical_mmr_root(blockchain: Blockchain) -> bytes32 | None:
    """
    Hand-built MMR over the composite leaves of every canonical block, with
    each coin commitments root reconstructed from the coin store. Comparing
    this against the live MMR root checks both the conds-derived roots
    registered during validation and their agreement with coin-store
    reconstruction.
    """
    mmr = MerkleMountainRange()
    peak = blockchain.get_peak()
    assert peak is not None
    aggregate_from = blockchain.mmr_manager.get_aggrtegate_from()
    for height in range(int(aggregate_from), peak.height + 1):
        header_hash = blockchain.height_to_hash(uint32(height))
        assert header_hash is not None
        coin_commitments_root = await blockchain.coin_store.get_coin_commitments_root(uint32(height))
        mmr.append(compute_mmr_leaf(header_hash, coin_commitments_root))
    return mmr.compute_root()


def _spendable_reward_coins(blocks: list[FullBlock], reward_ph: bytes32) -> list[Coin]:
    coins: list[Coin] = []
    for block in blocks:
        for coin in block.get_included_reward_coins():
            if coin.puzzle_hash == reward_ph:
                coins.append(coin)
    return coins


class TestMMRPersistence:
    """Tests for MMR persistence (Milestone 1B): startup loading, reorg truncation, recovery."""

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_corrupt_node_count_fails_closed(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        bt = hf2_bt
        blocks = bt.get_consecutive_blocks(8, guarantee_transaction_block=True)

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks:
                await _validate_and_add_block(blockchain, block)
            blockchain.shut_down()

            # corrupt the flat node array so its count no longer matches leaf_count
            async with db_wrapper.writer() as conn:
                await conn.execute("DELETE FROM mmr_nodes WHERE position = (SELECT MAX(position) FROM mmr_nodes)")

            # the corruption is detected and startup fails closed
            with pytest.raises(RuntimeError, match="node count"):
                await _open_blockchain(bt.constants, db_wrapper, tmp_path / "second")

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_corrupt_leaf_count_fails_closed(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        bt = hf2_bt
        blocks = bt.get_consecutive_blocks(8, guarantee_transaction_block=True)

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks:
                await _validate_and_add_block(blockchain, block)
            blockchain.shut_down()

            # corrupt the singleton metadata: the leaf count no longer matches the peak
            async with db_wrapper.writer() as conn:
                await conn.execute("UPDATE mmr_state SET leaf_count = leaf_count + 1")

            with pytest.raises(RuntimeError, match="leaf count"):
                await _open_blockchain(bt.constants, db_wrapper, tmp_path / "second")

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_corrupt_peak_hash_fails_closed(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        bt = hf2_bt
        blocks = bt.get_consecutive_blocks(8, guarantee_transaction_block=True)

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks:
                await _validate_and_add_block(blockchain, block)
            blockchain.shut_down()

            # corrupt the singleton metadata: the recorded peak hash is wrong for
            # the recorded peak height
            async with db_wrapper.writer() as conn:
                await conn.execute("UPDATE mmr_state SET canonical_header_hash = ?", (bytes32(b"\x01" * 32),))

            with pytest.raises(RuntimeError, match="peak hash"):
                await _open_blockchain(bt.constants, db_wrapper, tmp_path / "second")

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_mismatched_aggregate_from_fails_closed(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        bt = hf2_bt
        blocks = bt.get_consecutive_blocks(8, guarantee_transaction_block=True)

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks:
                await _validate_and_add_block(blockchain, block)
            blockchain.shut_down()

            # the persisted MMR starts aggregating at HF2=0; reopening the same
            # database under a different HF2 height must not reuse it
            with pytest.raises(RuntimeError, match="aggregate_from"):
                await _open_blockchain(
                    bt.constants.replace(HARD_FORK2_HEIGHT=uint32(4)), db_wrapper, tmp_path / "second"
                )

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_rescheduled_future_aggregate_from_rebuilds_empty_mmr(
        self, bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        blocks = bt.get_consecutive_blocks(3)
        scheduled = bt.constants.replace(HARD_FORK2_HEIGHT=uint32(1000))
        rescheduled = bt.constants.replace(HARD_FORK2_HEIGHT=uint32(2000))

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(scheduled, db_wrapper, tmp_path / "first")
            for block in blocks:
                await _validate_and_add_block(blockchain, block)
            assert blockchain.mmr_manager.compute_current_mmr_root() is None
            blockchain.shut_down()

            # the peak predates both activation heights and the persisted MMR
            # is empty: moving the future activation invalidates nothing, so
            # the empty MMR is rebuilt under the new height
            blockchain = await _open_blockchain(rescheduled, db_wrapper, tmp_path / "second")
            peak = blockchain.get_peak()
            assert peak is not None and peak.header_hash == blocks[-1].header_hash
            assert blockchain.mmr_store is not None
            state = await blockchain.mmr_store.get_state()
            assert state is not None and state.aggregate_from == rescheduled.HARD_FORK2_HEIGHT
            blockchain.shut_down()

            # the rewritten state loads directly
            blockchain = await _open_blockchain(rescheduled, db_wrapper, tmp_path / "third")
            peak = blockchain.get_peak()
            assert peak is not None and peak.header_hash == blocks[-1].header_hash
            blockchain.shut_down()


class TestStoredForkReplay:
    """Tests for replaying a stored fork branch before validating its child."""

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_prepare_stored_fork_with_a_different_genesis(
        self, bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        canonical = bt.get_consecutive_blocks(3)
        fork = bt.get_consecutive_blocks(2, seed=b"foreign-genesis")
        assert fork[0].header_hash != canonical[0].header_hash

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "chain")
            for block in canonical:
                await _validate_and_add_block(blockchain, block)
            await _validate_and_add_block(blockchain, fork[0], expected_result=AddBlockResult.ADDED_AS_ORPHAN)

            # the stored branch shares no block with the canonical chain, so it
            # is replayed from its own genesis
            fork_info = await blockchain.prepare_stored_fork_ancestry(fork[1])
            assert fork_info is not None
            assert fork_info.fork_height == -1
            assert fork_info.peak_height == 0 and fork_info.peak_hash == fork[0].header_hash
            await _validate_and_add_block(
                blockchain, fork[1], expected_result=AddBlockResult.ADDED_AS_ORPHAN, fork_info=fork_info
            )
            blockchain.shut_down()
