# from collections import OrderedDict
from dataclasses import dataclass
from enum import IntEnum
import logging

# from typing import Dict, List, Optional, Tuple
from typing import Iterable, Optional, Tuple

import aiosqlite
from clvm.CLVMObject import CLVMObject
from clvm.SExp import SExp

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
    row: CLVMObject


@dataclass(frozen=True)
class Commit:
    # actions: OrderedDict[bytes32, CLVMObject]
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
        await self.db.execute("CREATE TABLE IF NOT EXISTS data_rows(row_index INTEGER PRIMARY KEY, row_hash TEXT)")
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

    async def insert_row(self, table: bytes32, clvm_object: CLVMObject, index: Optional[int] = None) -> None:
        """
        Args:
            clvm_object: The CLVM object to insert.
            index: The index at which to insert the CLVM object.  If ``None``, such as
                when unspecified, the object will be appended with the now-highest
                index.
        """
        # TODO: Should we be using CLVMObject or SExp?

        row_hash = sha256_treehash(sexp=clvm_object)

        # check if this is already present in the raw_rows
        cursor = await self.db.execute(
            "SELECT * FROM raw_rows WHERE row_hash=:row_hash",
            parameters={"row_hash": row_hash},
        )

        if await cursor.fetchone() is None:
            # not present in raw_rows so add it
            clvm_bytes = SExp.to(clvm_object).as_bin()
            await self.db.execute("INSERT INTO raw_rows (row_hash, table_id, clvm_object) VALUES(?, ?, ?)", (row_hash, table, clvm_bytes))

        largest_index = await self._get_largest_index()

        if index is None:
            index = largest_index + 1
        elif index > largest_index + 1:
            # Inserting this index would result in a gap in the indices.
            raise ValueError(f"Index must be no more than 1 larger than the largest index ({largest_index!r}), received: {index!r}")
        else:
            await self.db.execute("UPDATE data_rows SET row_index = row_index + 1 WHERE row_index >= ?", (index,))

        await self.db.execute("INSERT INTO data_rows (row_index, row_hash) VALUES(?, ?)", (index, row_hash,))
        # TODO: Review reentrancy on .commit() since it isn't clearly tied to this
        #       particular task's activity.
        await self.db.commit()

    async def _get_largest_index(self):
        cursor = await self.db.execute("SELECT MAX(row_index) FROM data_rows")
        [[maybe_largest_index]] = await cursor.fetchall()
        if maybe_largest_index is None:
            largest_index = -1
        else:
            largest_index = maybe_largest_index
        return largest_index

    async def delete_row_by_index(self, table: bytes32, index: int) -> CLVMObject:
        # todo this
        await self.db.execute("DELETE FROM data_rows WHERE row_index == ?", (index,))
        await self.db.execute("UPDATE data_rows SET row_index = row_index - 1 WHERE row_index > ?", (index,))

    async def delete_row_by_hash(self, table: bytes32, row_hash: bytes32) -> None:
        # TODO: A hash could match multiple rows.
        cursor = await self.db.execute("SELECT row_index FROM data_rows WHERE row_hash == ?", (row_hash,))
        [[index]] = await cursor.fetchall()
        await self.delete_row_by_index(table=table, index=index)

        # # TODO: This is doubly careful to make sure it matches but it seems like maybe
        # #       we should be able to delete by hash and get the index in one step?
        # await self.db.execute("DELETE FROM data_rows WHERE row_hash == ? AND row_index == ?", (row_hash, index,))
        # await self.db.execute("UPDATE data_rows SET row_index = row_index - 1 WHERE row_index > ?", (index,))

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
