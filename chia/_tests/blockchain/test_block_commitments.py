from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from chia_rs import ConsensusConstants, FullBlock, SpendBundle
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
from chia.consensus.block_generator_info import block_has_transactions_generator
from chia.consensus.block_height_map import BlockHeightMap
from chia.consensus.blockchain import AddBlockResult, Blockchain
from chia.consensus.blockchain_mmr import BlockchainMMRManager
from chia.consensus.coin_commitments import EMPTY_MERKLE_SET_ROOT, compute_coin_commitments_root, compute_mmr_leaf
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.get_block_challenge import pre_sp_tx_block_height
from chia.consensus.mmr import MerkleMountainRange
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.mmr_store import MMRStore
from chia.protocols import full_node_protocol
from chia.simulator.block_tools import BlockTools, create_block_tools_async, test_constants
from chia.simulator.wallet_tools import WalletTool
from chia.types.blockchain_format.coin import Coin
from chia.types.peer_info import PeerInfo
from chia.types.validation_state import ValidationState
from chia.util.db_wrapper import DBWrapper2, generate_in_memory_db_uri
from chia.util.errors import Err
from chia.util.inline_executor import InlineExecutor
from chia.util.keychain import Keychain

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
        passed_sp_or_slot = False
        async with create_blockchain(constants, 2) as (blockchain, _):
            for i, block in enumerate(blocks):
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
            HARD_FORK_HEIGHT=uint32(0),
            PLOT_V1_PHASE_OUT_EPOCH_BITS=uint8(8),
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

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_batch_sync_fork_overtakes_mid_batch(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, self_hostname: str, db_version: int
    ) -> None:
        """A fork that overtakes the canonical chain mid-batch must not reject
        the post-reorg blocks: the augmented MMR snapshot is refreshed from the
        canonical manager after each branch change."""
        bt = hf2_bt
        constants = HF2_CONSTANTS
        async with setup_two_nodes(constants, db_version, self_hostname) as (
            full_node_1,
            _,
            _,
            _,
            _,
        ):
            # canonical chain A to height 17
            blocks_a = bt.get_consecutive_blocks(18, guarantee_transaction_block=True)
            for block in blocks_a:
                await full_node_1.full_node.add_block(block)

            # fork chain B diverges at height 4 and overtakes the canonical tip
            # partway through the batch, then continues for several more blocks
            blocks_b = bt.get_consecutive_blocks(
                20, block_list_input=blocks_a[:5], seed=b"fork", guarantee_transaction_block=True
            )
            batch = blocks_b[5:]
            first = batch[0]
            fork_height = blocks_a[4].height
            prev_record = await full_node_1.full_node.blockchain.get_block_record_from_db(first.prev_header_hash)
            assert prev_record is not None
            ssi, diff = get_next_sub_slot_iters_and_difficulty(
                constants, len(first.finished_sub_slots) > 0, prev_record, full_node_1.full_node.blockchain
            )
            blockchain = AugmentedBlockchain(full_node_1.full_node.blockchain)
            success, _ = await full_node_1.full_node.add_block_batch(
                batch,
                PeerInfo("0.0.0.0", 0),
                ForkInfo(fork_height, fork_height, first.prev_header_hash),
                ValidationState(ssi, diff, None),
                blockchain,
            )
            assert success
            peak = full_node_1.full_node.blockchain.get_peak()
            assert peak is not None
            assert peak.header_hash == blocks_b[-1].header_hash


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


def _find_spend_block(blocks: list[FullBlock]) -> FullBlock:
    for block in blocks:
        if block_has_transactions_generator(block):
            return block
    raise AssertionError("no block with a transactions generator found")


def _spendable_reward_coins(blocks: list[FullBlock], reward_ph: bytes32) -> list[Coin]:
    coins: list[Coin] = []
    for block in blocks:
        for coin in block.get_included_reward_coins():
            if coin.puzzle_hash == reward_ph:
                coins.append(coin)
    return coins


