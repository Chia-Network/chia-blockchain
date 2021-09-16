# from collections import OrderedDict
from dataclasses import dataclass
from enum import IntEnum
import logging
# from typing import Dict, List, Optional, Tuple
from typing import Iterable, Tuple

import aiosqlite
from clvm import CLVMObject

# from chia.consensus.block_record import BlockRecord
from chia.types.blockchain_format.sized_bytes import bytes32
# from chia.types.blockchain_format.sub_epoch_summary import SubEpochSummary
# from chia.types.full_block import FullBlock
# from chia.types.weight_proof import SubEpochChallengeSegment, SubEpochSegments
from chia.util.db_wrapper import DBWrapper
# from chia.util.ints import uint32
# from chia.util.lru_cache import LRUCache

log = logging.getLogger(__name__)


class ActionType(IntEnum):
    INSERT = 0
    DELETE = 1


@dataclass(frozen=True)
class Action:
    type: ActionType
    row: CLVMObject.CLVMObject


@dataclass(frozen=True)
class Commit:
    # actions: OrderedDict[bytes32, CLVMObject.CLVMObject]
    actions: Tuple[Action, ...]
    changelist_hash: bytes32
    # TODO: bytes32 may be totally wrong here for the merkle root hash of the overall
    #       data state.
    root_hash: bytes32

    @classmethod
    def build(cls, actions: Iterable[Action], root_hash: bytes32) -> "Commit":
        # TODO: calculate the hash
        changelist_hash = bytes32()

        actions = tuple(actions)

        return cls(actions=actions, changelist_hash=changelist_hash, root_hash=root_hash)


class DataStore:
    db: aiosqlite.Connection
#     block_cache: LRUCache
    db_wrapper: DBWrapper
#     ses_challenge_cache: LRUCache

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.db_wrapper = db_wrapper
        self.db = db_wrapper.db
#         await self.db.execute("pragma journal_mode=wal")
#         await self.db.execute("pragma synchronous=2")
#         await self.db.execute(
#             "CREATE TABLE IF NOT EXISTS full_blocks(header_hash text PRIMARY KEY, height bigint,"
#             "  is_block tinyint, is_fully_compactified tinyint, block blob)"
#         )
#
#         # Block records
#         await self.db.execute(
#             "CREATE TABLE IF NOT EXISTS block_records(header_hash "
#             "text PRIMARY KEY, prev_hash text, height bigint,"
#             "block blob, sub_epoch_summary blob, is_peak tinyint, is_block tinyint)"
#         )
#
#         # todo remove in v1.2
#         await self.db.execute("DROP TABLE IF EXISTS sub_epoch_segments_v2")
#
#         # Sub epoch segments for weight proofs
#         await self.db.execute(
#             "CREATE TABLE IF NOT EXISTS sub_epoch_segments_v3(ses_block_hash text PRIMARY KEY, challenge_segments blob)"
#         )
#
#         # Height index so we can look up in order of height for sync purposes
#         await self.db.execute("CREATE INDEX IF NOT EXISTS full_block_height on full_blocks(height)")
#         await self.db.execute("CREATE INDEX IF NOT EXISTS is_block on full_blocks(is_block)")
#         await self.db.execute("CREATE INDEX IF NOT EXISTS is_fully_compactified on full_blocks(is_fully_compactified)")
#
#         await self.db.execute("CREATE INDEX IF NOT EXISTS height on block_records(height)")
#
#         await self.db.execute("CREATE INDEX IF NOT EXISTS hh on block_records(header_hash)")
#         await self.db.execute("CREATE INDEX IF NOT EXISTS peak on block_records(is_peak)")
#         await self.db.execute("CREATE INDEX IF NOT EXISTS is_block on block_records(is_block)")
#
#         await self.db.commit()
#         self.block_cache = LRUCache(1000)
#         self.ses_challenge_cache = LRUCache(50)
#         return self

    # TODO: Add some handling for multiple tables.  Could be another layer of class
    #       for each table or another parameter to select the table.

    # chia.util.merkle_set.TerminalNode requires 32 bytes so I think that's applicable here
    async def retrieve_row(self, hash: bytes32) -> CLVMObject.CLVMObject:
        pass

    async def insert_row(self, list: CLVMObject.CLVMObject) -> None:
        pass

    async def delete_row(self, hash: bytes32) -> None:
        pass

    # TODO: I'm not sure about the name here.  I'm thinking that this will
    async def create_commit(self) -> Commit:
        """Create a commit of the modifications since the last commit.  The returned
        object provides the information needed to update the singleton.  The database
        updates will document the commit so requests for it can be filled."""

    async def roll_back_to(self, changelist_hash: bytes32) -> None:
        """Roll back the database to the state associated with the provided changelist
        hash.  For example, when there is a chain reorg we may need to roll back to the
        now-latest state even though we have more recent data or even commits."""
