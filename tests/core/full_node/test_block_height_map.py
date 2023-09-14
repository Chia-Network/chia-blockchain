from __future__ import annotations

import struct
from pathlib import Path
from typing import Optional

import pytest

from chia.full_node.block_height_map import BlockHeightMap, SesCache
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.util.db_wrapper import DBWrapper2
from chia.util.files import write_file_async
from chia.util.ints import uint8, uint32
from tests.util.db_connection import DBConnection


def gen_block_hash(height: int) -> bytes32:
    return bytes32(struct.pack(">I", height + 1) * (32 // 4))


def gen_ses(height: int) -> SubEpochSummary:
    prev_ses = gen_block_hash(height + 0xFA0000)
    reward_chain_hash = gen_block_hash(height + 0xFC0000)
    return SubEpochSummary(prev_ses, reward_chain_hash, uint8(0), None, None)


async def new_block(
    db: DBWrapper2, block_hash: bytes32, parent: bytes32, height: int, is_peak: bool, ses: Optional[SubEpochSummary]
) -> None:
    async with db.writer_maybe_transaction() as conn:
        cursor = await conn.execute(
            "INSERT INTO full_blocks VALUES(?, ?, ?, ?, ?)",
            (
                block_hash,
                parent,
                height,
                True,  # in_main_chain
                # sub epoch summary
                None if ses is None else bytes(ses),
            ),
        )
        await cursor.close()
        if is_peak:
            cursor = await conn.execute("INSERT OR REPLACE INTO current_peak VALUES(?, ?)", (0, block_hash))
            await cursor.close()


async def setup_db(db: DBWrapper2) -> None:
    async with db.writer_maybe_transaction() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS full_blocks("
            "header_hash blob PRIMARY KEY,"
            "prev_hash blob,"
            "height bigint,"
            "in_main_chain tinyint,"
            "sub_epoch_summary blob)"
        )
        await conn.execute("CREATE TABLE IF NOT EXISTS current_peak(key int PRIMARY KEY, hash blob)")

        await conn.execute("CREATE INDEX IF NOT EXISTS height on full_blocks(height)")
        await conn.execute("CREATE INDEX IF NOT EXISTS hh on full_blocks(header_hash)")


# if chain_id != 0, the last block in the chain won't be considered the peak,
# and the chain_id will be mixed in to the hashes, to form a separate chain at
# the same heights as the main chain
async def setup_chain(
    db: DBWrapper2, length: int, *, chain_id: int = 0, ses_every: Optional[int] = None, start_height: int = 0
) -> None:
    height = start_height
    peak_hash = gen_block_hash(height + chain_id * 65536)
    parent_hash = bytes32([0] * 32)
    while height < length:
        ses = None
        if ses_every is not None and height % ses_every == 0:
            ses = gen_ses(height)

        await new_block(db, peak_hash, parent_hash, height, False, ses)
        height += 1
        parent_hash = peak_hash
        peak_hash = gen_block_hash(height + chain_id * 65536)

    # we only set is_peak=1 for chain_id 0
    await new_block(db, peak_hash, parent_hash, height, chain_id == 0, None)


class TestBlockHeightMap:
    @pytest.mark.asyncio
    async def test_height_to_hash(self, tmp_dir: Path, db_version: int) -> None:
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            assert not height_map.contains_height(uint32(11))
            for height in reversed(range(10)):
                assert height_map.contains_height(uint32(height))

            for height in reversed(range(10)):
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)

    @pytest.mark.asyncio
    async def test_height_to_hash_long_chain(self, tmp_dir: Path, db_version: int) -> None:
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10000)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            for height in reversed(range(1000)):
                assert height_map.contains_height(uint32(height))

            for height in reversed(range(10000)):
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)

    @pytest.mark.asyncio
    async def test_save_restore(self, tmp_dir: Path, db_version: int) -> None:
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10000, ses_every=20)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            for height in reversed(range(10000)):
                assert height_map.contains_height(uint32(height))
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)
                if (height % 20) == 0:
                    assert height_map.get_ses(uint32(height)) == gen_ses(height)
                else:
                    with pytest.raises(KeyError) as _:
                        height_map.get_ses(uint32(height))

            await height_map.maybe_flush()

            del height_map

            # To ensure we're actually loading from cache, and not the DB, clear
            # the table (but we still need the peak). We need at least 20 blocks
            # in the DB since we keep loading until we find a match of both hash
            # and sub epoch summary. In this test we have a sub epoch summary
            # every 20 blocks, so we generate the 30 last blocks only
            async with db_wrapper.writer_maybe_transaction() as conn:
                await conn.execute("DROP TABLE full_blocks")
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10000, ses_every=20, start_height=9970)
            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            for height in reversed(range(10000)):
                assert height_map.contains_height(uint32(height))
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)
                if (height % 20) == 0:
                    assert height_map.get_ses(uint32(height)) == gen_ses(height)
                else:
                    with pytest.raises(KeyError) as _:
                        height_map.get_ses(uint32(height))

    @pytest.mark.asyncio
    async def test_restore_entire_chain(self, tmp_dir: Path, db_version: int) -> None:
        # this is a test where the height-to-hash and height-to-ses caches are
        # entirely unrelated to the database. Make sure they can both be fully
        # replaced
        async with DBConnection(db_version) as db_wrapper:
            heights = bytearray(900 * 32)
            for i in range(900):
                idx = i * 32
                heights[idx : idx + 32] = bytes([i % 256] * 32)

            await write_file_async(tmp_dir / "height-to-hash", heights)

            ses_cache = []
            for i in range(0, 900, 19):
                ses_cache.append((uint32(i), bytes(gen_ses(i + 9999))))

            await write_file_async(tmp_dir / "sub-epoch-summaries", bytes(SesCache(ses_cache)))

            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10000, ses_every=20)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            for height in reversed(range(10000)):
                assert height_map.contains_height(uint32(height))
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)
                if (height % 20) == 0:
                    assert height_map.get_ses(uint32(height)) == gen_ses(height)
                else:
                    with pytest.raises(KeyError) as _:
                        height_map.get_ses(uint32(height))

    @pytest.mark.asyncio
    async def test_restore_ses_only(self, tmp_dir: Path, db_version: int) -> None:
        # this is a test where the height-to-hash is complete and correct but
        # sub epoch summaries are missing. We need to be able to restore them in
        # this case.
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 2000, ses_every=20)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)
            await height_map.maybe_flush()
            del height_map

            # corrupt the sub epoch cache
            ses_cache = []
            for i in range(0, 2000, 19):
                ses_cache.append((uint32(i), bytes(gen_ses(i + 9999))))

            await write_file_async(tmp_dir / "sub-epoch-summaries", bytes(SesCache(ses_cache)))

            # the test starts here
            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            for height in reversed(range(2000)):
                assert height_map.contains_height(uint32(height))
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)
                if (height % 20) == 0:
                    assert height_map.get_ses(uint32(height)) == gen_ses(height)
                else:
                    with pytest.raises(KeyError) as _:
                        height_map.get_ses(uint32(height))

    @pytest.mark.asyncio
    async def test_restore_extend(self, tmp_dir: Path, db_version: int) -> None:
        # test the case where the cache has fewer blocks than the DB, and that
        # we correctly load all the missing blocks from the DB to update the
        # cache
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 2000, ses_every=20)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            for height in reversed(range(2000)):
                assert height_map.contains_height(uint32(height))
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)
                if (height % 20) == 0:
                    assert height_map.get_ses(uint32(height)) == gen_ses(height)
                else:
                    with pytest.raises(KeyError) as _:
                        height_map.get_ses(uint32(height))

            await height_map.maybe_flush()

            del height_map

        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            # add 2000 blocks to the chain
            await setup_chain(db_wrapper, 4000, ses_every=20)
            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            # now make sure we have the complete chain, height 0 -> 4000
            for height in reversed(range(4000)):
                assert height_map.contains_height(uint32(height))
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)
                if (height % 20) == 0:
                    assert height_map.get_ses(uint32(height)) == gen_ses(height)
                else:
                    with pytest.raises(KeyError) as _:
                        height_map.get_ses(uint32(height))

    @pytest.mark.asyncio
    async def test_height_to_hash_with_orphans(self, tmp_dir: Path, db_version: int) -> None:
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10)

            # set up two separate chains, but without the peak
            await setup_chain(db_wrapper, 10, chain_id=1)
            await setup_chain(db_wrapper, 10, chain_id=2)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            for height in range(10):
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)

    @pytest.mark.asyncio
    async def test_height_to_hash_update(self, tmp_dir: Path, db_version: int) -> None:
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10)

            # orphan blocks
            await setup_chain(db_wrapper, 10, chain_id=1)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            for height in range(10):
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)

            height_map.update_height(uint32(10), gen_block_hash(100), None)

            for height in range(9):
                assert height_map.get_hash(uint32(height)) == gen_block_hash(height)

            assert height_map.get_hash(uint32(10)) == gen_block_hash(100)

    @pytest.mark.asyncio
    async def test_update_ses(self, tmp_dir: Path, db_version: int) -> None:
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10)

            # orphan blocks
            await setup_chain(db_wrapper, 10, chain_id=1)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            with pytest.raises(KeyError) as _:
                height_map.get_ses(uint32(10))

            height_map.update_height(uint32(10), gen_block_hash(10), gen_ses(10))

            assert height_map.get_ses(uint32(10)) == gen_ses(10)
            assert height_map.get_hash(uint32(10)) == gen_block_hash(10)

    @pytest.mark.asyncio
    async def test_height_to_ses(self, tmp_dir: Path, db_version: int) -> None:
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10, ses_every=2)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            assert height_map.get_ses(uint32(0)) == gen_ses(0)
            assert height_map.get_ses(uint32(2)) == gen_ses(2)
            assert height_map.get_ses(uint32(4)) == gen_ses(4)
            assert height_map.get_ses(uint32(6)) == gen_ses(6)
            assert height_map.get_ses(uint32(8)) == gen_ses(8)

            with pytest.raises(KeyError) as _:
                height_map.get_ses(uint32(1))
            with pytest.raises(KeyError) as _:
                height_map.get_ses(uint32(3))
            with pytest.raises(KeyError) as _:
                height_map.get_ses(uint32(5))
            with pytest.raises(KeyError) as _:
                height_map.get_ses(uint32(7))
            with pytest.raises(KeyError) as _:
                height_map.get_ses(uint32(9))

    @pytest.mark.asyncio
    async def test_rollback(self, tmp_dir: Path, db_version: int) -> None:
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10, ses_every=2)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            assert height_map.get_ses(uint32(0)) == gen_ses(0)
            assert height_map.get_ses(uint32(2)) == gen_ses(2)
            assert height_map.get_ses(uint32(4)) == gen_ses(4)
            assert height_map.get_ses(uint32(6)) == gen_ses(6)
            assert height_map.get_ses(uint32(8)) == gen_ses(8)

            assert height_map.get_hash(uint32(5)) == gen_block_hash(5)

            height_map.rollback(5)
            assert height_map.contains_height(uint32(0))
            assert height_map.contains_height(uint32(1))
            assert height_map.contains_height(uint32(2))
            assert height_map.contains_height(uint32(3))
            assert height_map.contains_height(uint32(4))
            assert height_map.contains_height(uint32(5))
            assert not height_map.contains_height(uint32(6))
            assert not height_map.contains_height(uint32(7))
            assert not height_map.contains_height(uint32(8))
            assert height_map.get_hash(uint32(5)) == gen_block_hash(5)

            assert height_map.get_ses(uint32(0)) == gen_ses(0)
            assert height_map.get_ses(uint32(2)) == gen_ses(2)
            assert height_map.get_ses(uint32(4)) == gen_ses(4)
            with pytest.raises(KeyError) as _:
                height_map.get_ses(uint32(6))
            with pytest.raises(KeyError) as _:
                height_map.get_ses(uint32(8))

    @pytest.mark.asyncio
    async def test_rollback2(self, tmp_dir: Path, db_version: int) -> None:
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10, ses_every=2)

            height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

            assert height_map.get_ses(uint32(0)) == gen_ses(0)
            assert height_map.get_ses(uint32(2)) == gen_ses(2)
            assert height_map.get_ses(uint32(4)) == gen_ses(4)
            assert height_map.get_ses(uint32(6)) == gen_ses(6)
            assert height_map.get_ses(uint32(8)) == gen_ses(8)

            assert height_map.get_hash(uint32(6)) == gen_block_hash(6)

            height_map.rollback(6)
            assert height_map.contains_height(uint32(6))
            assert not height_map.contains_height(uint32(7))

            assert height_map.get_hash(uint32(6)) == gen_block_hash(6)
            with pytest.raises(AssertionError) as _:
                height_map.get_hash(uint32(7))

            assert height_map.get_ses(uint32(0)) == gen_ses(0)
            assert height_map.get_ses(uint32(2)) == gen_ses(2)
            assert height_map.get_ses(uint32(4)) == gen_ses(4)
            assert height_map.get_ses(uint32(6)) == gen_ses(6)
            with pytest.raises(KeyError) as _:
                height_map.get_ses(uint32(8))

    @pytest.mark.asyncio
    async def test_cache_file_nothing_to_write(self, tmp_dir: Path, db_version: int) -> None:
        # This is a test where the height-to-hash data is entirely used from
        # the cache file and there is nothing to write in that file as a result.
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10000, ses_every=20)
            await BlockHeightMap.create(tmp_dir, db_wrapper)
            # To ensure we're actually loading from cache, and not the DB, clear
            # the table.
            async with db_wrapper.writer_maybe_transaction() as conn:
                await conn.execute("DELETE FROM full_blocks")
            await setup_chain(db_wrapper, 10000, ses_every=20, start_height=9970)
            # At this point we should have a proper cache file
            with open(tmp_dir / "height-to-hash", "rb") as f:
                heights = bytearray(f.read())
                assert len(heights) == (10000 + 1) * 32
            await BlockHeightMap.create(tmp_dir, db_wrapper)
            # Make sure we didn't alter the cache (nothing new to write)
            with open(tmp_dir / "height-to-hash", "rb") as f:
                # pytest doesn't behave very well comparing large buffers
                # (when the test fails). Compare small portions at a time instead
                new_heights = f.read()
                assert len(new_heights) == len(heights)
                for idx in range(0, len(heights), 32):
                    assert new_heights[idx : idx + 32] == heights[idx : idx + 32]

    @pytest.mark.asyncio
    async def test_cache_file_replace_everything(self, tmp_dir: Path, db_version: int) -> None:
        # This is a test where the height-to-hash is entirely unrelated to the
        # database. Make sure it can be fully replaced
        async with DBConnection(db_version) as db_wrapper:
            heights = bytearray(900 * 32)
            for i in range(900):
                idx = i * 32
                heights[idx : idx + 32] = bytes([i % 256] * 32)
            await write_file_async(tmp_dir / "height-to-hash", heights)
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 10000, ses_every=20)
            await BlockHeightMap.create(tmp_dir, db_wrapper)
            # We replaced the whole cache at this point so all values should be different
            with open(tmp_dir / "height-to-hash", "rb") as f:
                new_heights = bytearray(f.read())
                # Make sure we wrote the whole file
                assert len(new_heights) == (10000 + 1) * 32
                # Make sure none of the old values remain
                for i in range(0, len(heights), 32):
                    assert new_heights[i : i + 32] != heights[i : i + 32]

    @pytest.mark.asyncio
    async def test_cache_file_extend(self, tmp_dir: Path, db_version: int) -> None:
        # Test the case where the cache has fewer blocks than the DB, and that
        # we correctly load all the missing blocks from the DB to update the
        # cache
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            await setup_chain(db_wrapper, 2000, ses_every=20)
            await BlockHeightMap.create(tmp_dir, db_wrapper)
        async with DBConnection(db_version) as db_wrapper:
            await setup_db(db_wrapper)
            # Add 2000 blocks to the chain
            await setup_chain(db_wrapper, 4000, ses_every=20)
            # At this point we should have a proper cache with the old chain data
            with open(tmp_dir / "height-to-hash", "rb") as f:
                heights = f.read()
                assert len(heights) == (2000 + 1) * 32
            await BlockHeightMap.create(tmp_dir, db_wrapper)
            # Make sure we properly wrote the additional data to the cache
            with open(tmp_dir / "height-to-hash", "rb") as f:
                new_heights = f.read()
                assert len(new_heights) == (4000 + 1) * 32
                # pytest doesn't behave very well comparing large buffers
                # (when the test fails). Compare small portions at a time instead
                for idx in range(0, len(heights), 32):
                    assert new_heights[idx : idx + 32] == heights[idx : idx + 32]