class TestCoinCommitmentRoots:
    """Tests for composite MMR leaves: H(header_hash || coin_commitments_root)"""

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_tx_outputs_committed_and_reconstructed(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode
    ) -> None:
        bt = hf2_bt
        wallet = WalletTool(bt.constants)
        reward_ph = wallet.get_new_puzzlehash()
        blocks = bt.get_consecutive_blocks(
            8,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
        )
        spend_coin = None
        for coin in blocks[2].get_included_reward_coins():
            if coin.puzzle_hash == reward_ph:
                spend_coin = coin
        assert spend_coin is not None

        receiver_ph = wallet.get_new_puzzlehash()
        spend_bundle = wallet.generate_signed_transaction(uint64(1000), receiver_ph, spend_coin)
        blocks = bt.get_consecutive_blocks(
            8,
            block_list_input=blocks,
            transaction_data=spend_bundle,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
        )
        spend_block = _find_spend_block(blocks)

        async with create_blockchain(bt.constants, 2) as (blockchain, _):
            for block in blocks:
                await _validate_and_add_block(blockchain, block)

            # the spend's outputs are committed: the reconstructed root of the
            # spend block matches a direct computation from the spend bundle
            expected_spend_root = compute_coin_commitments_root([spend_coin.name()], spend_bundle.additions())
            assert expected_spend_root != EMPTY_MERKLE_SET_ROOT
            assert await blockchain.coin_store.get_coin_commitments_root(spend_block.height) == expected_spend_root

            # a reward-only transaction block commits the canonical empty root
            reward_only = blocks[1]
            assert block_has_transactions_generator(reward_only) is False
            assert await blockchain.coin_store.get_coin_commitments_root(reward_only.height) == EMPTY_MERKLE_SET_ROOT

            # the live canonical MMR root equals the hand-built composite MMR
            assert blockchain.compute_current_mmr_root() == await _expected_canonical_mmr_root(blockchain)

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_changed_outputs_change_committed_root(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode
    ) -> None:
        bt = hf2_bt
        wallet = WalletTool(bt.constants)
        reward_ph = wallet.get_new_puzzlehash()
        base_blocks = bt.get_consecutive_blocks(
            8,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
        )
        spend_coin = None
        for coin in base_blocks[2].get_included_reward_coins():
            if coin.puzzle_hash == reward_ph:
                spend_coin = coin
        assert spend_coin is not None

        receiver_ph = wallet.get_new_puzzlehash()
        bundle_a = wallet.generate_signed_transaction(uint64(1000), receiver_ph, spend_coin)
        bundle_b = wallet.generate_signed_transaction(uint64(2000), receiver_ph, spend_coin)

        # the coin commitments root binds the spend's outputs
        root_a = compute_coin_commitments_root([spend_coin.name()], bundle_a.additions())
        root_b = compute_coin_commitments_root([spend_coin.name()], bundle_b.additions())
        assert root_a != root_b

        roots = []
        for seed, bundle in ((b"a", bundle_a), (b"b", bundle_b)):
            chain = bt.get_consecutive_blocks(
                6,
                block_list_input=base_blocks,
                transaction_data=bundle,
                farmer_reward_puzzle_hash=reward_ph,
                pool_reward_puzzle_hash=reward_ph,
                guarantee_transaction_block=True,
                seed=seed,
            )
            async with create_blockchain(bt.constants, 2) as (blockchain, _):
                for block in chain:
                    await _validate_and_add_block(blockchain, block)
                # each chain's live MMR root agrees with coin-store reconstruction
                expected = await _expected_canonical_mmr_root(blockchain)
                assert blockchain.compute_current_mmr_root() == expected
                roots.append(blockchain.compute_current_mmr_root())

        # changing the spend's outputs changes the later committed MMR root
        assert roots[0] != roots[1]

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_startup_mmr_reconstruction(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        bt = hf2_bt
        wallet = WalletTool(bt.constants)
        reward_ph = wallet.get_new_puzzlehash()
        # a chain with a real transaction spend, so the restart reconstruction
        # covers a non-empty coin commitments root
        blocks = bt.get_consecutive_blocks(
            8,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
        )
        spend_coin = _spendable_reward_coins(blocks, reward_ph)[0]
        spend_bundle = wallet.generate_signed_transaction(uint64(1000), wallet.get_new_puzzlehash(), spend_coin)
        blocks = bt.get_consecutive_blocks(
            12,
            block_list_input=blocks,
            transaction_data=spend_bundle,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
        )
        spend_block = _find_spend_block(blocks)
        expected_spend_root = compute_coin_commitments_root([spend_coin.name()], spend_bundle.additions())
        assert expected_spend_root != EMPTY_MERKLE_SET_ROOT

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks:
                await _validate_and_add_block(blockchain, block)
            root_before = blockchain.compute_current_mmr_root()
            assert root_before is not None
            # the spend block's root is committed and reconstructable
            assert await blockchain.coin_store.get_coin_commitments_root(spend_block.height) == expected_spend_root
            blockchain.shut_down()

            # simulate a restart: a fresh Blockchain and height map over the same DB
            restarted = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "second")
            # the MMR was rebuilt from coin-store reconstruction to the same root
            assert restarted.compute_current_mmr_root() == root_before
            assert await restarted.coin_store.get_coin_commitments_root(spend_block.height) == expected_spend_root

            # the restarted chain can validate and append the next block
            next_blocks = bt.get_consecutive_blocks(2, block_list_input=blocks)
            for block in next_blocks[len(blocks) :]:
                await _validate_and_add_block(restarted, block)
            assert restarted.compute_current_mmr_root() == await _expected_canonical_mmr_root(restarted)
            restarted.shut_down()

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_reorg_rollback_and_branch_extension(self, hf2_bt: BlockTools, consensus_mode: ConsensusMode) -> None:
        bt = hf2_bt
        blocks_a = bt.get_consecutive_blocks(15, guarantee_transaction_block=True)
        # a fork that diverges at height 5 and overtakes the original chain
        blocks_b = bt.get_consecutive_blocks(
            13, block_list_input=blocks_a[:5], seed=b"fork", guarantee_transaction_block=True
        )

        async with create_blockchain(bt.constants, 2) as (blockchain, _):
            for block in blocks_a:
                await _validate_and_add_block(blockchain, block)
            root_a = blockchain.compute_current_mmr_root()
            assert root_a == await _expected_canonical_mmr_root(blockchain)

            # add the fork blocks with a shared overlay and fork info, mirroring
            # the full-node batch validation path
            fork_info = ForkInfo(blocks_a[4].height, blocks_a[4].height, blocks_a[4].header_hash)
            aug_chain = AugmentedBlockchain(blockchain)
            for block in blocks_b[5:]:
                await _validate_and_add_block_no_error(
                    blockchain, block, fork_info=fork_info, augmented_blockchain=aug_chain
                )

            # the fork overtook the original chain
            peak = blockchain.get_peak()
            assert peak is not None
            assert peak.header_hash == blocks_b[-1].header_hash

            # after the reorg rolled back and extended the canonical MMR, its
            # root covers the fork branch's composite leaves
            root_b = blockchain.compute_current_mmr_root()
            assert root_b is not None
            assert root_b != root_a
            assert root_b == await _expected_canonical_mmr_root(blockchain)

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_old_orphan_replay_after_restart(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        bt = hf2_bt
        wallet = WalletTool(bt.constants)
        reward_ph = wallet.get_new_puzzlehash()
        blocks_a = bt.get_consecutive_blocks(
            15,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
        )
        # the fork branch carries a real transaction spend of a shared-prefix
        # reward coin, so the replayed orphan roots are non-empty
        spend_coin = _spendable_reward_coins(blocks_a[:5], reward_ph)[0]
        spend_bundle = wallet.generate_signed_transaction(uint64(1000), wallet.get_new_puzzlehash(), spend_coin)
        blocks_b = bt.get_consecutive_blocks(
            13,
            block_list_input=blocks_a[:5],
            transaction_data=spend_bundle,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
            seed=b"fork",
        )
        expected_spend_root = compute_coin_commitments_root([spend_coin.name()], spend_bundle.additions())
        assert expected_spend_root != EMPTY_MERKLE_SET_ROOT

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks_a:
                await _validate_and_add_block(blockchain, block)

            # add the fork blocks that don't overtake as orphans
            fork_info = ForkInfo(blocks_a[4].height, blocks_a[4].height, blocks_a[4].header_hash)
            aug_chain = AugmentedBlockchain(blockchain)
            for block in blocks_b[5:14]:
                await _validate_and_add_block(
                    blockchain,
                    block,
                    expected_result=AddBlockResult.ADDED_AS_ORPHAN,
                    fork_info=fork_info,
                    augmented_blockchain=aug_chain,
                )
            blockchain.shut_down()

            # simulate a restart: the in-memory coin commitments of the orphan
            # blocks are lost and must be reconstructed by generator replay
            restarted = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "second")

            # re-register the orphan blocks (already in the DB) so they are back
            # in the in-memory block-record cache; this replays their generators
            # through the same advance_fork_info()/run_single_block() path used
            # for old orphans after a restart
            fork_info = ForkInfo(blocks_a[4].height, blocks_a[4].height, blocks_a[4].header_hash)
            aug_chain = AugmentedBlockchain(restarted)
            for block in blocks_b[5:14]:
                await _validate_and_add_block(
                    restarted,
                    block,
                    expected_result=AddBlockResult.ALREADY_HAVE_BLOCK,
                    fork_info=fork_info,
                    augmented_blockchain=aug_chain,
                )

            # now extend the fork so it overtakes the canonical chain; the
            # fork becomes strictly heavier one block past the old peak
            for block in blocks_b[14:]:
                await _validate_and_add_block_no_error(
                    restarted, block, fork_info=fork_info, augmented_blockchain=aug_chain
                )

            peak = restarted.get_peak()
            assert peak is not None
            assert peak.header_hash == blocks_b[-1].header_hash
            # the fork's spend block was replayed and its non-empty root is
            # reconstructed from the coin store after the reorg
            assert await restarted.coin_store.get_coin_commitments_root(blocks_b[5].height) == expected_spend_root
            assert restarted.compute_current_mmr_root() == await _expected_canonical_mmr_root(restarted)
            restarted.shut_down()

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_restart_and_reorg_with_transaction_spends(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        """
        Restart and reorg coverage with distinct transaction spends on both
        branches: a multiple-spend block on the canonical branch and an
        ephemeral create-and-spend on the fork branch. Asserts the per-height
        CoinStore-reconstructed roots agree with the conds-derived roots, and
        the final MMR root matches a hand-built composite MMR after the restart
        and after the reorg.
        """
        bt = hf2_bt
        wallet = WalletTool(bt.constants)
        reward_ph = wallet.get_new_puzzlehash()
        base = bt.get_consecutive_blocks(
            8,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
        )
        spendable = _spendable_reward_coins(base, reward_ph)

        # chain A: one block spending two coins (multiple spends in one block)
        bundle_a = SpendBundle.aggregate(
            [
                wallet.generate_signed_transaction(uint64(1000), wallet.get_new_puzzlehash(), spendable[0]),
                wallet.generate_signed_transaction(uint64(500), wallet.get_new_puzzlehash(), spendable[1]),
            ]
        )
        chain_a = bt.get_consecutive_blocks(
            4,
            block_list_input=base,
            transaction_data=bundle_a,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
        )

        # chain B (one block longer, so heavier): an ephemeral create-and-spend
        tx_b1 = wallet.generate_signed_transaction(uint64(700), wallet.get_new_puzzlehash(), spendable[2])
        ephemeral_coin = tx_b1.additions()[0]
        tx_b2 = wallet.generate_signed_transaction(uint64(300), wallet.get_new_puzzlehash(), ephemeral_coin)
        bundle_b = SpendBundle.aggregate([tx_b1, tx_b2])
        chain_b = bt.get_consecutive_blocks(
            5,
            block_list_input=base,
            transaction_data=bundle_b,
            farmer_reward_puzzle_hash=reward_ph,
            pool_reward_puzzle_hash=reward_ph,
            guarantee_transaction_block=True,
            seed=b"fork",
        )

        root_a = compute_coin_commitments_root([c.name() for c in bundle_a.removals()], bundle_a.additions())
        root_b = compute_coin_commitments_root([c.name() for c in bundle_b.removals()], bundle_b.additions())
        assert root_a != EMPTY_MERKLE_SET_ROOT
        assert root_b != EMPTY_MERKLE_SET_ROOT
        assert root_a != root_b
        # first block after the shared base, on either branch
        spend_height = uint32(base[-1].height + 1)

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in chain_a:
                await _validate_and_add_block(blockchain, block)

            # per-height reconstruction agrees with chain A's validated spends
            assert await blockchain.coin_store.get_coin_commitments_root(spend_height) == root_a
            mmr_root_a = blockchain.compute_current_mmr_root()
            assert mmr_root_a == await _expected_canonical_mmr_root(blockchain)
            blockchain.shut_down()

            # restart: the MMR is rebuilt from coin-store reconstruction with
            # real spends, to the same root
            restarted = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "second")
            assert restarted.compute_current_mmr_root() == mmr_root_a
            assert await restarted.coin_store.get_coin_commitments_root(spend_height) == root_a

            # reorg to chain B with its distinct ephemeral-spend block
            fork_info = ForkInfo(base[-1].height, base[-1].height, base[-1].header_hash)
            aug_chain = AugmentedBlockchain(restarted)
            for block in chain_b[len(base) :]:
                await _validate_and_add_block_no_error(
                    restarted, block, fork_info=fork_info, augmented_blockchain=aug_chain
                )

            peak = restarted.get_peak()
            assert peak is not None
            assert peak.header_hash == chain_b[-1].header_hash

            # per-height reconstruction now follows chain B's ephemeral spend,
            # and the final MMR root matches the hand-built composite MMR
            assert await restarted.coin_store.get_coin_commitments_root(spend_height) == root_b
            assert restarted.compute_current_mmr_root() == await _expected_canonical_mmr_root(restarted)
            restarted.shut_down()

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_restart_new_orphan_child(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        """
        After a restart, a node must accept a new child of a previously stored
        orphan branch: the stored fork ancestry's coin commitments must be
        replayed/registered before the new block is prevalidated. The old
        orphan blocks are not resubmitted.
        """
        bt = hf2_bt
        blocks_a = bt.get_consecutive_blocks(18, guarantee_transaction_block=True)
        # fork branch diverging at height 4, lighter than the canonical tip
        blocks_b = bt.get_consecutive_blocks(
            10, block_list_input=blocks_a[:5], seed=b"fork", guarantee_transaction_block=True
        )

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks_a:
                await _validate_and_add_block(blockchain, block)

            fork_info = ForkInfo(blocks_a[4].height, blocks_a[4].height, blocks_a[4].header_hash)
            aug_chain = AugmentedBlockchain(blockchain)
            for block in blocks_b[5:]:
                await _validate_and_add_block(
                    blockchain,
                    block,
                    expected_result=AddBlockResult.ADDED_AS_ORPHAN,
                    fork_info=fork_info,
                    augmented_blockchain=aug_chain,
                )
            blockchain.shut_down()

            # restart: a fresh Blockchain over the same DB
            restarted = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "second")

            # create a new block extending the orphan branch tip
            blocks_b2 = bt.get_consecutive_blocks(1, block_list_input=blocks_b, seed=b"fork")
            new_child = blocks_b2[-1]
            assert new_child.prev_header_hash == blocks_b[-1].header_hash

            # submit only the new orphan child; the stored fork ancestry is
            # replayed/registered before prevalidation (as FullNode.add_block
            # does via prepare_stored_fork_ancestry). The augmented overlay is
            # created after the replay, so its MMR snapshot includes the
            # newly registered leaves.
            fork_info2 = await restarted.prepare_stored_fork_ancestry(new_child)
            assert fork_info2 is not None
            await _validate_and_add_block(
                restarted,
                new_child,
                expected_result=AddBlockResult.ADDED_AS_ORPHAN,
                fork_info=fork_info2,
            )

            # the orphan child was accepted without resubmitting the old orphan
            # blocks, and the canonical MMR remains consistent with coin-store
            # reconstruction
            assert restarted.compute_current_mmr_root() == await _expected_canonical_mmr_root(restarted)
            restarted.shut_down()


