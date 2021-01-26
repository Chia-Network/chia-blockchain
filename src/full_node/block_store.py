import logging
import aiosqlite
from typing import Dict, List, Optional, Tuple

from src.types.full_block import FullBlock
from src.types.header_block import HeaderBlock
from src.types.sized_bytes import bytes32
from src.types.sub_epoch_summary import SubEpochSummary
from src.types.weight_proof import SubEpochSegments, SubEpochChallengeSegment
from src.util.ints import uint32
from src.consensus.sub_block_record import SubBlockRecord

log = logging.getLogger(__name__)


class BlockStore:
    db: aiosqlite.Connection

    @classmethod
    async def create(cls, connection: aiosqlite.Connection):
        self = cls()

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.db = connection
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS full_blocks(header_hash text PRIMARY KEY, height bigint, sub_height bigint,"
            "  is_block tinyint, block blob)"
        )

        # Sub block records
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS sub_block_records(header_hash "
            "text PRIMARY KEY, prev_hash text, sub_height bigint,"
            "sub_block blob,sub_epoch_summary blob, is_peak tinyint, is_block tinyint)"
        )

        # Sub epoch segments for weight proofs
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS sub_epoch_segments(ses_sub_height bigint PRIMARY KEY, challenge_segments blob)"
        )

        # Height index so we can look up in order of height for sync purposes
        await self.db.execute("CREATE INDEX IF NOT EXISTS full_block_sub_height on full_blocks(sub_height)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS full_block_height on full_blocks(height)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS is_block on full_blocks(is_block)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS sub_block_sub_height on sub_block_records(sub_height)")

        await self.db.execute("CREATE INDEX IF NOT EXISTS hh on sub_block_records(header_hash)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS peak on sub_block_records(is_peak)")
        await self.db.execute("CREATE INDEX IF NOT EXISTS is_block on sub_block_records(is_block)")

        await self.db.commit()

        return self

    async def add_full_block(self, block: FullBlock, sub_block: SubBlockRecord) -> None:

        cursor_1 = await self.db.execute(
            "INSERT OR REPLACE INTO full_blocks VALUES(?, ?, ?, ?, ?)",
            (
                block.header_hash.hex(),
                sub_block.height,
                block.sub_block_height,
                int(block.is_block()),
                bytes(block),
            ),
        )

        await cursor_1.close()

        cursor_2 = await self.db.execute(
            "INSERT OR REPLACE INTO sub_block_records VALUES(?, ?, ?, ?,?, ?, ?)",
            (
                block.header_hash.hex(),
                block.prev_header_hash.hex(),
                block.sub_block_height,
                bytes(sub_block),
                None if sub_block.sub_epoch_summary_included is None else bytes(sub_block.sub_epoch_summary_included),
                False,
                block.is_block(),
            ),
        )
        await cursor_2.close()
        await self.db.commit()

    async def persist_sub_epoch_challenge_segments(
        self, sub_epoch_summary_sub_height: uint32, segments: List[SubEpochChallengeSegment]
    ):
        cursor_1 = await self.db.execute(
            "INSERT OR REPLACE INTO sub_epoch_segments VALUES(?, ?)",
            (sub_epoch_summary_sub_height, bytes(SubEpochSegments(segments))),
        )
        await cursor_1.close()
        await self.db.commit()

    async def get_sub_epoch_challenge_segments(
        self,
        sub_epoch_summary_sub_height: uint32,
    ) -> Optional[List[SubEpochChallengeSegment]]:
        cursor = await self.db.execute(
            "SELECT challenge_segments from sub_epoch_segments WHERE ses_sub_height=?", (sub_epoch_summary_sub_height,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return SubEpochSegments.from_bytes(row[0]).challenge_segments
        return None

    async def delete_sub_epoch_challenge_segments(self, fork_height: uint32):
        cursor = await self.db.execute("delete from sub_epoch_segments WHERE ses_sub_height>?", (fork_height,))
        await cursor.close()

    async def get_full_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        cursor = await self.db.execute("SELECT block from full_blocks WHERE header_hash=?", (header_hash.hex(),))
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return FullBlock.from_bytes(row[0])
        return None

    async def get_full_blocks_at(self, sub_heights: List[uint32]) -> List[FullBlock]:
        if len(sub_heights) == 0:
            return []

        heights_db = tuple(sub_heights)
        formatted_str = f'SELECT block from full_blocks WHERE sub_height in ({"?," * (len(heights_db) - 1)}?)'
        cursor = await self.db.execute(formatted_str, heights_db)
        rows = await cursor.fetchall()
        await cursor.close()
        return [FullBlock.from_bytes(row[0]) for row in rows]

    async def get_full_blocks_at_height(self, heights: List[uint32]) -> List[FullBlock]:
        if len(heights) == 0:
            return []

        heights_db = tuple(heights)
        formatted_str = (
            f'SELECT block from full_blocks WHERE height in ({"?," * (len(heights_db) - 1)}?) and is_block = 1'
        )
        cursor = await self.db.execute(formatted_str, heights_db)
        rows = await cursor.fetchall()
        await cursor.close()
        return [FullBlock.from_bytes(row[0]) for row in rows]

    async def get_sub_block_record(self, header_hash: bytes32) -> Optional[SubBlockRecord]:
        cursor = await self.db.execute(
            "SELECT sub_block from sub_block_records WHERE header_hash=?",
            (header_hash.hex(),),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is not None:
            return SubBlockRecord.from_bytes(row[0])
        return None

    async def get_sub_block_records(
        self,
    ) -> Tuple[Dict[bytes32, SubBlockRecord], Optional[bytes32]]:
        """
        Returns a dictionary with all sub blocks, as well as the header hash of the peak,
        if present.
        """
        cursor = await self.db.execute("SELECT * from sub_block_records")
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, SubBlockRecord] = {}
        peak: Optional[bytes32] = None
        for row in rows:
            header_hash = bytes.fromhex(row[0])
            ret[header_hash] = SubBlockRecord.from_bytes(row[3])
            if row[5]:
                assert peak is None  # Sanity check, only one peak
                peak = header_hash
        return ret, peak

    async def get_headers_in_range(
        self,
        start: int,
        stop: int,
    ) -> Dict[bytes32, HeaderBlock]:

        formatted_str = (
            f"SELECT header_hash,block from full_blocks WHERE sub_height >= {start} and sub_height <= {stop}"
        )

        cursor = await self.db.execute(formatted_str)
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, HeaderBlock] = {}
        for row in rows:
            header_hash = bytes.fromhex(row[0])
            full_block: FullBlock = FullBlock.from_bytes(row[1])
            ret[header_hash] = full_block.get_block_header()

        return ret

    async def get_sub_block_in_range(
        self,
        start: int,
        stop: int,
    ) -> Dict[bytes32, SubBlockRecord]:
        """
        Returns a dictionary with all sub blocks in range between start and stop
        if present.
        """

        formatted_str = (
            f"SELECT header_hash,sub_block from sub_block_records WHERE sub_height >= {start} and sub_height <= {stop}"
        )

        cursor = await self.db.execute(formatted_str)
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, SubBlockRecord] = {}
        for row in rows:
            header_hash = bytes.fromhex(row[0])
            ret[header_hash] = SubBlockRecord.from_bytes(row[1])

        return ret

    async def get_sub_blocks_from_peak(self, blocks_n: int) -> Tuple[Dict[bytes32, SubBlockRecord], Optional[bytes32]]:
        """
        Returns a dictionary with all sub_blocks that have sub_height >= peak sub_height - blocks_n, as well as the
        peak header hash.
        """

        res = await self.db.execute("SELECT * from sub_block_records WHERE is_peak = 1")
        row = await res.fetchone()
        await res.close()
        if row is None:
            return {}, None

        formatted_str = f"SELECT header_hash,sub_block  from sub_block_records WHERE sub_height >= {row[2] - blocks_n}"
        cursor = await self.db.execute(formatted_str)
        rows = await cursor.fetchall()
        await cursor.close()
        ret: Dict[bytes32, SubBlockRecord] = {}
        for row in rows:
            header_hash = bytes.fromhex(row[0])
            ret[header_hash] = SubBlockRecord.from_bytes(row[1])
        return ret, bytes.fromhex(row[0])

    async def get_sub_block_dicts(self) -> Tuple[Dict[uint32, bytes32], Dict[uint32, SubEpochSummary]]:
        """
        Returns a dictionary with all sub blocks, as well as the header hash of the peak,
        if present.
        """

        res = await self.db.execute("SELECT * from sub_block_records WHERE is_peak = 1")
        row = await res.fetchone()
        await res.close()
        if row is None:
            return {}, {}

        peak: bytes32 = bytes.fromhex(row[0])
        cursor = await self.db.execute(
            "SELECT header_hash,prev_hash,sub_height,sub_epoch_summary from sub_block_records"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        hash_to_prev_hash: Dict[bytes32, bytes32] = {}
        hash_to_height: Dict[bytes32, uint32] = {}
        hash_to_summary: Dict[bytes32, SubEpochSummary] = {}

        for row in rows:
            hash_to_prev_hash[bytes.fromhex(row[0])] = bytes.fromhex(row[1])
            hash_to_height[bytes.fromhex(row[0])] = row[2]
            if row[3] is not None:
                hash_to_summary[bytes.fromhex(row[0])] = SubEpochSummary.from_bytes(row[3])

        sub_height_to_hash: Dict[uint32, bytes32] = {}
        sub_epoch_summaries: Dict[uint32, SubEpochSummary] = {}

        curr_header_hash = peak
        curr_sub_height = hash_to_height[curr_header_hash]
        while True:
            sub_height_to_hash[curr_sub_height] = curr_header_hash
            if curr_header_hash in hash_to_summary:
                sub_epoch_summaries[curr_sub_height] = hash_to_summary[curr_header_hash]
            if curr_sub_height == 0:
                break
            curr_header_hash = hash_to_prev_hash[curr_header_hash]
            curr_sub_height = hash_to_height[curr_header_hash]
        return sub_height_to_hash, sub_epoch_summaries

    async def set_peak(self, header_hash: bytes32) -> None:
        cursor_1 = await self.db.execute("UPDATE sub_block_records SET is_peak=0 WHERE is_peak=1")
        await cursor_1.close()
        cursor_2 = await self.db.execute(
            "UPDATE sub_block_records SET is_peak=1 WHERE header_hash=?",
            (header_hash.hex(),),
        )
        await cursor_2.close()
        await self.db.commit()
