"""
Integration tests for verifying full_node starts and syncs correctly after pruning.
"""

from __future__ import annotations

import logging

import pytest
from chia_rs import CoinRecord, ConsensusConstants
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64

from chia._tests.core.node_height import node_height_exactly
from chia._tests.util.time_out_assert import time_out_assert
from chia.cmds.db_prune_func import prune_db
from chia.consensus.coin_store_protocol import CoinStoreProtocol
from chia.simulator.block_tools import create_block_tools_async
from chia.simulator.keyring import TempKeyring
from chia.simulator.setup_services import setup_full_node
from chia.types.peer_info import PeerInfo

log = logging.getLogger(__name__)


async def get_all_coin_records(coin_store: CoinStoreProtocol, max_height: uint32) -> dict[bytes32, CoinRecord]:
    """Get all coin records from the coin store up to a given height."""
    all_records: dict[bytes32, CoinRecord] = {}
    for height in range(max_height + 1):
        records = await coin_store.get_coins_added_at_height(uint32(height))
        for record in records:
            all_records[record.coin.name()] = record
    return all_records


def compare_coin_records(records1: dict[bytes32, CoinRecord], records2: dict[bytes32, CoinRecord]) -> tuple[bool, str]:
    """
    Compare two sets of coin records and return whether they match.
    Returns (match: bool, message: str) where message explains any differences.
    """
    if len(records1) != len(records2):
        return False, f"Different number of coin records: {len(records1)} vs {len(records2)}"

    for coin_name, record1 in records1.items():
        if coin_name not in records2:
            return False, f"Coin {coin_name.hex()[:16]}... missing from second set"
        record2 = records2[coin_name]
        if record1.coin != record2.coin:
            return False, f"Coin {coin_name.hex()[:16]}... has different coin data"
        if record1.confirmed_block_index != record2.confirmed_block_index:
            msg = (
                f"Coin {coin_name.hex()[:16]}... confirmed at different heights: "
                f"{record1.confirmed_block_index} vs {record2.confirmed_block_index}"
            )
            return False, msg
        if record1.spent_block_index != record2.spent_block_index:
            msg = (
                f"Coin {coin_name.hex()[:16]}... spent at different heights: "
                f"{record1.spent_block_index} vs {record2.spent_block_index}"
            )
            return False, msg
        if record1.coinbase != record2.coinbase:
            return False, f"Coin {coin_name.hex()[:16]}... has different coinbase flag"

    return True, "All coin records match"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "num_blocks,blocks_back,compare_height",
    [
        (200, 50, 149),  # many coins: exercises compare_coin_records branch checks (>= 3 records)
        (2, 1, 0),  # few coins at height <= 0: exercises else branch (< 3 records)
    ],
)
async def test_full_node_starts_after_prune(
    self_hostname: str,
    blockchain_constants: ConsensusConstants,
    num_blocks: int,
    blocks_back: int,
    compare_height: int,
) -> None:
    """
    Test that a full_node can start correctly after its database has been pruned,
    and that coin records are preserved correctly below the prune height.

    This test:
    1. Creates a full_node with num_blocks transaction blocks
    2. Stops the node
    3. Prunes blocks_back blocks from the peak
    4. Restarts the full_node
    5. Verifies it starts with the correct peak height
    6. Verifies coin records are intact for heights <= compare_height
    """
    config_overrides = {"full_node.max_sync_wait": 0}
    db_name = f"blockchain_prune_test_{num_blocks}_{blocks_back}.db"
    expected_peak_after_prune = num_blocks - 1 - blocks_back

    with TempKeyring(populate=True) as keychain:
        async with create_block_tools_async(
            constants=blockchain_constants, keychain=keychain, config_overrides=config_overrides
        ) as bt:
            # Generate test blocks with transactions to create coin records
            blocks = bt.get_consecutive_blocks(num_blocks, guarantee_transaction_block=True)

            # First, create the node and add blocks to build a blockchain
            async with setup_full_node(
                blockchain_constants,
                db_name,
                self_hostname,
                bt,
                simulator=False,
                db_version=2,
                reuse_db=True,
            ) as service:
                full_node = service._api.full_node

                # Add all blocks to the blockchain
                for block in blocks:
                    await full_node.add_block(block)

                # Verify we have the expected peak
                peak = full_node.blockchain.get_peak()
                assert peak is not None
                assert peak.height == num_blocks - 1

                # Store coin records before pruning for comparison
                records_before_prune = await get_all_coin_records(full_node.coin_store, uint32(compare_height))
                num_coins_before = len(records_before_prune)
                log.info(f"Coin records at height <= {compare_height} before prune: {num_coins_before}")

                # Exercise compare_coin_records length-mismatch branch (skip when no records)
                if records_before_prune:
                    match, msg = compare_coin_records(records_before_prune, {})
                    assert not match
                    assert "Different number of coin records" in msg

                # Exercise remaining compare_coin_records branches (need at least 3 records)
                if len(records_before_prune) >= 3:
                    items = list(records_before_prune.items())
                    (n1, r1), (n2, r2), (n3, r3) = items[0], items[1], items[2]

                    # Branch: coin missing from second set (same length, different keys)
                    recs1 = {n1: r1, n2: r2}
                    recs2 = {n1: r1, n3: r3}
                    match, msg = compare_coin_records(recs1, recs2)
                    assert not match
                    assert "missing from second set" in msg

                    # Branch: different coin data (same key, different record's coin)
                    recs1 = {n1: r1}
                    recs2 = {n1: r2}  # r2 has different coin
                    match, msg = compare_coin_records(recs1, recs2)
                    assert not match
                    assert "has different coin data" in msg

                    # Branch: different confirmed_block_index
                    r1_alt_conf = CoinRecord(
                        r1.coin,
                        uint32(99999),
                        r1.spent_block_index,
                        r1.coinbase,
                        uint64(0),
                    )
                    recs1 = {n1: r1}
                    recs2 = {n1: r1_alt_conf}
                    match, msg = compare_coin_records(recs1, recs2)
                    assert not match
                    assert "confirmed at different heights" in msg

                    # Branch: different spent_block_index
                    r1_alt_spent = CoinRecord(
                        r1.coin,
                        r1.confirmed_block_index,
                        uint32(88888),
                        r1.coinbase,
                        uint64(0),
                    )
                    recs2 = {n1: r1_alt_spent}
                    match, msg = compare_coin_records(recs1, recs2)
                    assert not match
                    assert "spent at different heights" in msg

                    # Branch: different coinbase
                    r1_alt_coinbase = CoinRecord(
                        r1.coin,
                        r1.confirmed_block_index,
                        r1.spent_block_index,
                        not r1.coinbase,
                        uint64(0),
                    )
                    recs2 = {n1: r1_alt_coinbase}
                    match, msg = compare_coin_records(recs1, recs2)
                    assert not match
                    assert "different coinbase flag" in msg

            # Node is now stopped. Prune the database.
            db_path = bt.root_path / db_name
            assert db_path.exists(), f"Database file not found: {db_path}"

            prune_db(db_path, blocks_back=blocks_back)

            # Restart the node with the pruned database
            async with setup_full_node(
                blockchain_constants,
                db_name,
                self_hostname,
                bt,
                simulator=False,
                db_version=2,
                reuse_db=True,
            ) as service2:
                full_node2 = service2._api.full_node

                # Verify the node started with the correct pruned peak
                peak2 = full_node2.blockchain.get_peak()
                assert peak2 is not None
                assert peak2.height == expected_peak_after_prune, (
                    f"Expected peak height {expected_peak_after_prune}, got {peak2.height}"
                )

                # Verify coin records at heights <= compare_height are preserved
                records_after_prune = await get_all_coin_records(full_node2.coin_store, uint32(compare_height))
                log.info(f"Coin records at height <= {compare_height} after prune: {len(records_after_prune)}")

                # Compare coin records
                match, message = compare_coin_records(records_before_prune, records_after_prune)
                assert match, f"Coin records changed after prune: {message}"


