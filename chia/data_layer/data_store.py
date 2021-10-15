from collections import defaultdict
from dataclasses import dataclass, replace

import logging

from typing import Awaitable, Callable, Dict, List, Optional, Set, Tuple

import aiosqlite

from chia.data_layer.data_layer_errors import (
    InternalKeyValueError,
    InternalLeftRightNotBytes32Error,
    NodeHashError,
    TerminalLeftRightError,
    TerminalInvalidKeyOrValueProgramError,
    TreeGenerationIncrementingError,
)
from chia.data_layer.data_layer_types import Root, Side, Node, TerminalNode, NodeType, InternalNode
from chia.data_layer.data_layer_util import row_to_node
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.db_wrapper import DBWrapper


log = logging.getLogger(__name__)


# TODO: review and replace all asserts


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
        # if foreign key checking gets turned off, please add corresponding check methods
        await self.db.execute("PRAGMA foreign_keys=ON")

        async with self.db_wrapper.locked_transaction():
            await self.db.execute(
                "CREATE TABLE IF NOT EXISTS node("
                "hash TEXT PRIMARY KEY NOT NULL,"
                # " generation INTEGER NOT NULL",
                "node_type INTEGER NOT NULL,"
                "left TEXT REFERENCES node,"
                "right TEXT REFERENCES node,"
                "key TEXT,"
                "value TEXT"
                # "FOREIGN KEY(left) REFERENCES node(hash),"
                # " FOREIGN KEY(right) REFERENCES node(hash)"
                ")"
            )
            await self.db.execute(
                "CREATE TABLE IF NOT EXISTS root("
                "tree_id TEXT NOT NULL,"
                " generation INTEGER NOT NULL,"
                " node_hash TEXT,"
                " PRIMARY KEY(tree_id, generation),"
                " FOREIGN KEY(node_hash) REFERENCES node(hash)"
                ")"
            )

        return self

    async def _insert_root(self, tree_id: bytes32, node_hash: Optional[bytes32]) -> None:
        # TODO: maybe verify a transaction is active

        existing_generation = await self.get_tree_generation(tree_id=tree_id, lock=False)

        if existing_generation is None:
            generation = 0
        else:
            generation = existing_generation + 1

        await self.db.execute(
            "INSERT INTO root(tree_id, generation, node_hash) VALUES(:tree_id, :generation, :node_hash)",
            {
                "tree_id": tree_id.hex(),
                "generation": generation,
                "node_hash": None if node_hash is None else node_hash.hex(),
            },
        )

    async def _insert_internal_node(self, left_hash: bytes32, right_hash: bytes32) -> bytes32:
        # TODO: maybe verify a transaction is active

        # TODO: verify this is the hashing we want
        node_hash = Program.to((left_hash, right_hash)).get_tree_hash(left_hash, right_hash)

        # TODO: Review the OR IGNORE bit, should more be done to validate it is
        #       "the same row"?
        await self.db.execute(
            "INSERT OR IGNORE INTO node(hash, node_type, left, right, key, value)"
            " VALUES(:hash, :node_type, :left, :right, :key, :value)",
            {
                "hash": node_hash.hex(),
                "node_type": NodeType.INTERNAL,
                "left": left_hash.hex(),
                "right": right_hash.hex(),
                "key": None,
                "value": None,
            },
        )

        return node_hash

    async def _insert_terminal_node(self, key: Program, value: Program) -> bytes32:
        # TODO: maybe verify a transaction is active

        node_hash = Program.to((key, value)).get_tree_hash()

        await self.db.execute(
            """
            INSERT INTO node(hash, node_type, left, right, key, value)
            VALUES(:hash, :node_type, :left, :right, :key, :value)
            """,
            {
                "hash": node_hash.hex(),
                "node_type": NodeType.TERMINAL,
                "left": None,
                "right": None,
                "key": key.as_bin().hex(),
                "value": value.as_bin().hex(),
            },
        )

        return node_hash

    async def check(self) -> None:
        for check in self._checks:
            await check(self)

    async def _check_internal_key_value_are_null(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute(
                "SELECT * FROM node WHERE node_type == :node_type AND (key NOT NULL OR value NOT NULL)",
                {"node_type": NodeType.INTERNAL},
            )
            hashes = [hexstr_to_bytes(row["hash"]) async for row in cursor]

        if len(hashes) > 0:
            raise InternalKeyValueError(node_hashes=hashes)

    async def _check_internal_left_right_are_bytes32(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute(
                "SELECT * FROM node WHERE node_type == :node_type",
                {"node_type": NodeType.INTERNAL},
            )

            hashes = []
            async for row in cursor:
                try:
                    bytes32(hexstr_to_bytes(row["left"]))
                    bytes32(hexstr_to_bytes(row["right"]))
                except ValueError:
                    hashes.append(hexstr_to_bytes(row["hash"]))

        if len(hashes) > 0:
            raise InternalLeftRightNotBytes32Error(node_hashes=hashes)

    async def _check_terminal_left_right_are_null(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute(
                "SELECT * FROM node WHERE node_type == :node_type AND (left NOT NULL OR right NOT NULL)",
                {"node_type": NodeType.TERMINAL},
            )
            hashes = [hexstr_to_bytes(row["hash"]) async for row in cursor]

        if len(hashes) > 0:
            raise TerminalLeftRightError(node_hashes=hashes)

    async def _check_terminal_key_value_are_serialized_programs(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute(
                "SELECT * FROM node WHERE node_type == :node_type",
                {"node_type": NodeType.TERMINAL},
            )

            hashes = []
            async for row in cursor:
                try:
                    Program.fromhex(row["key"])
                    Program.fromhex(row["value"])
                except ValueError:
                    hashes.append(hexstr_to_bytes(row["hash"]))

        if len(hashes) > 0:
            raise TerminalInvalidKeyOrValueProgramError(node_hashes=hashes)

    async def _check_roots_are_incrementing(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute("SELECT * FROM root ORDER BY tree_id, generation")
            roots = [Root.from_row(row=row) async for row in cursor]

            roots_by_tree: Dict[bytes32, List[Root]] = defaultdict(list)
            for root in roots:
                roots_by_tree[root.tree_id].append(root)

            bad_trees = []
            for tree_id, roots in roots_by_tree.items():
                current_generation = roots[-1].generation
                expected_generations = list(range(current_generation + 1))
                actual_generations = [root.generation for root in roots]
                if actual_generations != expected_generations:
                    bad_trees.append(tree_id)

            if len(bad_trees) > 0:
                raise TreeGenerationIncrementingError(tree_ids=bad_trees)

    async def _check_hashes(self, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute("SELECT * FROM node")

            bad_node_hashes: bytes32 = []
            async for row in cursor:
                node = row_to_node(row=row)
                if isinstance(node, InternalNode):
                    expected_hash = Program.to((node.left_hash, node.right_hash)).get_tree_hash(
                        node.left_hash, node.right_hash
                    )
                elif isinstance(node, TerminalNode):
                    # TODO: what form of key and value to hash?  tuple or list for Program.to()?
                    # expected_hash = Program.to((node.key, node.value)).get_tree_hash()
                    expected_hash = Program.to((node.key, node.value)).get_tree_hash()

                if node.hash != expected_hash:
                    bad_node_hashes.append(node.hash)

        if len(bad_node_hashes) > 0:
            raise NodeHashError(node_hashes=bad_node_hashes)

    _checks: Tuple[Callable[["DataStore"], Awaitable[None]], ...] = (
        _check_internal_key_value_are_null,
        _check_internal_left_right_are_bytes32,
        _check_terminal_left_right_are_null,
        _check_terminal_key_value_are_serialized_programs,
        _check_roots_are_incrementing,
        _check_hashes,
    )

    async def create_tree(self, tree_id: bytes32, *, lock: bool = True) -> bool:
        async with self.db_wrapper.locked_transaction(lock=lock):
            await self._insert_root(tree_id=tree_id, node_hash=None)

        return True

    async def table_is_empty(self, tree_id: bytes32, *, lock: bool = True) -> bool:
        async with self.db_wrapper.locked_transaction(lock=lock):
            tree_root = await self.get_tree_root(tree_id=tree_id, lock=False)

        return tree_root.node_hash is None

    async def get_tree_ids(self, *, lock: bool = True) -> Set[bytes32]:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute("SELECT DISTINCT tree_id FROM root")

        tree_ids = {bytes32(hexstr_to_bytes(row["tree_id"])) async for row in cursor}

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

    async def get_tree_generation(self, tree_id: bytes32, *, lock: bool = True) -> int:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute(
                "SELECT MAX(generation) FROM root WHERE tree_id == :tree_id",
                {"tree_id": tree_id.hex()},
            )
            row = await cursor.fetchone()

        # TODO: real handling
        assert row is not None
        generation: int = row["MAX(generation)"]
        return generation

    async def get_tree_root(self, tree_id: bytes32, *, lock: bool = True) -> Root:
        async with self.db_wrapper.locked_transaction(lock=lock):
            generation = await self.get_tree_generation(tree_id=tree_id, lock=False)
            cursor = await self.db.execute(
                "SELECT * FROM root WHERE tree_id == :tree_id AND generation == :generation",
                {"tree_id": tree_id.hex(), "generation": generation},
            )
            [root_dict] = [row async for row in cursor]

        return Root.from_row(row=root_dict)

    # TODO: If we exclude the requested node from the result then we could have a
    #       consistent List[InternalNode] return type.
    async def get_ancestors(self, node_hash: bytes32, tree_id: bytes32, *, lock: bool = True) -> List[InternalNode]:
        async with self.db_wrapper.locked_transaction(lock=lock):
            root = await self.get_tree_root(tree_id=tree_id, lock=False)
            assert root.node_hash
            assert root  # todo handle errors
            cursor = await self.db.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(hash, node_type, left, right, key, value, depth) AS (
                        SELECT node.*, 0 AS depth FROM node WHERE node.hash == :root_hash
                        UNION ALL
                        SELECT node.*, tree_from_root_hash.depth + 1 AS depth FROM node, tree_from_root_hash
                        WHERE node.hash == tree_from_root_hash.left OR node.hash == tree_from_root_hash.right
                    ),
                    ancestors(hash, node_type, left, right, key, value, depth) AS (
                        SELECT node.*, NULL AS depth FROM node
                        WHERE node.left == :reference_hash OR node.right == :reference_hash
                        UNION ALL
                        SELECT node.*, NULL AS depth FROM node, ancestors
                        WHERE node.left == ancestors.hash OR node.right == ancestors.hash
                    )
                SELECT * FROM tree_from_root_hash INNER JOIN ancestors
                WHERE tree_from_root_hash.hash == ancestors.hash
                ORDER BY tree_from_root_hash.depth DESC
                """,
                {"reference_hash": node_hash.hex(), "root_hash": root.node_hash.hex()},
            )

            # The resulting rows must represent internal nodes.  InternalNode.from_row()
            # does some amount of validation in the sense that it will fail if left
            # or right can't turn into a bytes32 as expected.  There is room for more
            # validation here if desired.
            ancestors = [InternalNode.from_row(row=row) async for row in cursor]

        return ancestors

    async def get_pairs(self, tree_id: bytes32, *, lock: bool = True) -> List[TerminalNode]:
        async with self.db_wrapper.locked_transaction(lock=lock):
            root = await self.get_tree_root(tree_id=tree_id, lock=False)

            if root.node_hash is None:
                return []

            cursor = await self.db.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(hash, node_type, left, right, key, value, depth) AS (
                        SELECT node.*, 0 AS depth FROM node WHERE node.hash == :root_hash
                        UNION ALL
                        SELECT node.*, tree_from_root_hash.depth + 1 AS depth FROM node, tree_from_root_hash
                        WHERE node.hash == tree_from_root_hash.left OR node.hash == tree_from_root_hash.right
                    )
                SELECT * FROM tree_from_root_hash
                WHERE node_type == :node_type
                """,
                {"root_hash": root.node_hash.hex(), "node_type": NodeType.TERMINAL},
            )

            terminal_nodes: List[TerminalNode] = []
            async for row in cursor:
                node = row_to_node(row=row)
                assert isinstance(node, TerminalNode)
                terminal_nodes.append(node)

        return terminal_nodes

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
    #         "INSERT INTO node(hash, node_type, left, right, key, value)"
    #         " VALUE(:hash, :node_type, :left, :right, :key, :value)",
    #         {
    #             "hash": node_hash.hex(),
    #             "node_type": NodeType.INTERNAL,
    #             "left": left_hash.hex(),
    #             "right": right_hash.hex(),
    #             "key": None,
    #             "value": None,
    #         },
    #     )
    #
    #     return node_hash

    async def get_node_type(self, node_hash: bytes32, *, lock: bool = True) -> NodeType:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute("SELECT node_type FROM node WHERE hash == :hash", {"hash": node_hash.hex()})
            raw_node_type = await cursor.fetchone()
            # [node_type] = await cursor.fetchall()
            # TODO: i'm pretty curious why this one fails...
            # [node_type] = (NodeType(row["node_type"]) async for row in cursor)

        # TODO: real handling
        assert raw_node_type is not None

        return NodeType(raw_node_type["node_type"])

    async def insert(
        self,
        key: Program,
        value: Program,
        tree_id: bytes32,
        reference_node_hash: Optional[bytes32],
        side: Optional[Side],
        *,
        lock: bool = True,
    ) -> bytes32:
        async with self.db_wrapper.locked_transaction(lock=lock):
            was_empty = await self.table_is_empty(tree_id=tree_id, lock=False)
            root = await self.get_tree_root(tree_id=tree_id, lock=False)

            if not was_empty:
                # TODO: is there any way the db can enforce this?
                pairs = await self.get_pairs(tree_id=tree_id, lock=False)
                if any(key == node.key for node in pairs):
                    # TODO: more specific exception
                    raise Exception("key already present")

            if reference_node_hash is None:
                # TODO: tidy up and real exceptions
                assert was_empty
            else:
                reference_node_type = await self.get_node_type(node_hash=reference_node_hash, lock=False)
                if reference_node_type == NodeType.INTERNAL:
                    raise Exception("can not insert a new key/value on an internal node")

            # create new terminal node
            new_terminal_node_hash = await self._insert_terminal_node(key=key, value=value)

            if was_empty:
                # TODO: a real exception
                assert side is None

                await self._insert_root(tree_id=tree_id, node_hash=new_terminal_node_hash)
            else:
                # TODO: a real exception
                assert side is not None
                assert reference_node_hash is not None
                assert root.node_hash  # todo handle errors

                ancestors = await self.get_ancestors(node_hash=reference_node_hash, tree_id=tree_id, lock=False)

                # create the new internal node
                if side == Side.LEFT:
                    left = new_terminal_node_hash
                    right = reference_node_hash
                elif side == Side.RIGHT:
                    left = reference_node_hash
                    right = new_terminal_node_hash

                # create first new internal node
                new_hash = await self._insert_internal_node(left_hash=left, right_hash=right)

                traversal_node_hash = reference_node_hash

                # update the rest of the internal nodes
                for ancestor in ancestors:
                    # TODO: really handle
                    assert isinstance(ancestor, InternalNode)
                    if ancestor.left_hash == traversal_node_hash:
                        left = new_hash
                        right = ancestor.right_hash
                    elif ancestor.right_hash == traversal_node_hash:
                        left = ancestor.left_hash
                        right = new_hash

                    traversal_node_hash = ancestor.hash

                    new_hash = await self._insert_internal_node(left_hash=left, right_hash=right)

                await self._insert_root(tree_id=tree_id, node_hash=new_hash)

        return new_terminal_node_hash

    async def delete(self, key: Program, tree_id: bytes32, *, lock: bool = True) -> None:
        async with self.db_wrapper.locked_transaction(lock=lock):
            node = await self.get_node_by_key(key=key, tree_id=tree_id, lock=False)
            ancestors = await self.get_ancestors(node_hash=node.hash, tree_id=tree_id, lock=False)

            if len(ancestors) == 0:
                # the only node is being deleted
                await self._insert_root(tree_id=tree_id, node_hash=None)

                return

            parent = ancestors[0]
            other_hash = parent.other_child_hash(hash=node.hash)

            if len(ancestors) == 1:
                # the parent is the root so the other side will become the new root
                await self._insert_root(tree_id=tree_id, node_hash=other_hash)

                return

            old_child_hash = parent.hash
            new_child_hash = other_hash
            # more parents to handle so let's traverse them
            for ancestor in ancestors[1:]:
                if ancestor.left_hash == old_child_hash:
                    left_hash = new_child_hash
                    right_hash = ancestor.right_hash
                elif ancestor.right_hash == old_child_hash:
                    left_hash = ancestor.left_hash
                    right_hash = new_child_hash
                else:
                    # TODO real checking and errors
                    raise Exception("internal error")

                # TODO: handle if it already exists, recheck other places too.
                #       INSERT OR IGNORE?
                new_child_hash = await self._insert_internal_node(left_hash=left_hash, right_hash=right_hash)

                old_child_hash = ancestor.hash

            await self._insert_root(tree_id=tree_id, node_hash=new_child_hash)

        return

    async def get_node_by_key(self, key: Program, tree_id: bytes32, *, lock: bool = True) -> TerminalNode:
        async with self.db_wrapper.locked_transaction(lock=lock):
            nodes = await self.get_pairs(tree_id=tree_id, lock=False)

        for node in nodes:
            if node.key == key:
                return node

        # TODO: fill out the exception
        raise Exception("node not found")

    async def get_node_by_key_bytes(self, key: bytes32, tree_id: bytes32, *, lock: bool = True) -> TerminalNode:
        async with self.db_wrapper.locked_transaction(lock=lock):
            nodes = await self.get_pairs(tree_id=tree_id, lock=False)

        for node in nodes:
            if node.key.as_bin() == key:
                return node

        # TODO: fill out the exception
        raise Exception("node not found")

    async def get_node(self, node_hash: bytes32, *, lock: bool = True) -> Node:
        async with self.db_wrapper.locked_transaction(lock=lock):
            cursor = await self.db.execute("SELECT * FROM node WHERE hash == :hash", {"hash": node_hash.hex()})
            row = await cursor.fetchone()

        # TODO: really handle
        assert row is not None

        node = row_to_node(row=row)
        return node

    async def get_tree_as_program(self, tree_id: bytes32, *, lock: bool = True) -> Program:
        async with self.db_wrapper.locked_transaction(lock=lock):
            root = await self.get_tree_root(tree_id=tree_id, lock=False)
            root_node = await self.get_node(node_hash=root.node_hash, lock=False)

            # await self.db.execute("SELECT * FROM node WHERE node.left ==
            # :hash OR node.right == :hash", {"hash": root_node.hash})

            cursor = await self.db.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(hash, node_type, left, right, key, value) AS (
                        SELECT node.* FROM node WHERE node.hash == :root_hash
                        UNION ALL
                        SELECT node.* FROM node, tree_from_root_hash
                        WHERE node.hash == tree_from_root_hash.left OR node.hash == tree_from_root_hash.right
                    )
                SELECT * FROM tree_from_root_hash
                """,
                {"root_hash": root_node.hash.hex()},
            )
            nodes = [row_to_node(row=row) async for row in cursor]
            hash_to_node: Dict[bytes32, Node] = {}
            for node in reversed(nodes):
                # node = row_to_node(row)
                if isinstance(node, InternalNode):
                    node = replace(node, pair=(hash_to_node[node.left_hash], hash_to_node[node.right_hash]))
                hash_to_node[node.hash] = node

            # nodes = [row_to_node(row=row) async for row in cursor]
            print(" ++++++++++++++++++++++++++++++++++++++")
            root_node = hash_to_node[root_node.hash]
            print(root_node)
            # TODO: clvm needs py.typed, SExp.to() needs def to(class_: Type[T], v: CastableType) -> T:
            program: Program = Program.to(root_node)
            program.as_bin()
            print(program)
            print(program.as_bin())
            # for node in reversed(nodes):
            #     print('    ', node)
            # async for row in cursor:
            #     # row = {key: value.hex() for key, value in dict(row).items()}
            #     print(f"    {dict(row)}")
            print(" ++++++++++++++++++++++++++++++++++++++")

        return program

    # async def create_root(self, tree_id: bytes32, node_hash: bytes32):
    #     # generation = 0
    #
    #     async with self.db_wrapper.locked_transaction():
    #         await _debug_dump(db=self.db, description="before")
    #
    #         # await self.db.execute(
    #         #     "INSERT INTO node(hash, node_type, left, right, key, value)"
    #         #     " VALUES(:hash, :node_type, :left, :right, :key, :value)",
    #         #     {
    #         #         "hash": node_hash.hex(),
    #         #         "node_type": NodeType.EMPTY,
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
