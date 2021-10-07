from dataclasses import dataclass
from enum import IntEnum
import logging
import random
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Type, Union

import aiosqlite
from clvm.SExp import SExp

from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.db_wrapper import DBWrapper


log = logging.getLogger(__name__)


class NodeType(IntEnum):
    # EMPTY = 0
    INTERNAL = 1
    TERMINAL = 2


class Side(IntEnum):
    LEFT = 0
    RIGHT = 1

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


Node = Union["TerminalNode", "InternalNode"]


@dataclass(frozen=True)
class TerminalNode:
    hash: bytes32
    # generation: int
    key: Program
    value: Program

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "TerminalNode":
        return cls(
            hash=hexstr_to_bytes32(row["hash"]),
            # generation=row["generation"],
            key=Program.fromhex(row["key"]),
            value=Program.fromhex(row["value"]),
        )


@dataclass(frozen=True)
class InternalNode:
    hash: bytes32
    # generation: int
    left_hash: Node
    right_hash: Node

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "InternalNode":
        return cls(
            hash=hexstr_to_bytes32(row["hash"]),
            # generation=row["generation"],
            left_hash=hexstr_to_bytes32(row["left"]),
            right_hash=hexstr_to_bytes32(row["right"]),
        )


@dataclass(frozen=True)
class Root:
    tree_id: bytes32
    node_hash: Optional[bytes32]
    generation: int

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Root":
        raw_node_hash = row["node_hash"]
        if raw_node_hash is None:
            node_hash = None
        else:
            node_hash = hexstr_to_bytes32(raw_node_hash)

        return cls(
            tree_id=hexstr_to_bytes32(row["tree_id"]),
            node_hash=node_hash,
            generation=row["generation"],
        )


node_type_to_class: Dict[NodeType, Union[Type[InternalNode], Type[TerminalNode]]] = {
    NodeType.INTERNAL: InternalNode,
    NodeType.TERMINAL: TerminalNode,
}