@pytest.mark.anyio
async def test_pruned_node_can_sync_forward(
    self_hostname: str,
    blockchain_constants: ConsensusConstants,
) -> None:
    """
    Test that a pruned full_node can sync forward when connected to a node with more blocks,
    and that the coin records match after syncing.

    This test:
    1. Creates full_node_1 with 100 transaction blocks (to create coin records)
    2. Creates full_node_2 with the same 100 blocks
    3. Stops full_node_2
    4. Adds 50 more transaction blocks to full_node_1 (now at height 149)
    5. Prunes full_node_2's database by 30 blocks (new peak = 69)
    6. Restarts full_node_2 and connects to full_node_1
    7. Verifies full_node_2 syncs forward to height 149
    8. Verifies coin records match between both nodes
    """
    config_overrides = {"full_node.max_sync_wait": 0}
    db_name_1 = "blockchain_sync_source.db"
    db_name_2 = "blockchain_sync_pruned.db"

    with TempKeyring(populate=True) as keychain1, TempKeyring(populate=True) as keychain2:
        async with (
            create_block_tools_async(
                constants=blockchain_constants, keychain=keychain1, config_overrides=config_overrides
            ) as bt1,
            create_block_tools_async(
                constants=blockchain_constants, keychain=keychain2, config_overrides=config_overrides
            ) as bt2,
        ):
            # Generate initial blocks with transaction blocks to create coin records
            # guarantee_transaction_block=True ensures blocks have transactions/rewards
            initial_blocks = bt1.get_consecutive_blocks(100, guarantee_transaction_block=True)

            # Set up node 1 with initial blocks
            async with setup_full_node(
                blockchain_constants,
                db_name_1,
                self_hostname,
                bt1,
                simulator=False,
                db_version=2,
                reuse_db=True,
            ) as service1:
                full_node_1 = service1._api
                for block in initial_blocks:
                    await full_node_1.full_node.add_block(block)

                # Set up node 2 with the same initial blocks
                async with setup_full_node(
                    blockchain_constants,
                    db_name_2,
                    self_hostname,
                    bt2,
                    simulator=False,
                    db_version=2,
                    reuse_db=True,
                ) as service2:
                    full_node_2 = service2._api
                    for block in initial_blocks:
                        await full_node_2.full_node.add_block(block)

                    # Verify both nodes are at height 99
                    peak1 = full_node_1.full_node.blockchain.get_peak()
                    peak2 = full_node_2.full_node.blockchain.get_peak()
                    assert peak1 is not None and peak1.height == 99
                    assert peak2 is not None and peak2.height == 99

                # Node 2 is now stopped. Add more blocks to node 1 with transactions.
                additional_blocks = bt1.get_consecutive_blocks(
                    50, block_list_input=initial_blocks, guarantee_transaction_block=True
                )
                for block in additional_blocks[100:]:  # Only add the new blocks
                    await full_node_1.full_node.add_block(block)

                # Node 1 is now at height 149
                peak1_after = full_node_1.full_node.blockchain.get_peak()
                assert peak1_after is not None and peak1_after.height == 149

                # Prune node 2's database by 30 blocks (new peak = 69)
                db_path_2 = bt2.root_path / db_name_2
                prune_db(db_path_2, blocks_back=30)

                # Restart node 2 with the pruned database
                async with setup_full_node(
                    blockchain_constants,
                    db_name_2,
                    self_hostname,
                    bt2,
                    simulator=False,
                    db_version=2,
                    reuse_db=True,
                ) as service2_restarted:
                    full_node_2_restarted = service2_restarted._api

                    # Verify pruned node starts at the correct height
                    peak_after_prune = full_node_2_restarted.full_node.blockchain.get_peak()
                    assert peak_after_prune is not None
                    assert peak_after_prune.height == 69, f"Expected height 69, got {peak_after_prune.height}"

                    # Connect node 2 to node 1
                    await full_node_2_restarted.full_node.server.start_client(
                        PeerInfo(self_hostname, full_node_1.full_node.server.get_port()),
                        on_connect=full_node_2_restarted.full_node.on_connect,
                    )

                    # Node 2 should sync to node 1's height (149)
                    await time_out_assert(
                        60,
                        node_height_exactly,
                        True,
                        full_node_2_restarted,
                        149,
                    )

                    # Verify coin records match between both nodes
                    # Get all coin records from both nodes
                    coin_store_1 = full_node_1.full_node.coin_store
                    coin_store_2 = full_node_2_restarted.full_node.coin_store

                    records_1 = await get_all_coin_records(coin_store_1, uint32(149))
                    records_2 = await get_all_coin_records(coin_store_2, uint32(149))

                    # Log some stats for debugging
                    log.info(f"Node 1 has {len(records_1)} coin records")
                    log.info(f"Node 2 has {len(records_2)} coin records")

                    # Verify the coin records match
                    match, message = compare_coin_records(records_1, records_2)
                    assert match, f"Coin records do not match after sync: {message}"

                    # Additional verification: check that we have a reasonable number of coins
                    # Each block should have at least reward coins (farmer + pool rewards)
                    assert len(records_1) >= 149, f"Expected at least 149 coin records, got {len(records_1)}"


