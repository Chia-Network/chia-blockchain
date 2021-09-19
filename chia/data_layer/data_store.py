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
from chia.types.blockchain_format.tree_hash import sha256_treehash

# from chia.types.full_block import FullBlock
# from chia.types.weight_proof import SubEpochChallengeSegment, SubEpochSegments
from chia.util.db_wrapper import DBWrapper

# from chia.util.ints import uint32
# from chia.util.lru_cache import LRUCache

log = logging.getLogger(__name__)


class OperationType(IntEnum):
    INSERT = 0
    DELETE = 1


@dataclass(frozen=True)
class Action:
    op: OperationType
    row_index: int
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
    # block_cache: LRUCache
    db_wrapper: DBWrapper
    # ses_challenge_cache: LRUCache

    @classmethod
    async def create(cls, db_wrapper: DBWrapper):
        self = cls()

        # All full blocks which have been added to the blockchain. Header_hash -> block
        self.db_wrapper = db_wrapper
        self.db = db_wrapper.db

        # TODO: what pragmas do we want?
        # await self.db.execute("pragma journal_mode=wal")
        # await self.db.execute("pragma synchronous=2")

        # TODO: make this handle multiple data layer tables
        # TODO: do we need to handle multiple equal rows

        # Just a raw collection of all ChiaLisp lists that are used
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS raw_rows(row_hash TEXT PRIMARY KEY,table_id TEXT, clvm_object BLOB)"
        )
        # The present properly ordered collection of rows.
        await self.db.execute("CREATE TABLE IF NOT EXISTS data_rows(row_hash TEXT PRIMARY KEY)")
        # TODO: needs a key
        # TODO: As operations are reverted do they get deleted?  Or perhaps we track
        #       a reference into the table and only remove when a non-matching forward
        #       step is taken?  Or reverts are just further actions?
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS actions(" "data_row_index INTEGER, row_hash TEXT, operation INTEGER" ")"
        )
        # TODO: Could also be structured such that the action table has a reference from
        #       each action to the commit it is part of.
        await self.db.execute("CREATE TABLE IF NOT EXISTS commits(" "changelist_hash TEXT, actions_index INTEGER" ")")

        await self.db.commit()

        return self

    # TODO: Add some handling for multiple tables.  Could be another layer of class
    #       for each table or another parameter to select the table.

    async def get_row_by_index(self, index: int) -> CLVMObject:
        pass

    # chia.util.merkle_set.TerminalNode requires 32 bytes so I think that's applicable here
    async def get_row_by_hash(self, row_hash: bytes32) -> CLVMObject:
        pass

    async def insert_row(self, table_id: bytes32, clvm_object: CLVMObject) -> None:
        row_hash = sha256_treehash(sexp=clvm_object)
        cursor = await self.db.execute(
            "SELECT * FROM raw_rows WHERE row_hash=:row_hash",
            parameters={"row_hash": row_hash},
        )
        if await cursor.fetchone() is None:
            await self.db.execute(
                "INSERT INTO raw_rows (row_hash,table_id,clvm_object) VALUES(?,?,?)",
                (row_hash, table_id, clvm_object),
            )

        await self.db.execute("INSERT INTO ")
        await self.db.commit()

    # "INSERT OR REPLACE INTO full_blocks VALUES(?, ?, ?, ?, ?)",

    async def delete_row_by_index(self, table: bytes32, index: int) -> CLVMObject:
        # todo this
        pass

    async def delete_row_by_hash(self, table: bytes32, row_hash: bytes32) -> Tuple[CLVMObject, int]:
        pass

    async def get_table_state(self, table: bytes32) -> bytes32:
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
