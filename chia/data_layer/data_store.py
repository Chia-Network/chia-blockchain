# from collections import OrderedDict
from dataclasses import dataclass, replace
from enum import IntEnum
import io
import logging
import random

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

        sexp_self = replace(self, clvm_object=SExp.to(self.clvm_object))

        return sexp_self == other

    def __hash__(self) -> int:
        # TODO: this is dirty, consider the TODOs in .__eq__()
        return object.__hash__(replace(self, clvm_object=SExp.to(self.clvm_object)))


# # TODO: remove or formalize this
# async def _debug_dump(db, description=""):
#     cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table';")
#     print("-" * 50, description, flush=True)
#     for [name] in await cursor.fetchall():
#         cursor = await db.execute(f"SELECT * FROM {name}")
#         x = await cursor.fetchall()
#         print(f"\n -- {name} ------", x, flush=True)


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


@dataclass
class DataStore:
    db: aiosqlite.Connection
    # block_cache: LRUCache
    db_wrapper: DBWrapper
    # ses_challenge_cache: LRUCache

    @classmethod
    async def create(cls, db_wrapper: DBWrapper) -> "DataStore":
        self = cls(db=db_wrapper.db, db_wrapper=db_wrapper)

        # TODO: what pragmas do we want?  maybe foreign_keys?
        # await self.db.execute("pragma journal_mode=wal")
        # await self.db.execute("pragma synchronous=2")

        # TODO: make this handle multiple data layer tables
        # TODO: do we need to handle multiple equal rows

        await self.db.execute("CREATE TABLE IF NOT EXISTS tables(id TEXT PRIMARY KEY, name STRING)")
        await self.db.execute("CREATE TABLE IF NOT EXISTS keys_values(key TEXT PRIMARY KEY, value BLOB)")
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS table_values("
            "table_id TEXT,"
            " key STRING,"
            " PRIMARY KEY(table_id, key),"
            " FOREIGN KEY(table_id) REFERENCES tables(id),"
            " FOREIGN KEY(key) REFERENCES keys_values(key)"
            ")"
        )
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS commits("
            "id TEXT PRIMARY KEY,"
            " table_id TEXT,"
            " state INTEGER,"
            " FOREIGN KEY(table_id) REFERENCES tables(id)"
            ")"
        )
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS actions("
            "commit_id TEXT,"
            " idx INTEGER,"
            " operation INTEGER,"
            " key TEXT,"
            " PRIMARY KEY(commit_id, idx)"
            ")"
        )

        # TODO: As operations are reverted do they get deleted?  Or perhaps we track
        #       a reference into the table and only remove when a non-matching forward
        #       step is taken?  Or reverts are just further actions?

        await self.db.commit()

        return self

    # TODO: Add some handling for multiple tables.  Could be another layer of class
    #       for each table or another parameter to select the table.

    # chia.util.merkle_set.TerminalNode requires 32 bytes so I think that's applicable here

    # TODO: should be Set[TableRow] but our stuff isn't super hashable yet...
    async def get_rows(self, table: bytes32) -> List[TableRow]:
        cursor = await self.db.execute(
            "SELECT value FROM keys_values INNER JOIN table_values"
            " WHERE"
            " keys_values.key == table_values.key"
            " AND table_values.table_id == :table_id",
            {"table_id": table},
        )

        some_clvm_bytes = [value for [value] in await cursor.fetchall()]

        table_rows = [TableRow.from_clvm_bytes(clvm_bytes=clvm_bytes) for clvm_bytes in some_clvm_bytes]

        return table_rows

    async def get_row_by_hash(self, table: bytes32, row_hash: bytes32) -> TableRow:
        cursor = await self.db.execute(
            "SELECT value FROM keys_values INNER JOIN table_values"
            " WHERE"
            " keys_values.key == :key"
            " AND keys_values.key == table_values.key"
            " AND table_values.table_id == :table_id",
            {"key": row_hash, "table_id": table},
        )

        [clvm_bytes] = [value for [value] in await cursor.fetchall()]

        table_row = TableRow(
            clvm_object=sexp_from_stream(io.BytesIO(clvm_bytes), to_sexp=CLVMObject),
            hash=row_hash,
            bytes=clvm_bytes,
        )

        return table_row

    async def create_table(self, id: bytes32, name: str) -> None:
        await self.db.execute("INSERT INTO tables(id, name) VALUES(:id, :name)", {"id": id, "name": name})
        await self.db.commit()

    async def insert_row(self, table: bytes32, clvm_object: CLVMObject) -> TableRow:
        """
        Args:
            clvm_object: The CLVM object to insert.
        """
        # TODO: Should we be using CLVMObject or SExp?

        row_hash = sha256_treehash(sexp=clvm_object)
        clvm_bytes = SExp.to(clvm_object).as_bin()

        await self.db.execute(
            "INSERT INTO keys_values(key, value) VALUES(:key, :value)", {"key": row_hash, "value": clvm_bytes}
        )

        await self.db.execute(
            "INSERT INTO table_values(table_id, key) VALUES(:table_id, :key)", {"table_id": table, "key": row_hash}
        )

        await self.add_action(operation_type=OperationType.INSERT, key=row_hash, table=table)

        # TODO: Review reentrancy on .commit() since it isn't clearly tied to this
        #       particular task's activity.
        await self.db.commit()

        return TableRow(clvm_object=clvm_object, hash=row_hash, bytes=clvm_bytes)

    async def add_action(self, operation_type: OperationType, key: bytes32, table: bytes32) -> None:
        cursor = await self.db.execute(
            "SELECT id, table_id FROM commits WHERE table_id == :table_id AND state == :state",
            {"table_id": table, "state": CommitState.OPEN},
        )
        commits_rows: List[Tuple[bytes32, bytes32]] = [(id, table_id) for id, table_id in await cursor.fetchall()]
        if len(commits_rows) == 0:
            # TODO: just copied from elsewhere...  reconsider
            commit_id = random.randint(0, 100000000).to_bytes(32, "big")
            print("table_id", repr(table))
            await self.db.execute(
                "INSERT INTO commits(id, table_id, state) VALUES(:id, :table_id, :state)",
                {"id": commit_id, "table_id": table, "state": CommitState.OPEN},
            )
            next_actions_index = 0
        else:
            [commit_id] = [commit_id for commit_id, table_id in commits_rows]

            cursor = await self.db.execute(
                "SELECT MAX(idx) FROM actions WHERE commit_id == :commit_id", {"commit_id": commit_id}
            )
            [[max_actions_index]] = await cursor.fetchall()
            next_actions_index = max_actions_index + 1
        await self.db.execute(
            "INSERT INTO actions(idx, commit_id, operation, key) VALUES(:idx, :commit_id, :operation, :key)",
            {"idx": next_actions_index, "commit_id": commit_id, "operation": operation_type, "key": key},
        )

    async def delete_row_by_hash(self, table: bytes32, row_hash: bytes32) -> TableRow:
        # TODO: do we really want to bother getting just so we can have the value and bytes?
        table_row = await self.get_row_by_hash(table=table, row_hash=row_hash)

        # TODO: How do we generally handle multiple incoming requests to avoid them
        #       trompling over each other via race conditions such as here?

        await self.db.execute(
            "DELETE FROM table_values WHERE table_id == :table_id AND key == :key",
            {"table_id": table, "key": row_hash},
        )

        await self.add_action(operation_type=OperationType.DELETE, key=row_hash, table=table)

        await self.db.commit()

        return table_row

    async def get_all_actions(self, table: bytes32) -> List[Action]:
        # TODO: What needs to be done to retain proper ordering, relates to the question
        #       at the table creation as well.
        cursor = await self.db.execute(
            "SELECT actions.operation, keys_values.value"
            " FROM actions INNER JOIN keys_values"
            " WHERE actions.key == keys_values.key"
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