@pytest.mark.anyio
async def test_pruned_node_can_receive_new_blocks(
    self_hostname: str,
    blockchain_constants: ConsensusConstants,
) -> None:
    """
    Test that a pruned full_node can receive and process new blocks,
    and that coin records match a reference node that processed all blocks from scratch.

    This test:
    1. Creates a full_node with 100 transaction blocks
    2. Stops the node
    3. Prunes 20 blocks (new peak = 79)
    4. Restarts the node
    5. Manually adds blocks from 80-119
    6. Creates a reference node and adds all 120 blocks from scratch
    7. Verifies coin records match between pruned+resynced node and reference node
    """
    config_overrides = {"full_node.max_sync_wait": 0}
    db_name = "blockchain_prune_new_blocks.db"
    db_name_reference = "blockchain_reference.db"

    with TempKeyring(populate=True) as keychain:
        async with create_block_tools_async(
            constants=blockchain_constants, keychain=keychain, config_overrides=config_overrides
        ) as bt:
            # Generate 120 blocks total with transactions
            all_blocks = bt.get_consecutive_blocks(120, guarantee_transaction_block=True)
            initial_blocks = all_blocks[:100]

            # Create node with initial blocks
            async with setup_full_node(
                blockchain_constants,
                db_name,
                self_hostname,
                bt,
                simulator=False,
                db_version=2,
                reuse_db=True,
            ) as service:
                full_node = service._api.full_node
                for block in initial_blocks:
                    await full_node.add_block(block)
                peak = full_node.blockchain.get_peak()
                assert peak is not None and peak.height == 99

                # Store coin records at height 79 for later comparison
                records_at_79 = await get_all_coin_records(full_node.coin_store, uint32(79))
                log.info(f"Coin records at height <= 79 before prune: {len(records_at_79)}")

            # Prune 20 blocks
            db_path = bt.root_path / db_name
            prune_db(db_path, blocks_back=20)

            # Restart and add new blocks
            async with setup_full_node(
                blockchain_constants,
                db_name,
                self_hostname,
                bt,
                simulator=False,
                db_version=2,
                reuse_db=True,
            ) as service2:
                full_node2 = service2._api.full_node

                # Verify pruned state
                peak = full_node2.blockchain.get_peak()
                assert peak is not None
                assert peak.height == 79

                # Verify coin records at height <= 79 are preserved after prune
                records_after_prune = await get_all_coin_records(full_node2.coin_store, uint32(79))
                match, message = compare_coin_records(records_at_79, records_after_prune)
                assert match, f"Coin records at height <= 79 changed after prune: {message}"

                # The pruned node needs to first get the blocks between 80-99
                # before it can add blocks 100-119
                # So we add all blocks from 80 onwards
                for block in all_blocks[80:]:
                    await full_node2.add_block(block)

                # Verify final state
                final_peak = full_node2.blockchain.get_peak()
                assert final_peak is not None
                assert final_peak.height == 119, f"Expected height 119, got {final_peak.height}"

                # Get coin records from the pruned+resynced node
                pruned_records = await get_all_coin_records(full_node2.coin_store, uint32(119))
                log.info(f"Pruned node has {len(pruned_records)} coin records after resync")

                # Create a reference node and process all blocks from scratch
                async with setup_full_node(
                    blockchain_constants,
                    db_name_reference,
                    self_hostname,
                    bt,
                    simulator=False,
                    db_version=2,
                    reuse_db=True,
                ) as service_reference:
                    full_node_reference = service_reference._api.full_node

                    # Add all 120 blocks from scratch
                    for block in all_blocks:
                        await full_node_reference.add_block(block)

                    ref_peak = full_node_reference.blockchain.get_peak()
                    assert ref_peak is not None and ref_peak.height == 119

                    # Get coin records from the reference node
                    reference_records = await get_all_coin_records(full_node_reference.coin_store, uint32(119))
                    log.info(f"Reference node has {len(reference_records)} coin records")

                    # Verify coin records match between pruned+resynced node and reference
                    match, message = compare_coin_records(reference_records, pruned_records)
                    assert match, f"Coin records do not match reference after prune+resync: {message}"
