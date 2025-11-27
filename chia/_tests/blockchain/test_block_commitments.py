from __future__ import annotations

import logging

import pytest
from chia_rs import FullBlock
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia._tests.blockchain.blockchain_test_utils import _validate_and_add_block, _validate_and_add_block_no_error
from chia._tests.conftest import ConsensusMode
from chia._tests.core.node_height import node_height_exactly
from chia._tests.simulation.test_simulation import test_constants
from chia._tests.util.blockchain import create_blockchain
from chia._tests.util.setup_nodes import setup_two_nodes
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.get_block_challenge import pre_sp_tx_block_height
from chia.protocols import full_node_protocol
from chia.types.peer_info import PeerInfo
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
            HARD_FORK_HEIGHT=uint32(2),
            PLOT_FILTER_128_HEIGHT=uint32(10),
            PLOT_FILTER_64_HEIGHT=uint32(15),
            PLOT_FILTER_32_HEIGHT=uint32(20),
        )
        passed_sp_or_slot = False
        async with create_blockchain(constants, 2) as (blockchain, _):
            for i, block in enumerate(blocks):
                if block.height in {50, 200, 499}:
                    block_no_mmr = block.replace(
                        reward_chain_block=block.reward_chain_block.replace(header_mmr_root=None)
                    )
                    await _validate_and_add_block(
                        blockchain, block_no_mmr, expected_error=Err.INVALID_REWARD_BLOCK_HASH
                    )
                if (
                    len(block.finished_sub_slots) > 0
                    and block.finished_sub_slots[0].challenge_chain.subepoch_summary_hash is not None
                ):
                    slot = block.finished_sub_slots[0].replace(
                        challenge_chain=block.finished_sub_slots[0].challenge_chain.replace(subepoch_summary_hash=None)
                    )
                    block_no_challenge_root = block.replace(finished_sub_slots=([slot]))
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
            assert peak.header_hash == block.header_hash
            assert peak.height == blocks[-1].height
            print(f"Successfully added all {len(blocks)} blocks with fork_height=0")

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_verify_fork_transition_point(
        self, fork_height2_500_1000_blocks: list[FullBlock], consensus_mode: ConsensusMode
    ) -> None:
        blocks = fork_height2_500_1000_blocks
        constants = test_constants.replace(
            HARD_FORK2_HEIGHT=uint32(500),
            HARD_FORK_HEIGHT=uint32(2),
            PLOT_FILTER_128_HEIGHT=uint32(10),
            PLOT_FILTER_64_HEIGHT=uint32(15),
            PLOT_FILTER_32_HEIGHT=uint32(20),
        )

        passed_fork = False
        async with create_blockchain(constants, 2) as (blockchain, _):
            for _, block in enumerate(blocks):
                if not passed_fork:
                    pre_sp_tx_height = pre_sp_tx_block_height(
                        constants=constants,
                        blocks=blockchain,
                        prev_b_hash=block.prev_header_hash,
                        sp_index=block.reward_chain_block.signage_point_index,
                        first_in_sub_slot=len(block.finished_sub_slots) > 0,
                    )
                    passed_fork = pre_sp_tx_height >= 500

                if block.height in {50, 200, 499, 550, 700}:
                    block_no_mmr = block.replace(
                        reward_chain_block=block.reward_chain_block.replace(header_mmr_root=bytes32.zeros)
                    )
                    await _validate_and_add_block(
                        blockchain, block_no_mmr, expected_error=Err.INVALID_REWARD_BLOCK_HASH
                    )
                if (
                    len(block.finished_sub_slots) > 0
                    and block.finished_sub_slots[0].challenge_chain.subepoch_summary_hash is not None
                ):
                    slot = block.finished_sub_slots[0].replace(
                        challenge_chain=block.finished_sub_slots[0].challenge_chain.replace(
                            subepoch_summary_hash=bytes32.zeros
                        )
                    )
                    block_no_challenge_root = block.replace(finished_sub_slots=([slot]))
                    # changing the subepoch_summary_hash will cause INVALID_POSPACE error
                    # because it changes the block challenge
                    await _validate_and_add_block(
                        blockchain, block_no_challenge_root, expected_error=Err.INVALID_POSPACE
                    )
                await _validate_and_add_block_no_error(blockchain, block)
                log.info(f"Successfully added {block.height}")
                if not passed_fork:
                    assert block.reward_chain_block.header_mmr_root is None
                    peak = blockchain.get_peak()
                    assert peak is not None and peak.header_hash == block.header_hash
                    if peak.sub_epoch_summary_included is not None:
                        assert peak.sub_epoch_summary_included.challenge_merkle_root is None
                else:
                    assert block.reward_chain_block.header_mmr_root is not None
                    peak = blockchain.get_peak()
                    assert peak is not None and peak.header_hash == block.header_hash
                    if peak.sub_epoch_summary_included is not None:
                        assert peak.sub_epoch_summary_included.challenge_merkle_root is not None

                log.info(f"Successfully added {block.height}")


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
            HARD_FORK_HEIGHT=uint32(2),
            PLOT_FILTER_128_HEIGHT=uint32(10),
            PLOT_FILTER_64_HEIGHT=uint32(15),
            PLOT_FILTER_32_HEIGHT=uint32(20),
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
