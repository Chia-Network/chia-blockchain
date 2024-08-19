from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiofiles

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
from chia.util.db_wrapper import DBWrapper2
from chia.util.files import write_file_async
from chia.util.ints import uint32
from chia.util.streamable import Streamable, streamable

log = logging.getLogger(__name__)


@streamable
@dataclass(frozen=True)
class SesCache(Streamable):
    content: List[Tuple[uint32, bytes]]


class BlockHeightMap:
    db: DBWrapper2

    # the below dictionaries are loaded from the database, from the peak
    # and back in time on startup.

    # Defines the path from genesis to the peak, no orphan blocks
    # this buffer contains all block hashes that are part of the current peak
    # ordered by height. i.e. __height_to_hash[0..32] is the genesis hash
    # __height_to_hash[32..64] is the hash for height 1 and so on
    __height_to_hash: bytearray

    # All sub-epoch summaries that have been included in the blockchain from the beginning until and including the peak
    # (height_included, SubEpochSummary). Note: ONLY for the blocks in the path to the peak
    # The value is a serialized SubEpochSummary object
    __sub_epoch_summaries: Dict[uint32, bytes]

    # count how many blocks have been added since the cache was last written to
    # disk
    __counter: int

    # this is the lowest height whose hash has been updated since the last flush
    # to disk. When it's time to write to disk, we can start flushing from this
    # offset
    __first_dirty: int

    # the file we're saving the height-to-hash cache to
    __height_to_hash_filename: Path

    # the file we're saving the sub epoch summary cache to
    __ses_filename: Path

    @classmethod
    async def create(cls, blockchain_dir: Path, db: DBWrapper2) -> BlockHeightMap:
        if db.db_version != 2:
            raise RuntimeError(f"BlockHeightMap does not support database schema v{db.db_version}")
        self = BlockHeightMap()
        self.db = db

        self.__counter = 0
        self.__first_dirty = 0
        self.__height_to_hash = bytearray()
        self.__sub_epoch_summaries = {}
        self.__height_to_hash_filename = blockchain_dir / "height-to-hash"
        self.__ses_filename = blockchain_dir / "sub-epoch-summaries"

        async with self.db.reader_no_transaction() as conn:
            async with conn.execute("SELECT hash FROM current_peak WHERE key = 0") as cursor:
                peak_row = await cursor.fetchone()
                if peak_row is None:
                    log.info("blockchain database is missing a peak. Not loading height-to-hash or sub-epoch-summaries")
                    return self

            async with conn.execute(
                "SELECT header_hash,prev_hash,height,sub_epoch_summary FROM full_blocks WHERE header_hash=?",
                (peak_row[0],),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    log.info("blockchain database is missing blocks. Not loading height-to-hash or sub-epoch-summaries")
                    return self

        try:
            async with aiofiles.open(self.__height_to_hash_filename, "rb") as f:
                self.__height_to_hash = bytearray(await f.read())
        except Exception as e:
            # it's OK if this file doesn't exist, we can rebuild it
            log.info(f"Failed to load height-to-hash: {e}")
            pass

        try:
            async with aiofiles.open(self.__ses_filename, "rb") as f:
                self.__sub_epoch_summaries = {k: v for (k, v) in SesCache.from_bytes(await f.read()).content}
        except Exception as e:
            # it's OK if this file doesn't exist, we can rebuild it
            log.info(f"Failed to load sub-epoch-summaries: {e}")
            pass

        peak: bytes32 = row[0]
        prev_hash: bytes32 = row[1]
        height = row[2]

        # allocate memory for height to hash map
        # this may also truncate it, if thie file on disk had an invalid size
        new_size = (height + 1) * 32
        size = len(self.__height_to_hash)
        if size > new_size:
            del self.__height_to_hash[new_size:]
        else:
            self.__height_to_hash += bytearray([0] * (new_size - size))

        self.__first_dirty = height + 1

        if self.get_hash(height) != peak:
            self.__set_hash(height, peak)

        if row[3] is not None:
            self.__sub_epoch_summaries[height] = row[3]

        log.info(
            f"Loaded sub-epoch-summaries: {len(self.__sub_epoch_summaries)} "
            f"height-to-hash: {len(self.__height_to_hash)//32}"
        )

        # prepopulate the height -> hash mapping
        # run this unconditionally in to ensure both the height-to-hash and sub
        # epoch summaries caches are in sync with the DB
        await self._load_blocks_from(height, prev_hash)

        await self.maybe_flush()

        return self

    def update_height(self, height: uint32, header_hash: bytes32, ses: Optional[SubEpochSummary]) -> None:
        # we're only updating the last hash. If we've reorged, we already rolled
        # back, making this the new peak
        assert height * 32 <= len(self.__height_to_hash)
        self.__set_hash(height, header_hash)
        if ses is not None:
            self.__sub_epoch_summaries[height] = bytes(ses)

    async def maybe_flush(self) -> None:
        if self.__counter < 1000:
            return

        assert (len(self.__height_to_hash) % 32) == 0
        offset = self.__first_dirty * 32

        ses_buf = bytes(SesCache([(k, v) for (k, v) in self.__sub_epoch_summaries.items()]))

        self.__counter = 0

        try:
            async with aiofiles.open(self.__height_to_hash_filename, "r+b") as f:
                map_buf = self.__height_to_hash[offset:].copy()
                await f.seek(offset)
                await f.write(map_buf)
        except Exception:
            # if the file doesn't exist, write the whole buffer
            async with aiofiles.open(self.__height_to_hash_filename, "wb") as f:
                map_buf = self.__height_to_hash.copy()
                await f.write(map_buf)

        self.__first_dirty = len(self.__height_to_hash) // 32
        await write_file_async(self.__ses_filename, ses_buf)

    # load height-to-hash map entries from the DB starting at height back in
    # time until we hit a match in the existing map, at which point we can
    # assume all previous blocks have already been populated
    # the first iteration is mandatory on each startup, so we make it load fewer
    # blocks to be fast. The common case is that the files are in sync with the
    # DB so iteration can stop early.
    async def _load_blocks_from(self, height: uint32, prev_hash: bytes32) -> None:
        # on mainnet, every 384th block has a sub-epoch summary. This should
        # guarantee that we find at least one in the first iteration. If it
        # matches, we're done reconciliating the cache with the DB.
        log.info(f"validating height-to-hash and sub-epoch-summaries. peak: {height}")
        window_size = 400
        while height > 0:
            # load 5000 blocks at a time
            window_end = max(0, height - window_size)
            window_size = 5000

            query = (
                "SELECT header_hash,prev_hash,height,sub_epoch_summary from full_blocks "
                "INDEXED BY height WHERE in_main_chain=1 AND height>=? AND height <?"
            )

            async with self.db.reader_no_transaction() as conn:
                async with conn.execute(query, (window_end, height)) as cursor:
                    # maps block-hash -> (height, prev-hash, sub-epoch-summary)
                    ordered: Dict[bytes32, Tuple[uint32, bytes32, Optional[bytes]]] = {}

                    for r in await cursor.fetchall():
                        ordered[r[0]] = (r[2], r[1], r[3])

            while height > window_end:
                if prev_hash not in ordered:
                    raise ValueError(
                        f"block with header hash is missing from your blockchain database: {prev_hash.hex()}"
                    )
                entry = ordered[prev_hash]
                assert height == entry[0] + 1
                height = entry[0]
                if entry[2] is not None:
                    if (
                        self.get_hash(height) == prev_hash
                        and height in self.__sub_epoch_summaries
                        and self.__sub_epoch_summaries[height] == entry[2]
                    ):
                        log.info(f"Done validating. height {height} matches")
                        # we only terminate the loop if we encounter a block
                        # that has a sub epoch summary matching the cache and
                        # the block hash matches the cache
                        return
                    self.__sub_epoch_summaries[height] = entry[2]
                elif height in self.__sub_epoch_summaries:
                    # if the database file was swapped out and the existing
                    # cache doesn't represent any of it at all, a missing sub
                    # epoch summary needs to be removed from the cache too
                    del self.__sub_epoch_summaries[height]
                self.__set_hash(height, prev_hash)
                prev_hash = entry[1]
            log.info(f"Done validating at height {height}")

    def __set_hash(self, height: int, block_hash: bytes32) -> None:
        idx = height * 32
        self.__height_to_hash[idx : idx + 32] = block_hash
        self.__counter += 1
        self.__first_dirty = min(self.__first_dirty, height)

    def get_hash(self, height: uint32) -> bytes32:
        idx = height * 32
        assert idx + 32 <= len(self.__height_to_hash)
        return bytes32(self.__height_to_hash[idx : idx + 32])

    def contains_height(self, height: uint32) -> bool:
        return height * 32 < len(self.__height_to_hash)

    def rollback(self, fork_height: int) -> None:
        # fork height may be -1, in which case all blocks are different and we
        # should clear all sub epoch summaries
        heights_to_delete = []

        for ses_included_height in self.__sub_epoch_summaries.keys():
            if ses_included_height > fork_height:
                heights_to_delete.append(ses_included_height)

        for height in heights_to_delete:
            del self.__sub_epoch_summaries[height]

        del self.__height_to_hash[(fork_height + 1) * 32 :]
        self.__first_dirty = min(self.__first_dirty, fork_height + 1)

        if len(heights_to_delete) > 0:
            log.log(
                logging.WARNING if fork_height < 100 else logging.INFO,
                f"rolling back {len(heights_to_delete)} blocks in "
                f"height-to-hash and sub-epoch-summaries cache, to height {fork_height}",
            )

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return SubEpochSummary.from_bytes(self.__sub_epoch_summaries[height])

    def get_ses_heights(self) -> List[uint32]:
        return sorted(self.__sub_epoch_summaries.keys())
