from dataclasses import dataclass
from enum import IntEnum
import logging
import random
from typing import Iterable, List, Set, Tuple

import aiosqlite
from clvm.SExp import SExp

from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.db_wrapper import DBWrapper


log = logging.getLogger(__name__)


class NodeType(IntEnum):
    EMPTY = 0
    INTERNAL = 1
    TERMINAL = 2


class OperationType(IntEnum):
    INSERT = 0
    DELETE = 1


class CommitState(IntEnum):
    OPEN = 0
    FINALIZED = 1
    ROLLED_BACK = 2


# TODO: remove or formalize this
async def _debug_dump(db, description=""):
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print("-" * 50, description, flush=True)
    for [name] in await cursor.fetchall():
        cursor = await db.execute(f"SELECT * FROM {name}")
        print(f"\n -- {name} ------", flush=True)
        async for row in cursor:
            print(f"        {dict(row)}")


def hexstr_to_bytes32(hexstr: str) -> bytes32:
    return bytes32(hexstr_to_bytes(hexstr))


@dataclass(frozen=True)
class TableRow:
    hash: bytes32
    bytes: bytes

    @classmethod
    def from_serialized_program(cls, serialized_program: SerializedProgram) -> "TableRow":
        hash = serialized_program.get_tree_hash()
        bytes_ = bytes(serialized_program)

        return cls(hash=hash, bytes=bytes_)

    @classmethod
    def from_bytes(cls, blob: bytes) -> "TableRow":
        serialized_program = SerializedProgram.from_bytes(blob=blob)

        return cls(hash=serialized_program.get_tree_hash(), bytes=blob)

    def serialized_program(self) -> SerializedProgram:
        return SerializedProgram.from_bytes(self.bytes)


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
    """A key/value store with the pairs being terminal nodes in a CLVM object tree."""

    db: aiosqlite.Connection
    # block_cache: LRUCache
    db_wrapper: DBWrapper
    # ses_challenge_cache: LRUCache

    @classmethod
    async def create(cls, db_wrapper: DBWrapper) -> "DataStore":
        self = cls(db=db_wrapper.db, db_wrapper=db_wrapper)
        self.db.row_factory = aiosqlite.Row

        await self.db.execute("pragma journal_mode=wal")
        # https://github.com/Chia-Network/chia-blockchain/pull/8514#issuecomment-923310041
        await self.db.execute("pragma synchronous=OFF")
        await self.db.execute("PRAGMA foreign_keys=ON")

        async with self.db_wrapper.locked_transaction():
            # TODO: should the hashes/ids be TEXT or BLOB?
            await self.db.execute("CREATE TABLE IF NOT EXISTS tree(id TEXT PRIMARY KEY NOT NULL)")
            # Note that the meaning of `first` and `rest` depend on the value of `type`:
            #   EMPTY: unused
            #   INTERNAL: both are foreign keys against node.hash
            #   TERMINAL: both are serialized CLVM objects with `first` being the key and `rest` being the value
            # TODO: Should we have the two columns for each of `first` and `rest` to be
            #       separated for explicitness rather than merged for storage
            #       optimization?
            # TODO: I think the generation needs to be added to the key so the
            #       "same node" can be tagged with multiple generations if it gets
            #       removed and re-added, or added to different tables, etc.  Or,
            #       perhaps the generation should be handled differently to avoid
            #       such repetition of subtrees.
            await self.db.execute(
                "CREATE TABLE IF NOT EXISTS node("
                "hash TEXT PRIMARY KEY NOT NULL,"
                " type INTEGER NOT NULL,"
                " generation INTEGER NOT NULL,"
                " first TEXT,"
                " rest TEXT"
                ")"
            )
            await self.db.execute(
                "CREATE TABLE IF NOT EXISTS root("
                "tree_id TEXT NOT NULL,"
                " node_hash TEXT NOT NULL,"
                " PRIMARY KEY(tree_id, node_hash),"
                " FOREIGN KEY(tree_id) REFERENCES tree(id),"
                " FOREIGN KEY(node_hash) REFERENCES node(hash)"
                ")"
            )

        return self

    async def create_tree(self, tree_id: bytes32) -> None:
        tree_id = bytes32(tree_id)

        async with self.db_wrapper.locked_transaction():
            await self.db.execute("INSERT INTO tree(id) VALUES(:id)", {"id": tree_id.hex()})

    async def get_tree_ids(self) -> Set[bytes32]:
        async with self.db_wrapper.locked_transaction():
            cursor = await self.db.execute("SELECT id FROM tree")

        tree_ids = {hexstr_to_bytes32(row["id"]) async for row in cursor}

        return tree_ids

    async def get_tree_generation(self, tree_id: bytes32) -> int:
        async with self.db_wrapper.locked_transaction():
            cursor = await self.db.execute(
                "SELECT max(generation) FROM nodes WHERE tree_id == :tree_id",
                {"tree_id": tree_id.hex()},
            )
            [generation] = (row["generation"] async for row in cursor)

        return generation

    async def _insert_program(self, program: Program) -> bytes32:
        if not program.pair:
            # TODO: use a more specific exception
            raise Exception("must be a pair")

        first = program.first()
        rest = program.rest()

        how_many_pairs = sum(1 if o.pair is not None else 0 for o in [first, rest])

        if how_many_pairs == 1:
            # TODO: use a better exception
            raise Exception("not an allowed state, must terminate with key/value")

        if how_many_pairs == 0:
            node_hash = await self._insert_key_value(key=first, value=rest)
            return node_hash

        # TODO: unroll the recursion
        first_hash = self._insert_program(program=first)
        rest_hash = self._insert_program(program=rest)

        node_hash = Program.to([first_hash, rest_hash]).get_tree_hash(first_hash, rest_hash)

        await self.db.execute(
            "INSERT INTO node(hash, type, first, rest) VALUE(:hash, :type, :first, :rest)",
            {"hash": node_hash.hex(), "type": NodeType.INTERNAL, "first": first_hash.hex(), "rest": rest_hash.hex()},
        )

        return node_hash

    async def _insert_key_value(self, key: bytes, value: bytes, generation: int) -> bytes32:
        # TODO: don't we decode from a program...?  and this undoes that...?
        node_hash = Program.to([key, value]).get_tree_hash()

        await self.db.execute(
            "INSERT INTO node(hash, type, generation, first, rest) VALUE(:hash, :type, :generation, :first, :rest)",
            {
                "hash": node_hash.hex(),
                "type": NodeType.TERMINAL,
                "generation": generation,
                "first": key.hex(),
                "rest": value.hex(),
            },
        )

        return node_hash

    async def create_root(self, tree_id: bytes32):
        generation = 0
        # TODO: Think through this a lot more as to...
        #           What should an empty tree look like?
        #           What API should the store provide for creating a tree including the
        #               root node.
        node_hash = bytes32(b"\0" * 32)

        async with self.db_wrapper.locked_transaction():
            await _debug_dump(db=self.db, description="before")
            await self.db.execute(
                "INSERT INTO node(hash, type, generation, first, rest)"
                " VALUES(:hash, :type, :generation, :first, :rest)",
                {
                    "hash": node_hash.hex(),
                    "type": NodeType.EMPTY,
                    "generation": generation,
                    "first": None,
                    "rest": None,
                },
            )
        async with self.db_wrapper.locked_transaction():
            await _debug_dump(db=self.db, description="between")
        to_insert = {"tree_id": tree_id.hex(), "node_hash": node_hash.hex()}
        print(f"to_insert: {to_insert}")
        async with self.db_wrapper.locked_transaction():
            await self.db.execute(
                "INSERT INTO root(tree_id, node_hash) VALUES(:tree_id, :node_hash)",
                to_insert,
            )

        return node_hash