def row_to_node(row: Dict[str, Any]) -> Node:
    cls = node_type_to_class[row["type"]]
    return cls.from_row(row=row)


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
            await self.db.execute("CREATE TABLE IF NOT EXISTS tree(id TEXT PRIMARY KEY NOT NULL)")
            # TODO: figure out the use of the generation
            await self.db.execute(
                "CREATE TABLE IF NOT EXISTS node("
                "hash TEXT PRIMARY KEY NOT NULL,"
                # " generation INTEGER NOT NULL",
                " type INTEGER NOT NULL,"
                " left TEXT,"
                " right TEXT,"
                " key TEXT,"
                " value TEXT,"
                " FOREIGN KEY(left) REFERENCES node(hash),"
                " FOREIGN KEY(right) REFERENCES node(hash)"
                ")"
            )
            await self.db.execute(
                "CREATE TABLE IF NOT EXISTS root("
                "tree_id TEXT NOT NULL,"
                " generation INTEGER NOT NULL,"
                " node_hash TEXT,"
                " PRIMARY KEY(tree_id, generation),"
                " FOREIGN KEY(tree_id) REFERENCES tree(id),"
                " FOREIGN KEY(node_hash) REFERENCES node(hash)"
                ")"
            )

        return self

    async def create_tree(self, tree_id: bytes32) -> None:
        tree_id = bytes32(tree_id)

        async with self.db_wrapper.locked_transaction():
            await self.db.execute("INSERT INTO tree(id) VALUES(:id)", {"id": tree_id.hex()})
            await self.db.execute(
                "INSERT INTO root(tree_id, generation, node_hash) VALUES(:tree_id, :generation, :node_hash)",
                {"tree_id": tree_id.hex(), "generation": 0, "node_hash": None},
            )

    async def table_is_empty(self, tree_id: bytes32) -> bool:
        async with self.db_wrapper.locked_transaction():
            return await self._raw_table_is_empty(tree_id=tree_id)

    async def _raw_table_is_empty(self, tree_id: bytes32) -> bool:
        tree_root = await self._raw_get_tree_root(tree_id=tree_id)
        return tree_root.node_hash is None

    async def get_tree_ids(self) -> Set[bytes32]:
        async with self.db_wrapper.locked_transaction():
            cursor = await self.db.execute("SELECT id FROM tree")

        tree_ids = {hexstr_to_bytes32(row["id"]) async for row in cursor}

        return tree_ids

    # async def get_tree_generation(self, tree_id: bytes32) -> int:
    #     async with self.db_wrapper.locked_transaction():
    #         cursor = await self.db.execute(
    #             "SELECT max(generation) FROM nodes WHERE tree_id == :tree_id",
    #             {"tree_id": tree_id.hex()},
    #         )
    #         [generation] = (row["generation"] async for row in cursor)
    #
    #     return generation

    async def get_tree_generation(self, tree_id: bytes32) -> int:
        async with self.db_wrapper.locked_transaction():
            return await self._raw_get_tree_generation(tree_id=tree_id)

    async def _raw_get_tree_generation(self, tree_id: bytes32) -> int:
        cursor = await self.db.execute(
            "SELECT MAX(generation) FROM root WHERE tree_id == :tree_id",
            {"tree_id": tree_id.hex()},
        )
        row = await cursor.fetchone()
        generation = row["MAX(generation)"]
        return generation

    async def get_tree_root(self, tree_id: bytes32) -> Root:
        async with self.db_wrapper.locked_transaction():
            return await self._raw_get_tree_root(tree_id=tree_id)

    async def _raw_get_tree_root(self, tree_id: bytes32) -> Root:
        generation = await self._raw_get_tree_generation(tree_id=tree_id)
        cursor = await self.db.execute(
            "SELECT * FROM root WHERE tree_id == :tree_id AND generation == :generation",
            {"tree_id": tree_id.hex(), "generation": generation},
        )
        [root_dict] = [row async for row in cursor]

        return Root.from_row(row=root_dict)

    # async def _insert_program(self, program: Program) -> bytes32:
    #     if not program.pair:
    #         # TODO: use a more specific exception
    #         raise Exception("must be a pair")
    #
    #     left = program.first()
    #     right = program.rest()
    #
    #     how_many_pairs = sum(1 if o.pair is not None else 0 for o in [left, right])
    #
    #     if how_many_pairs == 1:
    #         # TODO: use a better exception
    #         raise Exception("not an allowed state, must terminate with key/value")
    #
    #     if how_many_pairs == 0:
    #         node_hash = await self.insert_key_value(key=left, value=right)
    #         return node_hash
    #
    #     # TODO: unroll the recursion
    #     left_hash = self._insert_program(program=left)
    #     right_hash = self._insert_program(program=right)
    #
    #     node_hash = Program.to([left_hash, right_hash]).get_tree_hash(left_hash, right_hash)
    #
    #     await self.db.execute(
    #         "INSERT INTO node(hash, type, left, right, key, value) VALUE(:hash, :type, :left, :right, :key, :value)",
    #         {
    #             "hash": node_hash.hex(),
    #             "type": NodeType.INTERNAL,
    #             "left": left_hash.hex(),
    #             "right": right_hash.hex(),
    #             "key": None,
    #             "value": None,
    #         },
    #     )
    #
    #     return node_hash

    async def _raw_get_node_type(self, node_hash: bytes32) -> NodeType:
        cursor = self.db.execute("SELECT type FROM node WHERE hash == :hash", {"hash": node_hash})
        [node_type] = (NodeType(row["type"]) async for row in cursor)
        return node_type

    async def insert(
        self,
        key: Program,
        value: Program,
        tree_id: bytes32,
        reference_node_hash: bytes32,
        side: Optional[Side],
    ) -> bytes32:
        # TODO: this should be one big transaction
        async with self.db_wrapper.locked_transaction():
            was_empty = await self._raw_table_is_empty(tree_id=tree_id)

            reference_node_type = self._raw_get_node_type(node_hash=reference_node_hash)
            if reference_node_type == NodeType.INTERNAL:
                raise Exception("can not insert a new key/value on an internal node")

            # TODO: don't we decode from a program...?  and this undoes that...?
            new_terminal_node_hash = Program.to([key, value]).get_tree_hash()

            # create new terminal node
            await self.db.execute(
                "INSERT INTO node(hash, type, left, right, key, value)"
                " VALUES(:hash, :type, :left, :right, :key, :value)",
                {
                    "hash": new_terminal_node_hash.hex(),
                    "type": NodeType.TERMINAL,
                    # "generation": generation,
                    "left": None,
                    "right": None,
                    "key": bytes(key).hex(),
                    "value": bytes(value).hex(),
                },
            )

            generation = await self._raw_get_tree_generation(tree_id=tree_id)

            if was_empty:
                # TODO: a real exception
                assert side is None

                await self.db.execute(
                    "INSERT INTO root(tree_id, generation, node_hash)" " VALUES(:tree_id, :generation, :node_hash)",
                    {
                        "tree_id": tree_id.hex(),
                        "generation": generation + 1,
                        "node_hash": new_terminal_node_hash.hex(),
                    },
                )
            else:
                # TODO: a real exception
                assert side is not None

                traversal_hash = reference_node_hash
                parents = []
                print(f"traversal hash: {traversal_hash}")

                while True:
                    # TODO: but but but ...  multiple parents could be referencing this node...
                    cursor = await self.db.execute("SELECT * FROM node WHERE left == :hash OR right == :hash", {"hash": traversal_hash.hex()})
                    row = await cursor.fetchone()

                    if row is None:
                        break

                    new_node = row_to_node(row=row)
                    parents.append(new_node)
                    traversal_hash = new_node.hash

                # TODO: debug, remove
                print(" +++++++++++")
                for parent in parents:
                    print(f"        {parent}")

                # create the new internal node
                if side == Side.LEFT:
                    left = new_terminal_node_hash
                    right = reference_node_hash
                elif side == Side.RIGHT:
                    left = reference_node_hash
                    right = new_terminal_node_hash

                new_hash = Program.to([left, right]).get_tree_hash()

                # create first new internal node
                await self.db.execute(
                    "INSERT INTO node(hash, type, left, right, key, value)"
                    " VALUES(:hash, :type, :left, :right, :key, :value)",
                    {
                        "hash": new_hash.hex(),
                        "type": NodeType.INTERNAL,
                        "left": left.hex(),
                        "right": right.hex(),
                        "key": None,
                        "value": None,
                    },
                )

                traversal_node_hash = reference_node_hash

                for parent in parents:
                    if parent.left_hash == traversal_node_hash:
                        left = new_hash
                        right = parent.right_hash
                    elif parent.right_hash == traversal_node_hash:
                        left = parent.left_hash
                        right = new_hash

                    traversal_node_hash = parent.hash

                    new_hash = Program.to([left, right]).get_tree_hash()

                    await self.db.execute(
                        "INSERT INTO node(hash, type, left, right, key, value)"
                        " VALUES(:hash, :type, :left, :right, :key, :value)",
                        {
                            "hash": new_hash.hex(),
                            "type": NodeType.INTERNAL,
                            "left": left.hex(),
                            "right": right.hex(),
                            "key": None,
                            "value": None,
                        },
                    )

                await self.db.execute(
                    "INSERT INTO root(tree_id, generation, node_hash)" " VALUES(:tree_id, :generation, :node_hash)",
                    {
                        "tree_id": tree_id.hex(),
                        "generation": generation + 1,
                        "node_hash": new_hash.hex(),
                    },
                )

        # TODO: debug, remove
        await _debug_dump(db=self.db)

        return new_terminal_node_hash

    # async def create_root(self, tree_id: bytes32, node_hash: bytes32):
    #     # generation = 0
    #
    #     async with self.db_wrapper.locked_transaction():
    #         await _debug_dump(db=self.db, description="before")
    #
    #         # await self.db.execute(
    #         #     "INSERT INTO node(hash, type, left, right, key, value)"
    #         #     " VALUES(:hash, :type, :left, :right, :key, :value)",
    #         #     {
    #         #         "hash": node_hash.hex(),
    #         #         "type": NodeType.EMPTY,
    #         #         # "generation": generation,
    #         #         "left": None,
    #         #         "right": None,
    #         #         "key": None,
    #         #         "value": None,
    #         #     },
    #         # )
    #
    #         cursor = await self.db.execute(
    #             "INSERT INTO root(tree_id, generation, node_hash)"
    #             " VALUES(:tree_id, (SELECT max(generation) + 1 FROM root WHERE tree_id == :tree_id), :node_hash)",
    #             {"tree_id": tree_id.hex(), "node_hash": None},
    #         )
    #         x = list(row async for row in cursor)
    #
    #     return node_hash