def _spend_chain(bt: BlockTools, wallet: WalletTool, reward_ph: bytes32) -> list[FullBlock]:
    """A chain with a real transaction spend, so it has a non-empty coin commitments root."""
    blocks = bt.get_consecutive_blocks(
        8,
        farmer_reward_puzzle_hash=reward_ph,
        pool_reward_puzzle_hash=reward_ph,
        guarantee_transaction_block=True,
    )
    spend_coin = _spendable_reward_coins(blocks, reward_ph)[0]
    spend_bundle = wallet.generate_signed_transaction(uint64(1000), wallet.get_new_puzzlehash(), spend_coin)
    return bt.get_consecutive_blocks(
        6,
        block_list_input=blocks,
        transaction_data=spend_bundle,
        farmer_reward_puzzle_hash=reward_ph,
        pool_reward_puzzle_hash=reward_ph,
        guarantee_transaction_block=True,
    )


async def _open_blockchain_no_rebuild(
    constants: ConsensusConstants, db_wrapper: DBWrapper2, blockchain_dir: Path
) -> tuple[Blockchain, AsyncMock]:
    """
    Open a Blockchain whose coin store fails if get_coin_commitments_root() is
    called, so a successful open proves the canonical MMR was hydrated from the
    persisted store rather than rebuilt from the coin store. Returns the chain
    and the spy (so the caller can assert it was never called).
    """
    coin_store = await CoinStore.create(db_wrapper)
    block_store = await BlockStore.create(db_wrapper)
    mmr_store = await MMRStore.create(db_wrapper)
    height_map = await BlockHeightMap.create(blockchain_dir, db_wrapper)
    spy = AsyncMock(side_effect=AssertionError("canonical MMR was rebuilt from the coin store, not hydrated"))
    coin_store.get_coin_commitments_root = spy  # type: ignore[method-assign]
    blockchain = await Blockchain.create(
        coin_store, block_store, height_map, constants, InlineExecutor(), mmr_store=mmr_store
    )
    return blockchain, spy


