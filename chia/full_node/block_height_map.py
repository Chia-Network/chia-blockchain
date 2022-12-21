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
    __dirty: int

    # the file we're saving the height-to-hash cache to
    __height_to_hash_filename: Path

    # the file we're saving the sub epoch summary cache to
    __ses_filename: Path

    @classmethod
    async def create(cls, blockchain_dir: Path, db: DBWrapper2) -> "BlockHeightMap":
        self = BlockHeightMap()
        self.db = db

        self.__dirty = 0
        self.__height_to_hash = bytearray()
        self.__sub_epoch_summaries = {}
        self.__height_to_hash_filename = blockchain_dir / "height-to-hash"
        self.__ses_filename = blockchain_dir / "sub-epoch-summaries"

        async with self.db.reader_no_transaction() as conn:
            if db.db_version == 2:
                async with conn.execute("SELECT hash FROM current_peak WHERE key = 0") as cursor:
                    peak_row = await cursor.fetchone()
                    if peak_row is None:
                        return self

                async with conn.execute(
                    "SELECT header_hash,prev_hash,height,sub_epoch_summary FROM full_blocks WHERE header_hash=?",
                    (peak_row[0],),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row is None:
                        return self
            else:
                async with await conn.execute(
                    "SELECT header_hash,prev_hash,height,sub_epoch_summary from block_records WHERE is_peak=1"
                ) as cursor:
                    row = await cursor.fetchone()
                    if row is None:
                        return self

        try:
            async with aiofiles.open(self.__height_to_hash_filename, "rb") as f:
                self.__height_to_hash = bytearray(await f.read())
        except Exception:
            # it's OK if this file doesn't exist, we can rebuild it
            pass

        try:
            async with aiofiles.open(self.__ses_filename, "rb") as f:
                self.__sub_epoch_summaries = {k: v for (k, v) in SesCache.from_bytes(await f.read()).content}
        except Exception:
            # it's OK if this file doesn't exist, we can rebuild it
            pass

        peak: bytes32
        prev_hash: bytes32
        if db.db_version == 2:
            peak = row[0]
            prev_hash = row[1]
        else:
            peak = bytes32.fromhex(row[0])
            prev_hash = bytes32.fromhex(row[1])
        height = row[2]

        # allocate memory for height to hash map
        # this may also truncate it, if thie file on disk had an invalid size
        new_size = (height + 1) * 32
        size = len(self.__height_to_hash)
        if size > new_size:
            del self.__height_to_hash[new_size:]
        else:
            self.__height_to_hash += bytearray([0] * (new_size - size))

        # if the peak hash is already in the height-to-hash map, we don't need
        # to load anything more from the DB
        if self.get_hash(height) != peak:
            self.__set_hash(height, peak)

            if row[3] is not None:
                self.__sub_epoch_summaries[height] = row[3]

            # prepopulate the height -> hash mapping
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
        if self.__dirty < 1000:
            return

        assert (len(self.__height_to_hash) % 32) == 0
        map_buf = self.__height_to_hash.copy()

        ses_buf = bytes(SesCache([(k, v) for (k, v) in self.__sub_epoch_summaries.items()]))

        self.__dirty = 0

        await write_file_async(self.__height_to_hash_filename, map_buf)
        await write_file_async(self.__ses_filename, ses_buf)

    # load height-to-hash map entries from the DB starting at height back in
    # time until we hit a match in the existing map, at which point we can
    # assume all previous blocks have already been populated
    async def _load_blocks_from(self, height: uint32, prev_hash: bytes32) -> None:

        while height > 0:
            # load 5000 blocks at a time
            window_end = max(0, height - 5000)

            if self.db.db_version == 2:
                query = (
                    "SELECT header_hash,prev_hash,height,sub_epoch_summary from full_blocks "
                    "INDEXED BY height WHERE height>=? AND height <?"
                )
            else:
                query = (
                    "SELECT header_hash,prev_hash,height,sub_epoch_summary from block_records "
                    "INDEXED BY height WHERE height>=? AND height <?"
                )

            async with self.db.reader_no_transaction() as conn:
                async with conn.execute(query, (window_end, height)) as cursor:

                    # maps block-hash -> (height, prev-hash, sub-epoch-summary)
                    ordered: Dict[bytes32, Tuple[uint32, bytes32, Optional[bytes]]] = {}

                    if self.db.db_version == 2:
                        for r in await cursor.fetchall():
                            ordered[r[0]] = (r[2], r[1], r[3])
                    else:
                        for r in await cursor.fetchall():
                            ordered[bytes32.fromhex(r[0])] = (r[2], bytes32.fromhex(r[1]), r[3])

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
                        return
                    self.__sub_epoch_summaries[height] = entry[2]
                elif height in self.__sub_epoch_summaries:
                    # if the database file was swapped out and the existing
                    # cache doesn't represent any of it at all, a missing sub
                    # epoch summary needs to be removed from the cache too
                    del self.__sub_epoch_summaries[height]
                self.__set_hash(height, prev_hash)
                prev_hash = entry[1]

    def __set_hash(self, height: int, block_hash: bytes32) -> None:
        idx = height * 32
        self.__height_to_hash[idx : idx + 32] = block_hash
        self.__dirty += 1

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

    def get_ses(self, height: uint32) -> SubEpochSummary:
        return SubEpochSummary.from_bytes(self.__sub_epoch_summaries[height])

    def get_ses_heights(self) -> List[uint32]:
        return sorted(self.__sub_epoch_summaries.keys())
