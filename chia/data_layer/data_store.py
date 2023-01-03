from __future__ import annotations

import logging
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, BinaryIO, Callable, Dict, List, Optional, Set, Tuple, Union

import aiosqlite

from chia.data_layer.data_layer_errors import KeyNotFoundError, NodeHashError, TreeGenerationIncrementingError
from chia.data_layer.data_layer_util import (
    DiffData,
    InternalNode,
    Node,
    NodeType,
    OperationType,
    ProofOfInclusion,
    ProofOfInclusionLayer,
    Root,
    SerializedNode,
    ServerInfo,
    Side,
    Status,
    Subscription,
    TerminalNode,
    internal_hash,
    leaf_hash,
    row_to_node,
)
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import DBWrapper2

log = logging.getLogger(__name__)


# TODO: review exceptions for values that shouldn't be displayed
# TODO: pick exception types other than Exception


@dataclass
class DataStore:
    """A key/value store with the pairs being terminal nodes in a CLVM object tree."""

    db_wrapper: DBWrapper2

    @classmethod
    async def create(cls, database: Union[str, Path], uri: bool = False) -> "DataStore":
        db_wrapper = await DBWrapper2.create(
            database=database,
            uri=uri,
            journal_mode="WAL",
            # Setting to FULL despite other locations being configurable.  If there are
            # performance issues we can consider other the implications of other options.
            synchronous="FULL",
            # If foreign key checking gets turned off, please add corresponding check
            # methods and enable foreign key checking in the tests.
            foreign_keys=True,
            row_factory=aiosqlite.Row,
        )
        self = cls(db_wrapper=db_wrapper)

        async with db_wrapper.writer() as writer:
            await writer.execute(
                f"""
                CREATE TABLE IF NOT EXISTS node(
                    hash BLOB PRIMARY KEY NOT NULL CHECK(length(hash) == 32),
                    node_type INTEGER NOT NULL CHECK(
                        (
                            node_type == {int(NodeType.INTERNAL)}
                            AND left IS NOT NULL
                            AND right IS NOT NULL
                            AND key IS NULL
                            AND value IS NULL
                        )
                        OR
                        (
                            node_type == {int(NodeType.TERMINAL)}
                            AND left IS NULL
                            AND right IS NULL
                            AND key IS NOT NULL
                            AND value IS NOT NULL
                        )
                    ),
                    left BLOB REFERENCES node,
                    right BLOB REFERENCES node,
                    key BLOB,
                    value BLOB
                )
                """
            )
            await writer.execute(
                """
                CREATE TRIGGER IF NOT EXISTS no_node_updates
                BEFORE UPDATE ON node
                BEGIN
                    SELECT RAISE(FAIL, 'updates not allowed to the node table');
                END
                """
            )
            await writer.execute(
                f"""
                CREATE TABLE IF NOT EXISTS root(
                    tree_id BLOB NOT NULL CHECK(length(tree_id) == 32),
                    generation INTEGER NOT NULL CHECK(generation >= 0),
                    node_hash BLOB,
                    status INTEGER NOT NULL CHECK(
                        {" OR ".join(f"status == {status}" for status in Status)}
                    ),
                    PRIMARY KEY(tree_id, generation),
                    FOREIGN KEY(node_hash) REFERENCES node(hash)
                )
                """
            )
            # TODO: Add ancestor -> hash relationship, this might involve temporarily
            # deferring the foreign key enforcement due to the insertion order
            # and the node table also enforcing a similar relationship in the
            # other direction.
            # FOREIGN KEY(ancestor) REFERENCES ancestors(ancestor)
            await writer.execute(
                """
                CREATE TABLE IF NOT EXISTS ancestors(
                    hash BLOB NOT NULL REFERENCES node,
                    ancestor BLOB CHECK(length(ancestor) == 32),
                    tree_id BLOB NOT NULL CHECK(length(tree_id) == 32),
                    generation INTEGER NOT NULL,
                    PRIMARY KEY(hash, tree_id, generation),
                    FOREIGN KEY(ancestor) REFERENCES node(hash)
                )
                """
            )
            await writer.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions(
                    tree_id BLOB NOT NULL CHECK(length(tree_id) == 32),
                    url TEXT,
                    ignore_till INTEGER,
                    num_consecutive_failures INTEGER,
                    from_wallet tinyint CHECK(from_wallet == 0 OR from_wallet == 1),
                    PRIMARY KEY(tree_id, url)
                )
                """
            )
            await writer.execute(
                """
                CREATE INDEX IF NOT EXISTS node_hash ON root(node_hash)
                """
            )

        return self

    async def close(self) -> None:
        await self.db_wrapper.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self.db_wrapper.writer():
            yield

    async def _insert_root(
        self,
        tree_id: bytes32,
        node_hash: Optional[bytes32],
        status: Status,
        generation: Optional[int] = None,
    ) -> None:
        # This should be replaced by an SQLite schema level check.
        # https://github.com/Chia-Network/chia-blockchain/pull/9284
        tree_id = bytes32(tree_id)

        async with self.db_wrapper.writer() as writer:
            if generation is None:
                existing_generation = await self.get_tree_generation(tree_id=tree_id)

                if existing_generation is None:
                    generation = 0
                else:
                    generation = existing_generation + 1

            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                {
                    "tree_id": tree_id,
                    "generation": generation,
                    "node_hash": None if node_hash is None else node_hash,
                    "status": status.value,
                },
            )

            # `node_hash` is now a root, so it has no ancestor.
            # Don't change the ancestor table unless the root is committed.
            if node_hash is not None and status == Status.COMMITTED:
                values = {
                    "hash": node_hash,
                    "tree_id": tree_id,
                    "generation": generation,
                }
                await writer.execute(
                    """
                    INSERT INTO ancestors(hash, ancestor, tree_id, generation)
                    VALUES (:hash, NULL, :tree_id, :generation)
                    """,
                    values,
                )

    async def _insert_node(
        self,
        node_hash: bytes32,
        node_type: NodeType,
        left_hash: Optional[bytes32],
        right_hash: Optional[bytes32],
        key: Optional[bytes],
        value: Optional[bytes],
    ) -> None:
        # TODO: can we get sqlite to do this check?
        values = {
            "hash": node_hash,
            "node_type": node_type,
            "left": left_hash,
            "right": right_hash,
            "key": key,
            "value": value,
        }

        async with self.db_wrapper.writer() as writer:
            cursor = await writer.execute("SELECT * FROM node WHERE hash == :hash", {"hash": node_hash})
            result = await cursor.fetchone()

            if result is None:
                await writer.execute(
                    """
                    INSERT INTO node(hash, node_type, left, right, key, value)
                    VALUES(:hash, :node_type, :left, :right, :key, :value)
                    """,
                    values,
                )
            else:
                result_dict = dict(result)
                if result_dict != values:
                    raise Exception(
                        f"Requested insertion of node with matching hash but other values differ: {node_hash}"
                    )

    async def insert_node(self, node_type: NodeType, value1: bytes, value2: bytes) -> None:
        if node_type == NodeType.INTERNAL:
            left_hash = bytes32(value1)
            right_hash = bytes32(value2)
            node_hash = internal_hash(left_hash, right_hash)
            await self._insert_node(node_hash, node_type, bytes32(value1), bytes32(value2), None, None)
        else:
            node_hash = leaf_hash(key=value1, value=value2)
            await self._insert_node(node_hash, node_type, None, None, value1, value2)

    async def _insert_internal_node(self, left_hash: bytes32, right_hash: bytes32) -> bytes32:
        node_hash: bytes32 = internal_hash(left_hash=left_hash, right_hash=right_hash)

        await self._insert_node(
            node_hash=node_hash,
            node_type=NodeType.INTERNAL,
            left_hash=left_hash,
            right_hash=right_hash,
            key=None,
            value=None,
        )

        return node_hash

    async def _insert_ancestor_table(
        self,
        left_hash: bytes32,
        right_hash: bytes32,
        tree_id: bytes32,
        generation: int,
    ) -> None:
        node_hash = internal_hash(left_hash=left_hash, right_hash=right_hash)

        async with self.db_wrapper.writer() as writer:
            for hash in (left_hash, right_hash):
                values = {
                    "hash": hash,
                    "ancestor": node_hash,
                    "tree_id": tree_id,
                    "generation": generation,
                }
                cursor = await writer.execute(
                    "SELECT * FROM ancestors WHERE hash == :hash AND generation == :generation AND tree_id == :tree_id",
                    {"hash": hash, "generation": generation, "tree_id": tree_id},
                )
                result = await cursor.fetchone()
                if result is None:
                    await writer.execute(
                        """
                        INSERT INTO ancestors(hash, ancestor, tree_id, generation)
                        VALUES (:hash, :ancestor, :tree_id, :generation)
                        """,
                        values,
                    )
                else:
                    result_dict = dict(result)
                    if result_dict != values:
                        raise Exception(
                            "Requested insertion of ancestor, where ancestor differ, but other values are identical: "
                            f"{hash} {generation} {tree_id}"
                        )

    async def _insert_terminal_node(self, key: bytes, value: bytes) -> bytes32:
        # forcing type hint here for:
        # https://github.com/Chia-Network/clvm/pull/102
        # https://github.com/Chia-Network/clvm/pull/106
        node_hash: bytes32 = Program.to((key, value)).get_tree_hash()

        await self._insert_node(
            node_hash=node_hash,
            node_type=NodeType.TERMINAL,
            left_hash=None,
            right_hash=None,
            key=key,
            value=value,
        )

        return node_hash

    async def get_pending_root(self, tree_id: bytes32) -> Optional[Root]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT * FROM root WHERE tree_id == :tree_id AND status == :status",
                {"tree_id": tree_id, "status": Status.PENDING.value},
            )

            row = await cursor.fetchone()

            if row is None:
                return None

            maybe_extra_result = await cursor.fetchone()
            if maybe_extra_result is not None:
                raise Exception(f"multiple pending roots found for id: {tree_id.hex()}")

        return Root.from_row(row=row)

    async def clear_pending_roots(self, tree_id: bytes32) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "DELETE FROM root WHERE tree_id == :tree_id AND status == :status",
                {"tree_id": tree_id, "status": Status.PENDING.value},
            )

    async def shift_root_generations(self, tree_id: bytes32, shift_size: int) -> None:
        async with self.db_wrapper.writer():
            root = await self.get_tree_root(tree_id=tree_id)
            for _ in range(shift_size):
                await self._insert_root(tree_id=tree_id, node_hash=root.node_hash, status=Status.COMMITTED)

    async def change_root_status(self, root: Root, status: Status = Status.PENDING) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "UPDATE root SET status = ? WHERE tree_id=? and generation = ?",
                (
                    status.value,
                    root.tree_id,
                    root.generation,
                ),
            )
            # `node_hash` is now a root, so it has no ancestor.
            # Don't change the ancestor table unless the root is committed.
            if root.node_hash is not None and status == Status.COMMITTED:
                values = {
                    "hash": root.node_hash,
                    "tree_id": root.tree_id,
                    "generation": root.generation,
                }
                await writer.execute(
                    """
                    INSERT INTO ancestors(hash, ancestor, tree_id, generation)
                    VALUES (:hash, NULL, :tree_id, :generation)
                    """,
                    values,
                )

    async def check(self) -> None:
        for check in self._checks:
            # pylint seems to think these are bound methods not unbound methods.
            await check(self)  # pylint: disable=too-many-function-args

    async def _check_roots_are_incrementing(self) -> None:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT * FROM root ORDER BY tree_id, generation")
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

    async def _check_hashes(self) -> None:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT * FROM node")

            bad_node_hashes: List[bytes32] = []
            async for row in cursor:
                node = row_to_node(row=row)
                if isinstance(node, InternalNode):
                    expected_hash = internal_hash(left_hash=node.left_hash, right_hash=node.right_hash)
                elif isinstance(node, TerminalNode):
                    expected_hash = Program.to((node.key, node.value)).get_tree_hash()

                if node.hash != expected_hash:
                    bad_node_hashes.append(node.hash)

        if len(bad_node_hashes) > 0:
            raise NodeHashError(node_hashes=bad_node_hashes)

    _checks: Tuple[Callable[["DataStore"], Awaitable[None]], ...] = (
        _check_roots_are_incrementing,
        _check_hashes,
    )

    async def create_tree(self, tree_id: bytes32, status: Status = Status.PENDING) -> bool:
        await self._insert_root(tree_id=tree_id, node_hash=None, status=status)

        return True

    async def table_is_empty(self, tree_id: bytes32) -> bool:
        tree_root = await self.get_tree_root(tree_id=tree_id)

        return tree_root.node_hash is None

    async def get_tree_ids(self) -> Set[bytes32]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT DISTINCT tree_id FROM root")

            tree_ids = {bytes32(row["tree_id"]) async for row in cursor}

        return tree_ids

    async def get_tree_generation(self, tree_id: bytes32) -> int:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT MAX(generation) FROM root WHERE tree_id == :tree_id AND status == :status",
                {"tree_id": tree_id, "status": Status.COMMITTED.value},
            )
            row = await cursor.fetchone()

        if row is None:
            raise Exception(f"No generations found for tree ID: {tree_id.hex()}")
        generation: int = row["MAX(generation)"]
        return generation

    async def get_tree_root(self, tree_id: bytes32, generation: Optional[int] = None) -> Root:
        async with self.db_wrapper.reader() as reader:
            if generation is None:
                generation = await self.get_tree_generation(tree_id=tree_id)
            cursor = await reader.execute(
                "SELECT * FROM root WHERE tree_id == :tree_id AND generation == :generation AND status == :status",
                {"tree_id": tree_id, "generation": generation, "status": Status.COMMITTED.value},
            )
            row = await cursor.fetchone()

            if row is None:
                raise Exception(f"unable to find root for id, generation: {tree_id.hex()}, {generation}")

            maybe_extra_result = await cursor.fetchone()
            if maybe_extra_result is not None:
                raise Exception(f"multiple roots found for id, generation: {tree_id.hex()}, {generation}")

        return Root.from_row(row=row)

    async def tree_id_exists(self, tree_id: bytes32) -> bool:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT 1 FROM root WHERE tree_id == :tree_id AND status == :status",
                {"tree_id": tree_id, "status": Status.COMMITTED.value},
            )
            row = await cursor.fetchone()

        if row is None:
            return False
        return True

    async def get_roots_between(self, tree_id: bytes32, generation_begin: int, generation_end: int) -> List[Root]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT * FROM root WHERE tree_id == :tree_id "
                "AND generation >= :generation_begin AND generation < :generation_end ORDER BY generation ASC",
                {"tree_id": tree_id, "generation_begin": generation_begin, "generation_end": generation_end},
            )
            roots = [Root.from_row(row=row) async for row in cursor]

        return roots

    async def get_last_tree_root_by_hash(
        self, tree_id: bytes32, hash: Optional[bytes32], max_generation: Optional[int] = None
    ) -> Optional[Root]:
        async with self.db_wrapper.reader() as reader:
            max_generation_str = f"AND generation < {max_generation} " if max_generation is not None else ""
            node_hash_str = "AND node_hash == :node_hash " if hash is not None else "AND node_hash is NULL "
            cursor = await reader.execute(
                "SELECT * FROM root WHERE tree_id == :tree_id "
                f"{max_generation_str}"
                f"{node_hash_str}"
                "ORDER BY generation DESC LIMIT 1",
                {"tree_id": tree_id, "node_hash": None if hash is None else hash},
            )
            row = await cursor.fetchone()

        if row is None:
            return None
        return Root.from_row(row=row)

    async def get_ancestors(
        self,
        node_hash: bytes32,
        tree_id: bytes32,
        root_hash: Optional[bytes32] = None,
    ) -> List[InternalNode]:
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(tree_id=tree_id)
                root_hash = root.node_hash
            if root_hash is None:
                raise Exception(f"Root hash is unspecified for tree ID: {tree_id.hex()}")
            cursor = await reader.execute(
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
                {"reference_hash": node_hash, "root_hash": root_hash},
            )

            # The resulting rows must represent internal nodes.  InternalNode.from_row()
            # does some amount of validation in the sense that it will fail if left
            # or right can't turn into a bytes32 as expected.  There is room for more
            # validation here if desired.
            ancestors = [InternalNode.from_row(row=row) async for row in cursor]

        return ancestors

    async def get_ancestors_optimized(
        self, node_hash: bytes32, tree_id: bytes32, generation: Optional[int] = None
    ) -> List[InternalNode]:
        async with self.db_wrapper.reader():
            nodes = []
            root = await self.get_tree_root(tree_id=tree_id, generation=generation)
            if root.node_hash is None:
                return []

            while True:
                internal_node = await self._get_one_ancestor(node_hash, tree_id, generation)
                if internal_node is None:
                    break
                nodes.append(internal_node)
                node_hash = internal_node.hash

            if len(nodes) > 0:
                if root.node_hash != nodes[-1].hash:
                    raise RuntimeError("Ancestors list didn't produce the root as top result.")

            return nodes

    async def get_internal_nodes(self, tree_id: bytes32, root_hash: Optional[bytes32] = None) -> List[InternalNode]:
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(tree_id=tree_id)
                root_hash = root.node_hash
            cursor = await reader.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(hash, node_type, left, right, key, value) AS (
                        SELECT node.* FROM node WHERE node.hash == :root_hash
                        UNION ALL
                        SELECT node.* FROM node, tree_from_root_hash WHERE node.hash == tree_from_root_hash.left
                        OR node.hash == tree_from_root_hash.right
                    )
                SELECT * FROM tree_from_root_hash
                WHERE node_type == :node_type
                """,
                {"root_hash": None if root_hash is None else root_hash, "node_type": NodeType.INTERNAL},
            )

            internal_nodes: List[InternalNode] = []
            async for row in cursor:
                node = row_to_node(row=row)
                if not isinstance(node, InternalNode):
                    raise Exception(f"Unexpected internal node found: {node.hash.hex()}")
                internal_nodes.append(node)

        return internal_nodes

    async def get_keys_values(self, tree_id: bytes32, root_hash: Optional[bytes32] = None) -> List[TerminalNode]:
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(tree_id=tree_id)
                root_hash = root.node_hash
            cursor = await reader.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(hash, node_type, left, right, key, value, depth, rights) AS (
                        SELECT node.*, 0 AS depth, 0 AS rights FROM node WHERE node.hash == :root_hash
                        UNION ALL
                        SELECT
                            node.*,
                            tree_from_root_hash.depth + 1 AS depth,
                            CASE
                                WHEN node.hash == tree_from_root_hash.right
                                THEN tree_from_root_hash.rights + (1 << (62 - tree_from_root_hash.depth))
                                ELSE tree_from_root_hash.rights
                                END AS rights
                            FROM node, tree_from_root_hash
                        WHERE node.hash == tree_from_root_hash.left OR node.hash == tree_from_root_hash.right
                    )
                SELECT * FROM tree_from_root_hash
                WHERE node_type == :node_type
                ORDER BY depth ASC, rights ASC
                """,
                {"root_hash": None if root_hash is None else root_hash, "node_type": NodeType.TERMINAL},
            )

            terminal_nodes: List[TerminalNode] = []
            async for row in cursor:
                if row["depth"] > 62:
                    # TODO: Review the value and implementation of left-to-right order
                    #       reporting.  Initial use is for balanced insertion with the
                    #       work done in the query.

                    # This is limited based on the choice of 63 for the maximum left
                    # shift in the query.  This is in turn based on the SQLite integers
                    # ranging in size up to signed 8 bytes, 64 bits.  If we exceed this then
                    # we no longer guarantee the left-to-right ordering of the node
                    # list.  While 63 allows for a lot of nodes in a balanced tree, in
                    # the worst case it allows only 62 terminal nodes.
                    raise Exception("Tree depth exceeded 62, unable to guarantee left-to-right node order.")
                node = row_to_node(row=row)
                if not isinstance(node, TerminalNode):
                    raise Exception(f"Unexpected internal node found: {node.hash.hex()}")
                terminal_nodes.append(node)

        return terminal_nodes

    async def get_node_type(self, node_hash: bytes32) -> NodeType:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT node_type FROM node WHERE hash == :hash", {"hash": node_hash})
            raw_node_type = await cursor.fetchone()

        if raw_node_type is None:
            raise Exception(f"No node found for specified hash: {node_hash.hex()}")

        return NodeType(raw_node_type["node_type"])

    async def get_terminal_node_for_seed(self, tree_id: bytes32, seed: bytes32) -> Optional[bytes32]:
        path = int.from_bytes(seed, byteorder="big")
        async with self.db_wrapper.reader():
            root = await self.get_tree_root(tree_id)
            if root is None or root.node_hash is None:
                return None
            node_hash = root.node_hash
            while True:
                node = await self.get_node(node_hash)
                assert node is not None
                if isinstance(node, TerminalNode):
                    break
                if path % 2 == 0:
                    node_hash = node.left_hash
                else:
                    node_hash = node.right_hash
                path = path // 2

            return node_hash

    def get_side_for_seed(self, seed: bytes32) -> Side:
        side_seed = bytes(seed)[0]
        return Side.LEFT if side_seed < 128 else Side.RIGHT

    async def autoinsert(
        self,
        key: bytes,
        value: bytes,
        tree_id: bytes32,
        hint_keys_values: Optional[Dict[bytes, bytes]] = None,
        use_optimized: bool = True,
        status: Status = Status.PENDING,
    ) -> bytes32:
        async with self.db_wrapper.writer():
            was_empty = await self.table_is_empty(tree_id=tree_id)
            if was_empty:
                reference_node_hash = None
                side = None
            else:
                seed = leaf_hash(key=key, value=value)
                reference_node_hash = await self.get_terminal_node_for_seed(tree_id, seed)
                side = self.get_side_for_seed(seed)

            return await self.insert(
                key=key,
                value=value,
                tree_id=tree_id,
                reference_node_hash=reference_node_hash,
                side=side,
                hint_keys_values=hint_keys_values,
                use_optimized=use_optimized,
                status=status,
            )

    async def get_keys_values_dict(self, tree_id: bytes32) -> Dict[bytes, bytes]:
        pairs = await self.get_keys_values(tree_id=tree_id)
        return {node.key: node.value for node in pairs}

    async def get_keys(self, tree_id: bytes32, root_hash: Optional[bytes32] = None) -> List[bytes]:
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(tree_id=tree_id)
                root_hash = root.node_hash
            cursor = await reader.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(hash, node_type, left, right, key) AS (
                        SELECT node.hash, node.node_type, node.left, node.right, node.key
                        FROM node WHERE node.hash == :root_hash
                        UNION ALL
                        SELECT
                            node.hash, node.node_type, node.left, node.right, node.key FROM node, tree_from_root_hash
                        WHERE node.hash == tree_from_root_hash.left OR node.hash == tree_from_root_hash.right
                    )
                SELECT key FROM tree_from_root_hash WHERE node_type == :node_type
                """,
                {"root_hash": None if root_hash is None else root_hash, "node_type": NodeType.TERMINAL},
            )

            keys: List[bytes] = [row["key"] async for row in cursor]

        return keys

    async def insert(
        self,
        key: bytes,
        value: bytes,
        tree_id: bytes32,
        reference_node_hash: Optional[bytes32],
        side: Optional[Side],
        hint_keys_values: Optional[Dict[bytes, bytes]] = None,
        use_optimized: bool = True,
        status: Status = Status.PENDING,
    ) -> bytes32:
        async with self.db_wrapper.writer():
            was_empty = await self.table_is_empty(tree_id=tree_id)
            root = await self.get_tree_root(tree_id=tree_id)

            if not was_empty:
                if hint_keys_values is None:
                    # TODO: is there any way the db can enforce this?
                    pairs = await self.get_keys_values(tree_id=tree_id)
                    if any(key == node.key for node in pairs):
                        raise Exception(f"Key already present: {key.hex()}")
                else:
                    if bytes(key) in hint_keys_values:
                        raise Exception(f"Key already present: {key.hex()}")

            if reference_node_hash is None:
                if not was_empty:
                    raise Exception(f"Reference node hash must be specified for non-empty tree: {tree_id.hex()}")
            else:
                reference_node_type = await self.get_node_type(node_hash=reference_node_hash)
                if reference_node_type == NodeType.INTERNAL:
                    raise Exception("can not insert a new key/value on an internal node")

            # create new terminal node
            new_terminal_node_hash = await self._insert_terminal_node(key=key, value=value)

            if was_empty:
                if side is not None:
                    raise Exception("Tree was empty so side must be unspecified, got: {side!r}")

                await self._insert_root(
                    tree_id=tree_id,
                    node_hash=new_terminal_node_hash,
                    status=status,
                )
            else:
                if side is None:
                    raise Exception("Tree was not empty, side must be specified.")
                if reference_node_hash is None:
                    raise Exception("Tree was not empty, reference node hash must be specified.")
                if root.node_hash is None:
                    raise Exception("Internal error.")

                if use_optimized:
                    ancestors: List[InternalNode] = await self.get_ancestors_optimized(
                        node_hash=reference_node_hash, tree_id=tree_id
                    )
                else:
                    ancestors = await self.get_ancestors_optimized(node_hash=reference_node_hash, tree_id=tree_id)
                    ancestors_2: List[InternalNode] = await self.get_ancestors(
                        node_hash=reference_node_hash, tree_id=tree_id
                    )
                    if ancestors != ancestors_2:
                        raise RuntimeError("Ancestors optimized didn't produce the expected result.")

                if side == Side.LEFT:
                    left = new_terminal_node_hash
                    right = reference_node_hash
                elif side == Side.RIGHT:
                    left = reference_node_hash
                    right = new_terminal_node_hash

                if len(ancestors) >= 62:
                    raise RuntimeError("Tree exceeds max height of 62.")

                # update ancestors after inserting root, to keep table constraints.
                insert_ancestors_cache: List[Tuple[bytes32, bytes32, bytes32]] = []
                new_generation = root.generation + 1
                # create first new internal node
                new_hash = await self._insert_internal_node(left_hash=left, right_hash=right)
                insert_ancestors_cache.append((left, right, tree_id))
                traversal_node_hash = reference_node_hash

                # create updated replacements for the rest of the internal nodes
                for ancestor in ancestors:
                    if not isinstance(ancestor, InternalNode):
                        raise Exception(f"Expected an internal node but got: {type(ancestor).__name__}")

                    if ancestor.left_hash == traversal_node_hash:
                        left = new_hash
                        right = ancestor.right_hash
                    elif ancestor.right_hash == traversal_node_hash:
                        left = ancestor.left_hash
                        right = new_hash

                    traversal_node_hash = ancestor.hash

                    new_hash = await self._insert_internal_node(left_hash=left, right_hash=right)
                    insert_ancestors_cache.append((left, right, tree_id))

                await self._insert_root(
                    tree_id=tree_id,
                    node_hash=new_hash,
                    status=status,
                )
                if status == Status.COMMITTED:
                    for left_hash, right_hash, tree_id in insert_ancestors_cache:
                        await self._insert_ancestor_table(left_hash, right_hash, tree_id, new_generation)

        if hint_keys_values is not None:
            hint_keys_values[bytes(key)] = value
        return new_terminal_node_hash

    async def delete(
        self,
        key: bytes,
        tree_id: bytes32,
        hint_keys_values: Optional[Dict[bytes, bytes]] = None,
        use_optimized: bool = True,
        status: Status = Status.PENDING,
    ) -> None:
        async with self.db_wrapper.writer():
            if hint_keys_values is None:
                node = await self.get_node_by_key(key=key, tree_id=tree_id)
            else:
                if bytes(key) not in hint_keys_values:
                    log.debug(f"Request to delete an unknown key ignored: {key.hex()}")
                    return
                value = hint_keys_values[bytes(key)]
                node_hash = leaf_hash(key=key, value=value)
                node = TerminalNode(node_hash, key, value)
                del hint_keys_values[bytes(key)]
            if use_optimized:
                ancestors: List[InternalNode] = await self.get_ancestors_optimized(node_hash=node.hash, tree_id=tree_id)
            else:
                ancestors = await self.get_ancestors_optimized(node_hash=node.hash, tree_id=tree_id)
                ancestors_2: List[InternalNode] = await self.get_ancestors(node_hash=node.hash, tree_id=tree_id)
                if ancestors != ancestors_2:
                    raise RuntimeError("Ancestors optimized didn't produce the expected result.")

            if len(ancestors) > 62:
                raise RuntimeError("Tree exceeded max height of 62.")
            if len(ancestors) == 0:
                # the only node is being deleted
                await self._insert_root(
                    tree_id=tree_id,
                    node_hash=None,
                    status=status,
                )

                return

            parent = ancestors[0]
            other_hash = parent.other_child_hash(hash=node.hash)

            if len(ancestors) == 1:
                # the parent is the root so the other side will become the new root
                await self._insert_root(
                    tree_id=tree_id,
                    node_hash=other_hash,
                    status=status,
                )

                return

            old_child_hash = parent.hash
            new_child_hash = other_hash
            new_generation = await self.get_tree_generation(tree_id) + 1
            # update ancestors after inserting root, to keep table constraints.
            insert_ancestors_cache: List[Tuple[bytes32, bytes32, bytes32]] = []
            # more parents to handle so let's traverse them
            for ancestor in ancestors[1:]:
                if ancestor.left_hash == old_child_hash:
                    left_hash = new_child_hash
                    right_hash = ancestor.right_hash
                elif ancestor.right_hash == old_child_hash:
                    left_hash = ancestor.left_hash
                    right_hash = new_child_hash
                else:
                    raise Exception("Internal error.")

                new_child_hash = await self._insert_internal_node(left_hash=left_hash, right_hash=right_hash)
                insert_ancestors_cache.append((left_hash, right_hash, tree_id))
                old_child_hash = ancestor.hash

            await self._insert_root(
                tree_id=tree_id,
                node_hash=new_child_hash,
                status=status,
            )
            if status == Status.COMMITTED:
                for left_hash, right_hash, tree_id in insert_ancestors_cache:
                    await self._insert_ancestor_table(left_hash, right_hash, tree_id, new_generation)

        return

    async def insert_batch(
        self,
        tree_id: bytes32,
        changelist: List[Dict[str, Any]],
        status: Status = Status.PENDING,
    ) -> Optional[bytes32]:
        async with self.db_wrapper.writer():
            hint_keys_values = await self.get_keys_values_dict(tree_id)
            old_root = await self.get_tree_root(tree_id)
            for change in changelist:
                if change["action"] == "insert":
                    key = change["key"]
                    value = change["value"]
                    reference_node_hash = change.get("reference_node_hash", None)
                    side = change.get("side", None)
                    if reference_node_hash is None and side is None:
                        await self.autoinsert(key, value, tree_id, hint_keys_values, True, Status.COMMITTED)
                    else:
                        if reference_node_hash is None or side is None:
                            raise Exception("Provide both reference_node_hash and side or neither.")
                        await self.insert(
                            key,
                            value,
                            tree_id,
                            reference_node_hash,
                            side,
                            hint_keys_values,
                            True,
                            Status.COMMITTED,
                        )
                elif change["action"] == "delete":
                    key = change["key"]
                    await self.delete(key, tree_id, hint_keys_values, True, Status.COMMITTED)
                else:
                    raise Exception(f"Operation in batch is not insert or delete: {change}")

            root = await self.get_tree_root(tree_id=tree_id)
            if root.node_hash == old_root.node_hash:
                if len(changelist) != 0:
                    await self.rollback_to_generation(tree_id, old_root.generation)
                raise ValueError("Changelist resulted in no change to tree data")
            # We delete all "temporary" records stored in root and ancestor tables and store only the final result.
            await self.rollback_to_generation(tree_id, old_root.generation)
            await self.insert_root_with_ancestor_table(tree_id=tree_id, node_hash=root.node_hash, status=status)
            if status == Status.PENDING:
                new_root = await self.get_pending_root(tree_id=tree_id)
                assert new_root is not None
            elif status == Status.COMMITTED:
                new_root = await self.get_tree_root(tree_id=tree_id)
            else:
                raise Exception(f"No known status: {status}")
            if new_root.node_hash != root.node_hash:
                raise RuntimeError(
                    f"Tree root mismatches after batch update: Expected: {root.node_hash}. Got: {new_root.node_hash}"
                )
            if new_root.generation != old_root.generation + 1:
                raise RuntimeError(
                    "Didn't get the expected generation after batch update: "
                    f"Expected: {old_root.generation + 1}. Got: {new_root.generation}"
                )
            return root.node_hash

    async def _get_one_ancestor(
        self,
        node_hash: bytes32,
        tree_id: bytes32,
        generation: Optional[int] = None,
    ) -> Optional[InternalNode]:
        async with self.db_wrapper.reader() as reader:
            if generation is None:
                generation = await self.get_tree_generation(tree_id=tree_id)
            cursor = await reader.execute(
                """
                SELECT * from node INNER JOIN (
                    SELECT ancestors.ancestor AS hash, MAX(ancestors.generation) AS generation
                    FROM ancestors
                    WHERE ancestors.hash == :hash
                    AND ancestors.tree_id == :tree_id
                    AND ancestors.generation <= :generation
                    GROUP BY hash
                ) asc on asc.hash == node.hash
                """,
                {"hash": node_hash, "tree_id": tree_id, "generation": generation},
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return InternalNode.from_row(row=row)

    async def build_ancestor_table_for_latest_root(self, tree_id: bytes32) -> None:
        async with self.db_wrapper.writer():
            root = await self.get_tree_root(tree_id=tree_id)
            if root.node_hash is None:
                return
            previous_root = await self.get_tree_root(
                tree_id=tree_id,
                generation=max(root.generation - 1, 0),
            )

            if previous_root.node_hash is not None:
                previous_internal_nodes: List[InternalNode] = await self.get_internal_nodes(
                    tree_id=tree_id,
                    root_hash=previous_root.node_hash,
                )
                known_hashes: Set[bytes32] = set(node.hash for node in previous_internal_nodes)
            else:
                known_hashes = set()
            internal_nodes: List[InternalNode] = await self.get_internal_nodes(
                tree_id=tree_id,
                root_hash=root.node_hash,
            )
            for node in internal_nodes:
                # We already have the same values in ancestor tables, if we have the same internal node.
                # Don't reinsert it so we can save DB space.
                if node.hash not in known_hashes:
                    await self._insert_ancestor_table(node.left_hash, node.right_hash, tree_id, root.generation)

    async def insert_root_with_ancestor_table(
        self, tree_id: bytes32, node_hash: Optional[bytes32], status: Status = Status.PENDING
    ) -> None:
        async with self.db_wrapper.writer():
            await self._insert_root(tree_id=tree_id, node_hash=node_hash, status=status)
            # Don't update the ancestor table for non-committed status.
            if status == Status.COMMITTED:
                await self.build_ancestor_table_for_latest_root(tree_id=tree_id)

    async def get_node_by_key(
        self,
        key: bytes,
        tree_id: bytes32,
        root_hash: Optional[bytes32] = None,
    ) -> TerminalNode:
        nodes = await self.get_keys_values(tree_id=tree_id, root_hash=root_hash)

        for node in nodes:
            if node.key == key:
                return node

        raise KeyNotFoundError(key=key)

    async def get_node(self, node_hash: bytes32) -> Node:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT * FROM node WHERE hash == :hash", {"hash": node_hash})
            row = await cursor.fetchone()

        if row is None:
            raise Exception(f"Node not found for requested hash: {node_hash.hex()}")

        node = row_to_node(row=row)
        return node

    async def get_tree_as_program(self, tree_id: bytes32) -> Program:
        async with self.db_wrapper.reader() as reader:
            root = await self.get_tree_root(tree_id=tree_id)
            # TODO: consider actual proper behavior
            assert root.node_hash is not None
            root_node = await self.get_node(node_hash=root.node_hash)

            cursor = await reader.execute(
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
                {"root_hash": root_node.hash},
            )
            nodes = [row_to_node(row=row) async for row in cursor]
            hash_to_node: Dict[bytes32, Node] = {}
            for node in reversed(nodes):
                if isinstance(node, InternalNode):
                    node = replace(node, pair=(hash_to_node[node.left_hash], hash_to_node[node.right_hash]))
                hash_to_node[node.hash] = node

            root_node = hash_to_node[root_node.hash]
            # TODO: Remove ignore when done.
            #       https://github.com/Chia-Network/clvm/pull/102
            #       https://github.com/Chia-Network/clvm/pull/106
            program: Program = Program.to(root_node)

        return program

    async def get_proof_of_inclusion_by_hash(
        self,
        node_hash: bytes32,
        tree_id: bytes32,
        root_hash: Optional[bytes32] = None,
    ) -> ProofOfInclusion:
        """Collect the information for a proof of inclusion of a hash in the Merkle
        tree.
        """
        ancestors = await self.get_ancestors(node_hash=node_hash, tree_id=tree_id, root_hash=root_hash)

        layers: List[ProofOfInclusionLayer] = []
        child_hash = node_hash
        for parent in ancestors:
            layer = ProofOfInclusionLayer.from_internal_node(internal_node=parent, traversal_child_hash=child_hash)
            layers.append(layer)
            child_hash = parent.hash

        proof_of_inclusion = ProofOfInclusion(node_hash=node_hash, layers=layers)

        if len(ancestors) > 0:
            expected_root = ancestors[-1].hash
        else:
            expected_root = node_hash

        if expected_root != proof_of_inclusion.root_hash:
            raise Exception(
                f"Incorrect root, expected: {expected_root.hex()}"
                f"\n                     has: {proof_of_inclusion.root_hash.hex()}"
            )

        return proof_of_inclusion

    async def get_proof_of_inclusion_by_key(
        self,
        key: bytes,
        tree_id: bytes32,
    ) -> ProofOfInclusion:
        """Collect the information for a proof of inclusion of a key and its value in
        the Merkle tree.
        """
        async with self.db_wrapper.reader():
            node = await self.get_node_by_key(key=key, tree_id=tree_id)
            return await self.get_proof_of_inclusion_by_hash(node_hash=node.hash, tree_id=tree_id)

    async def get_first_generation(self, node_hash: bytes32, tree_id: bytes32) -> int:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT MIN(generation) AS generation FROM ancestors WHERE hash == :hash AND tree_id == :tree_id",
                {"hash": node_hash, "tree_id": tree_id},
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Hash not found in ancestor table.")

            generation = row["generation"]
            return int(generation)

    async def write_tree_to_file(
        self,
        root: Root,
        node_hash: bytes32,
        tree_id: bytes32,
        deltas_only: bool,
        writer: BinaryIO,
    ) -> None:
        if node_hash == bytes32([0] * 32):
            return

        if deltas_only:
            generation = await self.get_first_generation(node_hash, tree_id)
            # Root's generation is not the first time we see this hash, so it's not a new delta.
            if root.generation != generation:
                return
        node = await self.get_node(node_hash)
        to_write = b""
        if isinstance(node, InternalNode):
            await self.write_tree_to_file(root, node.left_hash, tree_id, deltas_only, writer)
            await self.write_tree_to_file(root, node.right_hash, tree_id, deltas_only, writer)
            to_write = bytes(SerializedNode(False, bytes(node.left_hash), bytes(node.right_hash)))
        elif isinstance(node, TerminalNode):
            to_write = bytes(SerializedNode(True, node.key, node.value))
        else:
            raise Exception(f"Node is neither InternalNode nor TerminalNode: {node}")

        writer.write(len(to_write).to_bytes(4, byteorder="big"))
        writer.write(to_write)

    async def update_subscriptions_from_wallet(self, tree_id: bytes32, new_urls: List[str]) -> None:
        async with self.db_wrapper.writer() as writer:
            cursor = await writer.execute(
                "SELECT * FROM subscriptions WHERE from_wallet == 1 AND tree_id == :tree_id",
                {
                    "tree_id": tree_id,
                },
            )
            old_urls = [row["url"] async for row in cursor]
            cursor = await writer.execute(
                "SELECT * FROM subscriptions WHERE from_wallet == 0 AND tree_id == :tree_id",
                {
                    "tree_id": tree_id,
                },
            )
            from_subscriptions_urls = {row["url"] async for row in cursor}
            additions = {url for url in new_urls if url not in old_urls}
            removals = [url for url in old_urls if url not in new_urls]
            for url in removals:
                await writer.execute(
                    "DELETE FROM subscriptions WHERE url == :url AND tree_id == :tree_id",
                    {
                        "url": url,
                        "tree_id": tree_id,
                    },
                )
            for url in additions:
                if url not in from_subscriptions_urls:
                    await writer.execute(
                        "INSERT INTO subscriptions(tree_id, url, ignore_till, num_consecutive_failures, from_wallet) "
                        "VALUES (:tree_id, :url, 0, 0, 1)",
                        {
                            "tree_id": tree_id,
                            "url": url,
                        },
                    )

    async def subscribe(self, subscription: Subscription) -> None:
        async with self.db_wrapper.writer() as writer:
            # Add a fake subscription, so we always have the tree_id, even with no URLs.
            await writer.execute(
                "INSERT INTO subscriptions(tree_id, url, ignore_till, num_consecutive_failures, from_wallet) "
                "VALUES (:tree_id, NULL, NULL, NULL, 0)",
                {
                    "tree_id": subscription.tree_id,
                },
            )
            all_subscriptions = await self.get_subscriptions()
            old_subscription = next(
                (
                    old_subscription
                    for old_subscription in all_subscriptions
                    if old_subscription.tree_id == subscription.tree_id
                ),
                None,
            )
            old_urls = set()
            if old_subscription is not None:
                old_urls = set(server_info.url for server_info in old_subscription.servers_info)
            new_servers = [server_info for server_info in subscription.servers_info if server_info.url not in old_urls]
            for server_info in new_servers:
                await writer.execute(
                    "INSERT INTO subscriptions(tree_id, url, ignore_till, num_consecutive_failures, from_wallet) "
                    "VALUES (:tree_id, :url, :ignore_till, :num_consecutive_failures, 0)",
                    {
                        "tree_id": subscription.tree_id,
                        "url": server_info.url,
                        "ignore_till": server_info.ignore_till,
                        "num_consecutive_failures": server_info.num_consecutive_failures,
                    },
                )

    async def remove_subscriptions(self, tree_id: bytes32, urls: List[str]) -> None:
        async with self.db_wrapper.writer() as writer:
            for url in urls:
                await writer.execute(
                    "DELETE FROM subscriptions WHERE tree_id == :tree_id AND url == :url",
                    {
                        "tree_id": tree_id,
                        "url": url,
                    },
                )

    async def unsubscribe(self, tree_id: bytes32) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "DELETE FROM subscriptions WHERE tree_id == :tree_id",
                {"tree_id": tree_id},
            )

    async def rollback_to_generation(self, tree_id: bytes32, target_generation: int) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "DELETE FROM ancestors WHERE tree_id == :tree_id AND generation > :target_generation",
                {"tree_id": tree_id, "target_generation": target_generation},
            )
            await writer.execute(
                "DELETE FROM root WHERE tree_id == :tree_id AND generation > :target_generation",
                {"tree_id": tree_id, "target_generation": target_generation},
            )

    async def update_server_info(self, tree_id: bytes32, server_info: ServerInfo) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "UPDATE subscriptions SET ignore_till = :ignore_till, "
                "num_consecutive_failures = :num_consecutive_failures WHERE tree_id = :tree_id AND url = :url",
                {
                    "ignore_till": server_info.ignore_till,
                    "num_consecutive_failures": server_info.num_consecutive_failures,
                    "tree_id": tree_id,
                    "url": server_info.url,
                },
            )

    async def received_incorrect_file(self, tree_id: bytes32, server_info: ServerInfo, timestamp: int) -> None:
        SEVEN_DAYS_BAN = 7 * 24 * 60 * 60
        new_server_info = replace(
            server_info,
            num_consecutive_failures=server_info.num_consecutive_failures + 1,
            ignore_till=max(server_info.ignore_till, timestamp + SEVEN_DAYS_BAN),
        )
        await self.update_server_info(tree_id, new_server_info)

    async def received_correct_file(self, tree_id: bytes32, server_info: ServerInfo) -> None:
        new_server_info = replace(
            server_info,
            num_consecutive_failures=0,
        )
        await self.update_server_info(tree_id, new_server_info)

    async def server_misses_file(self, tree_id: bytes32, server_info: ServerInfo, timestamp: int) -> None:
        BAN_TIME_BY_MISSING_COUNT = [5 * 60] * 3 + [15 * 60] * 3 + [60 * 60] * 2 + [240 * 60]
        index = min(server_info.num_consecutive_failures, len(BAN_TIME_BY_MISSING_COUNT) - 1)
        new_server_info = replace(
            server_info,
            num_consecutive_failures=server_info.num_consecutive_failures + 1,
            ignore_till=max(server_info.ignore_till, timestamp + BAN_TIME_BY_MISSING_COUNT[index]),
        )
        await self.update_server_info(tree_id, new_server_info)

    async def get_available_servers_for_store(self, tree_id: bytes32, timestamp: int) -> List[ServerInfo]:
        subscriptions = await self.get_subscriptions()
        subscription = next((subscription for subscription in subscriptions if subscription.tree_id == tree_id), None)
        if subscription is None:
            return []
        servers_info = []
        for server_info in subscription.servers_info:
            if timestamp > server_info.ignore_till:
                servers_info.append(server_info)
        return servers_info

    async def get_subscriptions(self) -> List[Subscription]:
        subscriptions: List[Subscription] = []

        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT * from subscriptions",
            )
            async for row in cursor:
                tree_id = bytes32(row["tree_id"])
                url = row["url"]
                ignore_till = row["ignore_till"]
                num_consecutive_failures = row["num_consecutive_failures"]
                subscription = next(
                    (subscription for subscription in subscriptions if subscription.tree_id == tree_id), None
                )
                if subscription is None:
                    if url is not None and num_consecutive_failures is not None and ignore_till is not None:
                        subscriptions.append(
                            Subscription(tree_id, [ServerInfo(url, num_consecutive_failures, ignore_till)])
                        )
                    else:
                        subscriptions.append(Subscription(tree_id, []))
                else:
                    if url is not None and num_consecutive_failures is not None and ignore_till is not None:
                        new_servers_info = subscription.servers_info
                        new_servers_info.append(ServerInfo(url, num_consecutive_failures, ignore_till))
                        new_subscription = replace(subscription, servers_info=new_servers_info)
                        subscriptions.remove(subscription)
                        subscriptions.append(new_subscription)

        return subscriptions

    async def get_kv_diff(
        self,
        tree_id: bytes32,
        hash_1: bytes32,
        hash_2: bytes32,
    ) -> Set[DiffData]:
        async with self.db_wrapper.reader():
            old_pairs = set(await self.get_keys_values(tree_id, hash_1))
            new_pairs = set(await self.get_keys_values(tree_id, hash_2))
            if len(old_pairs) == 0 and hash_1 != bytes32([0] * 32):
                return set()
            if len(new_pairs) == 0 and hash_2 != bytes32([0] * 32):
                return set()
            insertions = set(
                DiffData(type=OperationType.INSERT, key=node.key, value=node.value)
                for node in new_pairs
                if node not in old_pairs
            )
            deletions = set(
                DiffData(type=OperationType.DELETE, key=node.key, value=node.value)
                for node in old_pairs
                if node not in new_pairs
            )
            return set.union(insertions, deletions)