class TestMMRPersistence:
    """Tests for MMR persistence (Milestone 1B): startup hydration, reorg truncation, recovery."""

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_restart_hydrates_without_coinstore_rebuild(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        bt = hf2_bt
        wallet = WalletTool(bt.constants)
        reward_ph = wallet.get_new_puzzlehash()
        blocks = _spend_chain(bt, wallet, reward_ph)

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks:
                await _validate_and_add_block(blockchain, block)
            root_before = blockchain.compute_current_mmr_root()
            assert root_before is not None
            blockchain.shut_down()

            # restart: the MMR is hydrated from the persisted store, so the coin
            # store is never queried for a rebuild
            restarted, spy = await _open_blockchain_no_rebuild(bt.constants, db_wrapper, tmp_path / "second")
            assert restarted.compute_current_mmr_root() == root_before
            spy.assert_not_called()
            restarted.shut_down()

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_restart_after_reorg_hydrates(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        bt = hf2_bt
        blocks_a = bt.get_consecutive_blocks(12, guarantee_transaction_block=True)
        # a fork that diverges at height 5 and overtakes the original chain
        blocks_b = bt.get_consecutive_blocks(
            10, block_list_input=blocks_a[:5], seed=b"fork", guarantee_transaction_block=True
        )

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks_a:
                await _validate_and_add_block(blockchain, block)
            fork_info = ForkInfo(blocks_a[4].height, blocks_a[4].height, blocks_a[4].header_hash)
            aug_chain = AugmentedBlockchain(blockchain)
            for block in blocks_b[5:]:
                await _validate_and_add_block_no_error(
                    blockchain, block, fork_info=fork_info, augmented_blockchain=aug_chain
                )
            peak = blockchain.get_peak()
            assert peak is not None
            assert peak.header_hash == blocks_b[-1].header_hash
            root_after_reorg = blockchain.compute_current_mmr_root()
            blockchain.shut_down()

            # restart: the persisted MMR reflects the post-reorg branch (the old
            # suffix was truncated and the new branch appended), so hydration
            # restores the post-reorg root without a coin-store rebuild
            restarted, spy = await _open_blockchain_no_rebuild(bt.constants, db_wrapper, tmp_path / "second")
            restarted_peak = restarted.get_peak()
            assert restarted_peak is not None
            assert restarted_peak.header_hash == blocks_b[-1].header_hash
            assert restarted.compute_current_mmr_root() == root_after_reorg
            spy.assert_not_called()
            restarted.shut_down()

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_missing_persistence_rebuilds(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        bt = hf2_bt
        wallet = WalletTool(bt.constants)
        reward_ph = wallet.get_new_puzzlehash()
        blocks = _spend_chain(bt, wallet, reward_ph)

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks:
                await _validate_and_add_block(blockchain, block)
            root_before = blockchain.compute_current_mmr_root()
            blockchain.shut_down()

            # wipe the persisted MMR (e.g. a database migrated from before 1B)
            async with db_wrapper.writer() as conn:
                await conn.execute("DELETE FROM mmr_nodes")
                await conn.execute("DELETE FROM mmr_state")

            # restart: with no persisted state, the MMR is rebuilt from the coin
            # store to the same root, and the rebuild re-persists it
            restarted = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "second")
            assert restarted.compute_current_mmr_root() == root_before
            assert restarted.compute_current_mmr_root() == await _expected_canonical_mmr_root(restarted)
            restarted.shut_down()

            # the rebuild re-persisted the MMR, so a second restart hydrates it
            # without a coin-store rebuild
            restarted2, spy = await _open_blockchain_no_rebuild(bt.constants, db_wrapper, tmp_path / "third")
            assert restarted2.compute_current_mmr_root() == root_before
            spy.assert_not_called()
            restarted2.shut_down()

    @pytest.mark.anyio
    @pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN])
    async def test_stale_persistence_rebuilds(
        self, hf2_bt: BlockTools, consensus_mode: ConsensusMode, tmp_path: Path
    ) -> None:
        bt = hf2_bt
        wallet = WalletTool(bt.constants)
        reward_ph = wallet.get_new_puzzlehash()
        blocks = _spend_chain(bt, wallet, reward_ph)

        async with DBWrapper2.managed(
            database=generate_in_memory_db_uri(), uri=True, reader_count=1, db_version=2
        ) as db_wrapper:
            blockchain = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "first")
            for block in blocks:
                await _validate_and_add_block(blockchain, block)
            root_before = blockchain.compute_current_mmr_root()
            blockchain.shut_down()

            # make the persisted state stale: it points at a peak that is not the
            # stored canonical peak (e.g. a downgrade added blocks without MMR
            # persistence)
            async with db_wrapper.writer() as conn:
                await conn.execute("UPDATE mmr_state SET canonical_height = canonical_height - 1")

            # restart: the stale state is detected and the MMR is rebuilt from the
            # coin store to the correct root
            restarted = await _open_blockchain(bt.constants, db_wrapper, tmp_path / "second")
            assert restarted.compute_current_mmr_root() == root_before
            restarted.shut_down()

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