@pytest.mark.asyncio
async def test_unsupported_version(tmp_dir: Path) -> None:
    with pytest.raises(RuntimeError, match="BlockHeightMap does not support database schema v1"):
        async with DBConnection(1) as db_wrapper:
            await BlockHeightMap.create(tmp_dir, db_wrapper)


@pytest.mark.asyncio
async def test_empty_chain(tmp_dir: Path, db_version: int) -> None:
    async with DBConnection(db_version) as db_wrapper:
        await setup_db(db_wrapper)

        height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

        with pytest.raises(KeyError) as _:
            height_map.get_ses(uint32(0))

        with pytest.raises(AssertionError) as _:
            height_map.get_hash(uint32(0))


@pytest.mark.asyncio
async def test_peak_only_chain(tmp_dir: Path, db_version: int) -> None:
    async with DBConnection(db_version) as db_wrapper:
        await setup_db(db_wrapper)

        async with db_wrapper.writer_maybe_transaction() as conn:
            cursor = await conn.execute(
                "INSERT OR REPLACE INTO current_peak VALUES(?, ?)", (0, b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
            )
            await cursor.close()

        height_map = await BlockHeightMap.create(tmp_dir, db_wrapper)

        with pytest.raises(KeyError) as _:
            height_map.get_ses(uint32(0))

        with pytest.raises(AssertionError) as _:
            height_map.get_hash(uint32(0))
