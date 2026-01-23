#!/usr/bin/env python3
"""
Filesystem check (fsck) tool for CoinStore v3 (RocksDB).

This tool verifies the integrity of the coin store by:
1. Checking that all coins created in blocks exist in the store
2. Checking that all coins spent in blocks exist and are marked as spent
3. Finding orphaned coins (coins that exist but aren't in any block's history)
4. Verifying coin states match block history
5. Checking for data corruption or inconsistencies

Usage:
    fsck_coin_store --db-path /path/to/database
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from collections import defaultdict
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Optional

from chia_rs.sized_bytes import bytes32
from rocks_pyo3 import DB

from chia.full_node.coin_store_v3 import BlockInfo, blob_to_int, u32_to_blob
from chia.types.coin_record import CoinRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)


class FsckResults:
    """Container for fsck results and statistics."""

    def __init__(self) -> None:
        self.missing_created_coins: list[tuple[int, bytes32]] = []  # (height, coin_name)
        self.missing_spent_coins: list[tuple[int, bytes32]] = []  # (height, coin_name)
        self.orphaned_coins: list[bytes32] = []  # coins that exist but aren't in any block
        self.wrong_state_coins: list[tuple[bytes32, str, str]] = []  # (coin_name, expected, actual)
        self.duplicate_blocks: list[int] = []  # heights with duplicate block info
        self.missing_blocks: list[int] = []  # expected heights without block info
        self.corrupted_coin_records: list[bytes32] = []  # coins that can't be deserialized
        self.corrupted_block_infos: list[int] = []  # blocks that can't be deserialized
        self.total_blocks: int = 0
        self.total_coins: int = 0
        self.total_created: int = 0
        self.total_spent: int = 0


async def iterate_all_blocks(rocks_db: DB) -> AsyncGenerator[tuple[int, BlockInfo], None]:
    """Iterate through all block infos in the database."""
    # Start from the highest possible block index
    last_block_index = b"b" + bytes.fromhex("ffffffffffffffff")
    iterator = rocks_db.iterate_from(last_block_index, "reverse")

    for key, value in iterator:
        if key[:1] != b"b":
            break
        try:
            height = blob_to_int(key[1:])
            block_info = BlockInfo.from_bytes(value)
            yield height, block_info
        except Exception as e:
            log.error(f"Error parsing block at key {key.hex()}: {e}")
            yield -1, None  # Signal corruption


async def iterate_all_coins(rocks_db: DB) -> AsyncGenerator[tuple[bytes32, CoinRecord], None]:
    """Iterate through all coin records in the database."""
    iterator = rocks_db.iterate_from(b"c", "forward")
    for key, value in iterator:
        if key[:1] != b"c":
            break
        coin_name = bytes32(key[1:])
        try:
            coin_record = CoinRecord.from_bytes(value)
            yield coin_name, coin_record
        except Exception as e:
            log.error(f"Error parsing coin at key {key.hex()}: {e}")
            yield coin_name, None  # Signal corruption


async def fsck_coin_store(rocks_db: DB, max_height: Optional[int] = None) -> FsckResults:
    """
    Perform filesystem check on the coin store using a memory-efficient approach.

    Algorithm:
    1. Iterate blocks backwards, validating coins incrementally and tracking counts
    2. Iterate all coins, counting by height and finding orphans
    3. Validate that block counts match coin counts

    Args:
        rocks_db: The RocksDB instance
        max_height: Maximum block height to check (None for all, 0 = all)

    Returns:
        FsckResults with all detected issues
    """
    results = FsckResults()

    log.info("Starting fsck of coin store (memory-efficient mode)...")

    # Track which blocks we've seen and their counts
    seen_heights: set[int] = set()
    block_counts: dict[int, tuple[int, int]] = {}  # height -> (created_count, spent_count)
    all_created_coins: set[bytes32] = set()  # For orphan detection
    all_spent_coins: set[bytes32] = set()  # For validation
    max_block_height = 0
    blocks_processed = 0
    last_log_time = time.monotonic()
    last_log_count = 0

    # Phase 1: Iterate blocks backwards, validate coins incrementally
    log.info("Phase 1: Validating blocks and coins incrementally...")
    async for height, block_info in iterate_all_blocks(rocks_db):
        if height == -1:
            results.corrupted_block_infos.append(-1)
            continue
        if max_height is not None and max_height > 0 and height > max_height:
            continue

        blocks_processed += 1
        current_time = time.monotonic()

        # Log progress every 1000 blocks or every 5 seconds
        if blocks_processed % 1000 == 0 or (current_time - last_log_time) >= 5.0:
            rate = (blocks_processed - last_log_count) / max(1, current_time - last_log_time)
            log.info(
                f"Phase 1: Processed {blocks_processed:,} blocks (current height: {height:,}, "
                f"rate: {rate:.1f} blocks/sec)"
            )
            last_log_time = current_time
            last_log_count = blocks_processed

        if height in seen_heights:
            results.duplicate_blocks.append(height)
            log.warning(f"Duplicate block info at height {height}")
            continue

        seen_heights.add(height)
        max_block_height = max(max_block_height, height)
        results.total_blocks += 1

        # Track counts from block info
        created_count = len(block_info.created_coins)
        spent_count = len(block_info.spent_coins)
        block_counts[height] = (created_count, spent_count)
        results.total_created += created_count
        results.total_spent += spent_count

        # Track created/spent coins for later validation
        for coin_name in block_info.created_coins:
            all_created_coins.add(coin_name)

        for coin_name in block_info.spent_coins:
            all_spent_coins.add(coin_name)

        # Validate created coins exist and have correct height
        if created_count > 0:
            coin_keys = [b"c" + name for name in block_info.created_coins]
            coin_blobs = rocks_db.multi_get(coin_keys)
            for coin_name, blob in zip(block_info.created_coins, coin_blobs):
                if blob is None:
                    results.missing_created_coins.append((height, coin_name))
                    log.error(f"Height {height}: Created coin {coin_name.hex()} missing from store")
                else:
                    try:
                        coin_record = CoinRecord.from_bytes(blob)
                        if coin_record.confirmed_block_index != height:
                            results.wrong_state_coins.append(
                                (
                                    coin_name,
                                    f"confirmed_block_index={height}",
                                    f"confirmed_block_index={coin_record.confirmed_block_index}",
                                )
                            )
                            log.error(
                                f"Height {height}: Coin {coin_name.hex()} has wrong confirmed_block_index: "
                                f"expected {height}, got {coin_record.confirmed_block_index}"
                            )
                    except Exception as e:
                        results.corrupted_coin_records.append(coin_name)
                        log.error(f"Height {height}: Corrupted coin record {coin_name.hex()}: {e}")

        # Validate spent coins exist and have correct spent height
        if spent_count > 0:
            coin_keys = [b"c" + name for name in block_info.spent_coins]
            coin_blobs = rocks_db.multi_get(coin_keys)
            for coin_name, blob in zip(block_info.spent_coins, coin_blobs):
                if blob is None:
                    results.missing_spent_coins.append((height, coin_name))
                    log.error(f"Height {height}: Spent coin {coin_name.hex()} missing from store")
                else:
                    try:
                        coin_record = CoinRecord.from_bytes(blob)
                        if coin_record.spent_block_index != height:
                            results.wrong_state_coins.append(
                                (
                                    coin_name,
                                    f"spent_block_index={height}",
                                    f"spent_block_index={coin_record.spent_block_index}",
                                )
                            )
                            log.error(
                                f"Height {height}: Coin {coin_name.hex()} has wrong spent_block_index: "
                                f"expected {height}, got {coin_record.spent_block_index}"
                            )
                        # Verify coin was created before it was spent
                        if coin_record.confirmed_block_index == 0:
                            results.wrong_state_coins.append(
                                (
                                    coin_name,
                                    "confirmed_block_index > 0",
                                    f"confirmed_block_index={coin_record.confirmed_block_index}",
                                )
                            )
                            log.error(f"Height {height}: Spent coin {coin_name.hex()} has confirmed_block_index=0")
                        elif coin_record.confirmed_block_index > height:
                            results.wrong_state_coins.append(
                                (
                                    coin_name,
                                    f"confirmed_block_index <= {height}",
                                    f"confirmed_block_index={coin_record.confirmed_block_index}",
                                )
                            )
                            log.error(
                                f"Height {height}: Spent coin {coin_name.hex()} was created at height "
                                f"{coin_record.confirmed_block_index} but spent at {height}"
                            )
                    except Exception as e:
                        results.corrupted_coin_records.append(coin_name)
                        log.error(f"Height {height}: Corrupted coin record {coin_name.hex()}: {e}")

    log.info(
        f"Found {results.total_blocks} blocks, {results.total_created} created coins, {results.total_spent} spent coins"
    )

    # Check for missing blocks (gaps in sequence)
    if seen_heights:
        expected_heights = set(range(0, max_block_height + 1))
        results.missing_blocks = sorted(expected_heights - seen_heights)
        if results.missing_blocks:
            log.warning(f"Found {len(results.missing_blocks)} missing blocks: {results.missing_blocks[:10]}...")

    # Phase 2: Iterate all coins, count by height, find orphans
    log.info("Phase 2: Counting coins by height and finding orphans...")
    coin_counts: dict[int, tuple[int, int]] = defaultdict(lambda: (0, 0))  # height -> (created_count, spent_count)
    coins_processed = 0
    last_log_time = time.monotonic()
    last_log_count = 0

    async for coin_name, coin_record in iterate_all_coins(rocks_db):
        coins_processed += 1
        current_time = time.monotonic()

        # Log progress every 10000 coins or every 5 seconds
        if coins_processed % 10000 == 0 or (current_time - last_log_time) >= 5.0:
            rate = (coins_processed - last_log_count) / max(1, current_time - last_log_time)
            log.info(f"Phase 2: Processed {coins_processed:,} coins (rate: {rate:.1f} coins/sec)")
            last_log_time = current_time
            last_log_count = coins_processed

        if coin_record is None:
            results.corrupted_coin_records.append(coin_name)
            continue

        results.total_coins += 1

        # Count coins by their confirmed_block_index
        if coin_record.confirmed_block_index > 0:
            created_count, spent_count = coin_counts[coin_record.confirmed_block_index]
            coin_counts[coin_record.confirmed_block_index] = (created_count + 1, spent_count)

        # Count coins by their spent_block_index
        if coin_record.spent_block_index > 0:
            created_count, spent_count = coin_counts[coin_record.spent_block_index]
            coin_counts[coin_record.spent_block_index] = (created_count, spent_count + 1)

        # Check for orphaned coins (not in any block's created_coins)
        if coin_name not in all_created_coins:
            results.orphaned_coins.append(coin_name)
            log.warning(
                f"Orphaned coin {coin_name.hex()} exists in store but not in any block's created_coins "
                f"(confirmed={coin_record.confirmed_block_index}, spent={coin_record.spent_block_index})"
            )

        # Note: We can't verify that coins marked as spent are in the block's spent_coins list
        # without storing block_infos. The count validation in Phase 3 will catch inconsistencies.

    log.info(f"Found {results.total_coins} coin records")

    # Phase 3: Validate counts match
    log.info("Phase 3: Validating block counts match coin counts...")
    all_heights = set(block_counts.keys()) | set(coin_counts.keys())
    heights_checked = 0
    total_heights = len(all_heights)
    last_log_time = time.monotonic()
    last_log_count = 0
    heights_with_mismatches: list[int] = []

    for height in sorted(all_heights):
        heights_checked += 1
        current_time = time.monotonic()

        # Log progress every 1000 blocks or every 5 seconds
        if heights_checked % 1000 == 0 or (current_time - last_log_time) >= 5.0:
            rate = (heights_checked - last_log_count) / max(1, current_time - last_log_time)
            log.info(
                f"Phase 3: Checking height {height:,} ({heights_checked:,}/{total_heights:,}, "
                f"rate: {rate:.1f} heights/sec)"
            )
            last_log_time = current_time
            last_log_count = heights_checked

        block_created, block_spent = block_counts.get(height, (0, 0))
        coin_created, coin_spent = coin_counts.get(height, (0, 0))

        if block_created != coin_created:
            log.error(f"Height {height}: Created count mismatch - block says {block_created}, coins say {coin_created}")
            heights_with_mismatches.append(height)

        if block_spent != coin_spent:
            log.error(f"Height {height}: Spent count mismatch - block says {block_spent}, coins say {coin_spent}")
            if height not in heights_with_mismatches:
                heights_with_mismatches.append(height)

    # Phase 4: Detailed analysis of mismatches (only if needed)
    if heights_with_mismatches:
        log.warning(
            f"Found {len(heights_with_mismatches)} heights with count mismatches. "
            f"Running detailed analysis (this may take a while)..."
        )

        # Re-collect block info for problematic heights
        log.info("Phase 4a: Re-collecting block info for problematic heights...")
        problematic_block_infos: dict[int, BlockInfo] = {}
        for height in heights_with_mismatches:
            key = b"b" + u32_to_blob(height)
            blob = rocks_db.get(key)
            if blob is None:
                log.warning(f"Height {height}: Block info not found (was in seen_heights but now missing?)")
                continue
            try:
                block_info = BlockInfo.from_bytes(blob)
                problematic_block_infos[height] = block_info
            except Exception as e:
                log.error(f"Height {height}: Failed to parse block info: {e}")
                results.corrupted_block_infos.append(height)

        # Re-collect all coins and analyze problematic heights
        log.info("Phase 4b: Analyzing coins for problematic heights...")
        coins_by_created_height: dict[int, list[bytes32]] = defaultdict(list)
        coins_by_spent_height: dict[int, list[bytes32]] = defaultdict(list)
        coins_processed = 0
        last_log_time = time.monotonic()
        last_log_count = 0

        async for coin_name, coin_record in iterate_all_coins(rocks_db):
            coins_processed += 1
            current_time = time.monotonic()

            # Log progress every 10000 coins or every 5 seconds
            if coins_processed % 10000 == 0 or (current_time - last_log_time) >= 5.0:
                rate = (coins_processed - last_log_count) / max(1, current_time - last_log_time)
                log.info(f"Phase 4b: Processed {coins_processed:,} coins (rate: {rate:.1f} coins/sec)")
                last_log_time = current_time
                last_log_count = coins_processed

            if coin_record is None:
                continue

            if coin_record.confirmed_block_index in heights_with_mismatches:
                coins_by_created_height[coin_record.confirmed_block_index].append(coin_name)

            if coin_record.spent_block_index in heights_with_mismatches:
                coins_by_spent_height[coin_record.spent_block_index].append(coin_name)

        # Compare block info vs actual coins for each problematic height
        log.info("Phase 4c: Identifying specific problematic coins...")
        for height in sorted(heights_with_mismatches):
            if height not in problematic_block_infos:
                continue

            block_info = problematic_block_infos[height]
            block_created_set = set(block_info.created_coins)
            block_spent_set = set(block_info.spent_coins)
            actual_created_set = set(coins_by_created_height.get(height, []))
            actual_spent_set = set(coins_by_spent_height.get(height, []))

            # Find coins that should be created but aren't
            missing_created = block_created_set - actual_created_set
            for coin_name in missing_created:
                if (height, coin_name) not in results.missing_created_coins:
                    results.missing_created_coins.append((height, coin_name))
                    log.error(f"Height {height}: Created coin {coin_name.hex()} missing from coin store")

            # Find coins that are created but shouldn't be
            extra_created = actual_created_set - block_created_set
            for coin_name in extra_created:
                results.wrong_state_coins.append(
                    (
                        coin_name,
                        f"not in created_coins at height {height}",
                        f"confirmed_block_index={height}",
                    )
                )
                log.error(
                    f"Height {height}: Coin {coin_name.hex()} has confirmed_block_index={height} "
                    f"but is not in block's created_coins"
                )

            # Find coins that should be spent but aren't
            missing_spent = block_spent_set - actual_spent_set
            for coin_name in missing_spent:
                if (height, coin_name) not in results.missing_spent_coins:
                    results.missing_spent_coins.append((height, coin_name))
                    log.error(f"Height {height}: Spent coin {coin_name.hex()} missing from coin store")

            # Find coins that are spent but shouldn't be
            extra_spent = actual_spent_set - block_spent_set
            for coin_name in extra_spent:
                results.wrong_state_coins.append(
                    (
                        coin_name,
                        f"not in spent_coins at height {height}",
                        f"spent_block_index={height}",
                    )
                )
                log.error(
                    f"Height {height}: Coin {coin_name.hex()} has spent_block_index={height} "
                    f"but is not in block's spent_coins"
                )

            # Log summary
            if missing_created or extra_created or missing_spent or extra_spent:
                log.warning(
                    f"Height {height} detailed analysis: "
                    f"created: {len(missing_created)} missing, {len(extra_created)} extra; "
                    f"spent: {len(missing_spent)} missing, {len(extra_spent)} extra"
                )

    log.info("Fsck complete!")
    return results


def print_results(results: FsckResults) -> None:
    """Print a summary of fsck results."""
    print("\n" + "=" * 80)
    print("FSCK RESULTS SUMMARY")
    print("=" * 80)
    print(f"\nTotal blocks checked: {results.total_blocks}")
    print(f"Total coins in store: {results.total_coins}")
    print(f"Total created coins: {results.total_created}")
    print(f"Total spent coins: {results.total_spent}")

    print("\n" + "-" * 80)
    print("ISSUES FOUND:")
    print("-" * 80)

    issues_found = False

    if results.missing_created_coins:
        issues_found = True
        print(f"\n❌ Missing Created Coins: {len(results.missing_created_coins)}")
        for height, coin_name in results.missing_created_coins[:10]:
            print(f"  Height {height}: {coin_name.hex()}")
        if len(results.missing_created_coins) > 10:
            print(f"  ... and {len(results.missing_created_coins) - 10} more")

    if results.missing_spent_coins:
        issues_found = True
        print(f"\n❌ Missing Spent Coins: {len(results.missing_spent_coins)}")
        for height, coin_name in results.missing_spent_coins[:10]:
            print(f"  Height {height}: {coin_name.hex()}")
        if len(results.missing_spent_coins) > 10:
            print(f"  ... and {len(results.missing_spent_coins) - 10} more")

    if results.orphaned_coins:
        issues_found = True
        print(f"\n⚠️  Orphaned Coins: {len(results.orphaned_coins)}")
        for coin_name in results.orphaned_coins[:10]:
            print(f"  {coin_name.hex()}")
        if len(results.orphaned_coins) > 10:
            print(f"  ... and {len(results.orphaned_coins) - 10} more")

    if results.wrong_state_coins:
        issues_found = True
        print(f"\n❌ Wrong State Coins: {len(results.wrong_state_coins)}")
        for coin_name, expected, actual in results.wrong_state_coins[:10]:
            print(f"  {coin_name.hex()}: expected {expected}, got {actual}")
        if len(results.wrong_state_coins) > 10:
            print(f"  ... and {len(results.wrong_state_coins) - 10} more")

    if results.duplicate_blocks:
        issues_found = True
        print(f"\n⚠️  Duplicate Blocks: {len(results.duplicate_blocks)}")
        print(f"  Heights: {results.duplicate_blocks[:20]}")

    if results.missing_blocks:
        issues_found = True
        print(f"\n⚠️  Missing Blocks: {len(results.missing_blocks)}")
        print(f"  Heights: {results.missing_blocks[:20]}")
        if len(results.missing_blocks) > 20:
            print(f"  ... and {len(results.missing_blocks) - 20} more")

    if results.corrupted_coin_records:
        issues_found = True
        print(f"\n❌ Corrupted Coin Records: {len(results.corrupted_coin_records)}")
        for coin_name in results.corrupted_coin_records[:10]:
            print(f"  {coin_name.hex()}")
        if len(results.corrupted_coin_records) > 10:
            print(f"  ... and {len(results.corrupted_coin_records) - 10} more")

    if results.corrupted_block_infos:
        issues_found = True
        print(f"\n❌ Corrupted Block Infos: {len(results.corrupted_block_infos)}")
        print(f"  Count: {len(results.corrupted_block_infos)}")

    if not issues_found:
        print("\n✅ No issues found! Database appears consistent.")
    else:
        print("\n" + "=" * 80)
        print("⚠️  ISSUES DETECTED - Database may be inconsistent")
        print("=" * 80)

    print()


async def amain() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Filesystem check for CoinStore v3 (RocksDB)")
    parser.add_argument(
        "--db-path",
        type=Path,
        required=True,
        help="Path to the database directory (should contain .rocksdb subdirectory)",
    )
    parser.add_argument(
        "--max-height",
        type=int,
        default=None,
        help="Maximum block height to check (default: all)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    db_path = args.db_path
    if db_path.is_file():
        # If it's a file, assume it's the .rocksdb file itself
        rocks_db_path = db_path
    else:
        # If it's a directory, look for .rocksdb file or directory
        rocks_db_path = db_path.with_suffix(".rocksdb")
        if not rocks_db_path.exists():
            # Try as directory
            rocks_db_path = db_path / ".rocksdb"
            if not rocks_db_path.exists():
                log.error(f"RocksDB not found at {rocks_db_path}")
                sys.exit(1)

    log.info(f"Opening RocksDB at {rocks_db_path}")

    try:
        rocks_db = DB(str(rocks_db_path))
    except Exception as e:
        log.error(f"Failed to open RocksDB: {e}")
        sys.exit(1)

    try:
        results = await fsck_coin_store(rocks_db, max_height=args.max_height)
        print_results(results)

        # Exit with error code if issues found
        if (
            results.missing_created_coins
            or results.missing_spent_coins
            or results.wrong_state_coins
            or results.corrupted_coin_records
            or results.corrupted_block_infos
        ):
            sys.exit(1)
    finally:
        del rocks_db


def main() -> None:
    """Entry point for console script."""
    asyncio.run(amain())


if __name__ == "__main__":
    main()
