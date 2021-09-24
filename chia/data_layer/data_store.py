# from collections import OrderedDict
import dataclasses
from dataclasses import dataclass
from enum import IntEnum
import io
import logging

# from typing import Dict, List, Optional, Tuple
from typing import Iterable, List, Tuple

import aiosqlite
from clvm.CLVMObject import CLVMObject
from clvm.SExp import SExp
from clvm.serialize import sexp_from_stream

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


class CommitState(IntEnum):
    OPEN = 0
    FINALIZED = 1
    ROLLED_BACK = 2


@dataclass(frozen=True)
class TableRow:
    clvm_object: CLVMObject
    hash: bytes32
    bytes: bytes

    @classmethod
    def from_clvm_object(cls, clvm_object: CLVMObject) -> "TableRow":
        sexp = SExp.to(clvm_object)

        return cls(
            clvm_object=clvm_object,
            hash=sha256_treehash(sexp),
            bytes=sexp.as_bin(),
        )

    @classmethod
    def from_clvm_bytes(cls, clvm_bytes: bytes) -> "TableRow":
        clvm_object = sexp_from_stream(io.BytesIO(clvm_bytes), to_sexp=CLVMObject)
        sexp = SExp.to(clvm_object)

        return cls(
            clvm_object=clvm_object,
            hash=sha256_treehash(sexp),
            bytes=clvm_bytes,
        )

    def __eq__(self, other: object) -> bool:
        # TODO: I think this would not be needed if we switched from CLVMObject to SExp.
        #       CLVMObjects have not defined a `.__eq__()` so they inherit usage of `is`
        #       for equality checks.

        if not isinstance(other, TableRow):
            # Intentionally excluding subclasses, feel free to express other preferences
            return False

        if isinstance(self.clvm_object, SExp):
            # This would be the simple way but CLVMObject.__new__ trips it up
            # return dataclasses.asdict(self) == dataclasses.asdict(other)
            return self.clvm_object == other.clvm_object and self.hash == other.hash and self.bytes == other.bytes

        sexp_self = dataclasses.replace(self, clvm_object=SExp.to(self.clvm_object))

        return sexp_self == other


@dataclass(frozen=True)
class Action:
    op: OperationType
    row: TableRow


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
    async def create(cls, db_wrapper: DBWrapper) -> "DataStore":
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
            "CREATE TABLE IF NOT EXISTS raw_rows(row_hash TEXT PRIMARY KEY, table_id TEXT, clvm_object BLOB)"
        )
        # The present properly ordered collection of rows.
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS data_rows("
            "row_hash TEXT PRIMARY KEY,"
            " FOREIGN KEY(row_hash) REFERENCES raw_rows(row_hash))"
        )
        # TODO: needs a key
        # TODO: As operations are reverted do they get deleted?  Or perhaps we track
        #       a reference into the table and only remove when a non-matching forward
        #       step is taken?  Or reverts are just further actions?
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS actions("
            "row_hash TEXT,"
            " operation INTEGER,"
            " FOREIGN KEY(row_hash) REFERENCES raw_rows(row_hash))"
        )
        # TODO: Could also be structured such that the action table has a reference from
        #       each action to the commit it is part of.
        await self.db.execute("CREATE TABLE IF NOT EXISTS commits(changelist_hash TEXT, actions_index INTEGER)")

        await self.db.commit()

        return self

    # TODO: Add some handling for multiple tables.  Could be another layer of class
    #       for each table or another parameter to select the table.

    # chia.util.merkle_set.TerminalNode requires 32 bytes so I think that's applicable here

    # TODO: added as the core was adjusted to be `get_rows` (plural).  API can be
    #       discussed  more.
    async def get_row_by_hash(self, table: bytes32, row_hash: bytes32) -> TableRow:
        cursor = await self.db.execute(
            (
                "SELECT raw_rows.row_hash, raw_rows.clvm_object"
                " FROM raw_rows INNER JOIN data_rows"
                " WHERE raw_rows.row_hash == data_rows.row_hash AND data_rows.row_hash == ?"
            ),
            (row_hash,),
        )
        rows = await cursor.fetchall()

        [table_row] = [
            TableRow(
                clvm_object=sexp_from_stream(io.BytesIO(clvm_object_bytes), to_sexp=CLVMObject),
                hash=row_hash,
                bytes=clvm_object_bytes,
            )
            for row_hash, clvm_object_bytes in rows
        ]

        return table_row

    async def insert_row(self, table: bytes32, clvm_object: CLVMObject) -> TableRow:
        """
        Args:
            clvm_object: The CLVM object to insert.
        """
        # TODO: Should we be using CLVMObject or SExp?

        row_hash = sha256_treehash(sexp=clvm_object)

        # check if this is already present in the raw_rows
        cursor = await self.db.execute(
            "SELECT * FROM raw_rows WHERE row_hash=:row_hash",
            parameters={"row_hash": row_hash},
        )

        clvm_bytes = SExp.to(clvm_object).as_bin()
        if await cursor.fetchone() is None:
            # not present in raw_rows so add it
            await self.db.execute(
                "INSERT INTO raw_rows (row_hash, table_id, clvm_object) VALUES(?, ?, ?)", (row_hash, table, clvm_bytes)
            )

        await self.db.execute("INSERT INTO data_rows (row_hash) VALUES(?)", (row_hash,))

        await self.db.execute(
            "INSERT INTO actions (row_hash, operation) VALUES(?, ?)",
            (row_hash, OperationType.INSERT),
        )

        # TODO: Review reentrancy on .commit() since it isn't clearly tied to this
        #       particular task's activity.
        await self.db.commit()

        return TableRow(clvm_object=clvm_object, hash=row_hash, bytes=clvm_bytes)

    async def delete_row_by_hash(self, table: bytes32, row_hash: bytes32) -> TableRow:
        table_row = await self.get_row_by_hash(table=table, row_hash=row_hash)

        # TODO: How do we generally handle multiple incoming requests to avoid them
        #       trompling over each other via race conditions such as here?

        await self.db.execute("DELETE FROM data_rows WHERE row_hash == ?", (row_hash,))

        await self.db.execute(
            "INSERT INTO actions (row_hash, operation) VALUES(?, ?)",
            (table_row.hash, OperationType.DELETE),
        )

        await self.db.commit()

        return table_row

    async def get_all_actions(self, table: bytes32) -> List[Action]:
        # TODO: What needs to be done to retain proper ordering, relates to the question
        #       at the table creation as well.
        cursor = await self.db.execute(
            "SELECT actions.operation, raw_rows.clvm_object"
            " FROM actions INNER JOIN raw_rows"
            " WHERE actions.row_hash == raw_rows.row_hash"
        )
        actions = await cursor.fetchall()

        return [
            Action(op=OperationType(operation), row=TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes))
            for operation, clvm_bytes in actions
        ]

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
