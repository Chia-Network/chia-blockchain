from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from chia.consensus.block_record import BlockRecord, BlockRecordDB
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.util.config import load_config
from chia.util.full_block_utils import PlotFilterInfo, plot_filter_info_from_block
from chia.util.path import path_from_root


def db_validate_func(
    root_path: Path,
    in_db_path: Optional[Path] = None,
    *,
    validate_blocks: bool,
) -> None:
    if in_db_path is None:
        config: Dict[str, Any] = load_config(root_path, "config.yaml")["full_node"]
        selected_network: str = config["selected_network"]
        db_pattern: str = config["database_path"]
        db_path_replaced: str = db_pattern.replace("CHALLENGE", selected_network)
        in_db_path = path_from_root(root_path, db_path_replaced)

    validate_v2(in_db_path, validate_blocks=validate_blocks)

    print(f"\n\nDATABASE IS VALID: {in_db_path}\n")


def validate_v2(in_path: Path, *, validate_blocks: bool) -> None:
    import sqlite3
    from contextlib import closing

    import zstd

    if not in_path.exists():
        print(f"input file doesn't exist. {in_path}")
        raise RuntimeError(f"can't find {in_path}")

    print(f"opening file for reading: {in_path}")
    with closing(sqlite3.connect(in_path)) as in_db:
        # read the database version
        try:
            with closing(in_db.execute("SELECT * FROM database_version")) as cursor:
                row = cursor.fetchone()
                if row is None or row == []:
                    raise RuntimeError("Database is missing version field")
                if row[0] != 2:
                    raise RuntimeError(f"Database has the wrong version ({row[0]} expected 2)")
        except sqlite3.OperationalError:
            raise RuntimeError("Database is missing version table")

        try:
            with closing(in_db.execute("SELECT hash FROM current_peak WHERE key = 0")) as cursor:
                row = cursor.fetchone()
                if row is None or row == []:
                    raise RuntimeError("Database is missing current_peak field")
                peak = bytes32(row[0])
        except sqlite3.OperationalError:
            raise RuntimeError("Database is missing current_peak table")

        print(f"peak hash: {peak}")

        with closing(in_db.execute("SELECT height FROM full_blocks WHERE header_hash = ?", (peak,))) as cursor:
            peak_row = cursor.fetchone()
            if peak_row is None or peak_row == []:
                raise RuntimeError("Database is missing the peak block")
            peak_height = peak_row[0]

        print(f"peak height: {peak_height}")

        print("traversing the full chain")

        current_height = peak_height
        # we're looking for a block with this hash
        expect_hash = peak
        # once we find it, we know what the next block to look for is, which
        # this is set to
        next_hash = None

        num_orphans = 0
        height_to_hash = bytearray(peak_height * 32)

        with closing(
            in_db.execute(
                f"SELECT header_hash, prev_hash, height, in_main_chain"
                f"{', block, block_record' if validate_blocks else ''} "
                "FROM full_blocks ORDER BY height DESC"
            )
        ) as cursor:
            for row in cursor:
                hh = row[0]
                prev = row[1]
                height = row[2]
                in_main_chain = row[3]

                # if there are blocks being added to the database, just ignore
                # the ones added since we picked the peak
                if height > peak_height:
                    continue

                if validate_blocks:
                    block_bytes = zstd.decompress(row[4])
                    block = FullBlock.from_bytes(block_bytes)
                    block_record_db: BlockRecordDB = BlockRecordDB.from_bytes(row[5])
                    plot_filter_info: PlotFilterInfo = plot_filter_info_from_block(block_bytes)
                    block_record = BlockRecord.from_block_record_db(
                        block_record_db,
                        plot_filter_info.pos_ss_cc_challenge_hash,
                        plot_filter_info.cc_sp_hash,
                    )
                    actual_header_hash = block.header_hash
                    actual_prev_hash = block.prev_header_hash
                    if actual_header_hash != hh:
                        raise RuntimeError(
                            f"Block {hh.hex()} has a blob with mismatching hash: {actual_header_hash.hex()}"
                        )
                    if block_record.header_hash != hh:
                        raise RuntimeError(
                            f"Block {hh.hex()} has a block record with mismatching "
                            f"hash: {block_record.header_hash.hex()}"
                        )
                    if block_record.total_iters != block.total_iters:
                        raise RuntimeError(
                            f"Block {hh.hex()} has a block record with mismatching total "
                            f"iters: {block_record.total_iters} expected {block.total_iters}"
                        )
                    if block_record.prev_hash != actual_prev_hash:
                        raise RuntimeError(
                            f"Block {hh.hex()} has a block record with mismatching "
                            f"prev_hash: {block_record.prev_hash} expected {actual_prev_hash.hex()}"
                        )
                    if block.height != height:
                        raise RuntimeError(
                            f"Block {hh.hex()} has a mismatching height: {block.height} expected {height}"
                        )
                    if block_record.pos_ss_cc_challenge_hash != block.reward_chain_block.pos_ss_cc_challenge_hash:
                        raise RuntimeError(
                            f"Did not parse field pos_ss_cc_challenge_hash of block {hh.hex()} correctly: "
                            f"{block_record.pos_ss_cc_challenge_hash} "
                            f"expected {block.reward_chain_block.pos_ss_cc_challenge_hash}"
                        )
                    if block.reward_chain_block.challenge_chain_sp_vdf is None:
                        expected_cc_sp_hash: bytes32 = block.reward_chain_block.pos_ss_cc_challenge_hash
                    else:
                        expected_cc_sp_hash = block.reward_chain_block.challenge_chain_sp_vdf.output.get_hash()
                    if block_record.cc_sp_hash != expected_cc_sp_hash:
                        raise RuntimeError(
                            f"Did not parse field cc_sp_hash of block {hh.hex()} correctly: "
                            f"{block_record.pos_ss_cc_challenge_hash} expected {expected_cc_sp_hash}"
                        )

                if height != current_height:
                    # we're moving to the next level. Make sure we found the block
                    # we were looking for at the previous level
                    if next_hash is None:
                        raise RuntimeError(
                            f"Database is missing the block with hash {expect_hash} at height {current_height}"
                        )
                    expect_hash = next_hash
                    next_hash = None
                    current_height = height

                if hh == expect_hash:
                    if next_hash is not None:
                        raise RuntimeError(f"Database has multiple blocks with hash {hh.hex()}, at height {height}")
                    if not in_main_chain:
                        raise RuntimeError(
                            f"block {hh.hex()} (height: {height}) is part of the main chain, "
                            f"but in_main_chain is not set"
                        )

                    if validate_blocks:
                        if actual_prev_hash != prev:
                            raise RuntimeError(
                                f"Block {hh.hex()} has a blob with mismatching "
                                f"prev-hash: {actual_prev_hash}, expected {prev}"
                            )

                    next_hash = prev

                    height_to_hash[height * 32 : height * 32 + 32] = hh

                    print(f"\r{height} orphaned blocks: {num_orphans} ", end="")

                else:
                    if in_main_chain:
                        raise RuntimeError(f"block {hh.hex()} (height: {height}) is orphaned, but in_main_chain is set")
                    num_orphans += 1
        print("")

        if current_height != 0:
            raise RuntimeError(f"Database is missing blocks below height {current_height}")

        # make sure the prev_hash pointer of block height 0 is the genesis
        # challenge
        if next_hash != DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA:
            raise RuntimeError(
                f"Blockchain has invalid genesis challenge {next_hash}, expected "
                f"{DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA.hex()}"
            )

        if num_orphans > 0:
            print(f"{num_orphans} orphaned blocks")
