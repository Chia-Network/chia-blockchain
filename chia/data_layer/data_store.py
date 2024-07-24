from __future__ import annotations

import contextlib
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
    InsertResult,
    InternalNode,
    KeysPaginationData,
    KeysValuesCompressed,
    KeysValuesPaginationData,
    KVDiffPaginationData,
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
    Unspecified,
    get_hashes_for_page,
    internal_hash,
    key_hash,
    leaf_hash,
    row_to_node,
    unspecified,
)
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER, DBWrapper2

log = logging.getLogger(__name__)


# TODO: review exceptions for values that shouldn't be displayed
# TODO: pick exception types other than Exception


@dataclass
class DataStore:
    """A key/value store with the pairs being terminal nodes in a CLVM object tree."""

    db_wrapper: DBWrapper2

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(
        cls, database: Union[str, Path], uri: bool = False, sql_log_path: Optional[Path] = None
    ) -> AsyncIterator[DataStore]:
        async with DBWrapper2.managed(
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
            log_path=sql_log_path,
        ) as db_wrapper:
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
                    CREATE TABLE IF NOT EXISTS schema(
                        version_id TEXT PRIMARY KEY,
                        applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                await writer.execute(
                    """
                    CREATE INDEX IF NOT EXISTS node_hash ON root(node_hash)
                    """
                )
                await writer.execute(
                    """
                    CREATE INDEX IF NOT EXISTS node_key_index ON node(key)
                    """
                )

            yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self.db_wrapper.writer():
            yield

    async def migrate_db(self) -> None:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT * FROM schema")
            row = await cursor.fetchone()
            if row is not None:
                version = row["version_id"]
                if version != "v1.0":
                    raise Exception("Unknown version")
                log.info(f"Found DB schema version {version}. No migration needed.")
                return

        version = "v1.0"
        log.info(f"Initiating migration to version {version}")
        async with self.db_wrapper.writer(foreign_key_enforcement_enabled=False) as writer:
            await writer.execute(
                f"""
                CREATE TABLE IF NOT EXISTS new_root(
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
            await writer.execute("INSERT INTO new_root SELECT * FROM root")
            await writer.execute("DROP TABLE root")
            await writer.execute("ALTER TABLE new_root RENAME TO root")
            await writer.execute("INSERT INTO schema (version_id) VALUES (?)", (version,))
        log.info(f"Finished migrating DB to version {version}")

    async def _insert_root(
        self,
        store_id: bytes32,
        node_hash: Optional[bytes32],
        status: Status,
        generation: Optional[int] = None,
    ) -> Root:
        # This should be replaced by an SQLite schema level check.
        # https://github.com/Chia-Network/chia-blockchain/pull/9284
        store_id = bytes32(store_id)

        async with self.db_wrapper.writer() as writer:
            if generation is None:
                try:
                    existing_generation = await self.get_tree_generation(store_id=store_id)
                except Exception as e:
                    if not str(e).startswith("No generations found for store ID:"):
                        raise
                    generation = 0
                else:
                    generation = existing_generation + 1

            new_root = Root(
                store_id=store_id,
                node_hash=node_hash,
                generation=generation,
                status=status,
            )

            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                new_root.to_row(),
            )

            # `node_hash` is now a root, so it has no ancestor.
            # Don't change the ancestor table unless the root is committed.
            if node_hash is not None and status == Status.COMMITTED:
                values = {
                    "hash": node_hash,
                    "tree_id": store_id,
                    "generation": generation,
                }
                await writer.execute(
                    """
                    INSERT INTO ancestors(hash, ancestor, tree_id, generation)
                    VALUES (:hash, NULL, :tree_id, :generation)
                    """,
                    values,
                )

            return new_root

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
            try:
                await writer.execute(
                    """
                    INSERT INTO node(hash, node_type, left, right, key, value)
                    VALUES(:hash, :node_type, :left, :right, :key, :value)
                    """,
                    values,
                )
            except aiosqlite.IntegrityError as e:
                if not e.args[0].startswith("UNIQUE constraint"):
                    # UNIQUE constraint failed: node.hash
                    raise

                async with writer.execute(
                    "SELECT * FROM node WHERE hash == :hash LIMIT 1",
                    {"hash": node_hash},
                ) as cursor:
                    result = await cursor.fetchone()

                if result is None:
                    # some ideas for causes:
                    #   an sqlite bug
                    #   bad queries in this function
                    #   unexpected db constraints
                    raise Exception("Unable to find conflicting row") from e  # pragma: no cover

                result_dict = dict(result)
                if result_dict != values:
                    raise Exception(
                        f"Requested insertion of node with matching hash but other values differ: {node_hash}"
                    ) from None

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
        store_id: bytes32,
        generation: int,
    ) -> None:
        node_hash = internal_hash(left_hash=left_hash, right_hash=right_hash)

        async with self.db_wrapper.writer() as writer:
            for hash in (left_hash, right_hash):
                values = {
                    "hash": hash,
                    "ancestor": node_hash,
                    "tree_id": store_id,
                    "generation": generation,
                }
                try:
                    await writer.execute(
                        """
                        INSERT INTO ancestors(hash, ancestor, tree_id, generation)
                        VALUES (:hash, :ancestor, :tree_id, :generation)
                        """,
                        values,
                    )
                except aiosqlite.IntegrityError as e:
                    if not e.args[0].startswith("UNIQUE constraint"):
                        # UNIQUE constraint failed: ancestors.hash, ancestors.tree_id, ancestors.generation
                        raise

                    async with writer.execute(
                        """
                        SELECT *
                        FROM ancestors
                        WHERE hash == :hash AND generation == :generation AND tree_id == :tree_id
                        LIMIT 1
                        """,
                        {"hash": hash, "generation": generation, "tree_id": store_id},
                    ) as cursor:
                        result = await cursor.fetchone()

                    if result is None:
                        # some ideas for causes:
                        #   an sqlite bug
                        #   bad queries in this function
                        #   unexpected db constraints
                        raise Exception("Unable to find conflicting row") from e  # pragma: no cover

                    result_dict = dict(result)
                    if result_dict != values:
                        raise Exception(
                            "Requested insertion of ancestor, where ancestor differ, but other values are identical: "
                            f"{hash} {generation} {store_id}"
                        ) from None

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

    async def get_pending_root(self, store_id: bytes32) -> Optional[Root]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                """
                SELECT * FROM root WHERE tree_id == :tree_id
                AND status IN (:pending_status, :pending_batch_status) LIMIT 2
                """,
                {
                    "tree_id": store_id,
                    "pending_status": Status.PENDING.value,
                    "pending_batch_status": Status.PENDING_BATCH.value,
                },
            )

            row = await cursor.fetchone()

            if row is None:
                return None

            maybe_extra_result = await cursor.fetchone()
            if maybe_extra_result is not None:
                raise Exception(f"multiple pending roots found for id: {store_id.hex()}")

        return Root.from_row(row=row)

    async def clear_pending_roots(self, store_id: bytes32) -> Optional[Root]:
        async with self.db_wrapper.writer() as writer:
            pending_root = await self.get_pending_root(store_id=store_id)

            if pending_root is not None:
                await writer.execute(
                    "DELETE FROM root WHERE tree_id == :tree_id AND status IN (:pending_status, :pending_batch_status)",
                    {
                        "tree_id": store_id,
                        "pending_status": Status.PENDING.value,
                        "pending_batch_status": Status.PENDING_BATCH.value,
                    },
                )

        return pending_root

    async def shift_root_generations(self, store_id: bytes32, shift_size: int) -> None:
        async with self.db_wrapper.writer():
            root = await self.get_tree_root(store_id=store_id)
            for _ in range(shift_size):
                await self._insert_root(store_id=store_id, node_hash=root.node_hash, status=Status.COMMITTED)

    async def change_root_status(self, root: Root, status: Status = Status.PENDING) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "UPDATE root SET status = ? WHERE tree_id=? and generation = ?",
                (
                    status.value,
                    root.store_id,
                    root.generation,
                ),
            )
            # `node_hash` is now a root, so it has no ancestor.
            # Don't change the ancestor table unless the root is committed.
            if root.node_hash is not None and status == Status.COMMITTED:
                values = {
                    "hash": root.node_hash,
                    "tree_id": root.store_id,
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
                roots_by_tree[root.store_id].append(root)

            bad_trees = []
            for store_id, roots in roots_by_tree.items():
                current_generation = roots[-1].generation
                expected_generations = list(range(current_generation + 1))
                actual_generations = [root.generation for root in roots]
                if actual_generations != expected_generations:
                    bad_trees.append(store_id)

            if len(bad_trees) > 0:
                raise TreeGenerationIncrementingError(store_ids=bad_trees)

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
                else:
                    raise Exception(f"Internal error, unknown node type: {node!r}")

                if node.hash != expected_hash:
                    bad_node_hashes.append(node.hash)

        if len(bad_node_hashes) > 0:
            raise NodeHashError(node_hashes=bad_node_hashes)

    _checks: Tuple[Callable[[DataStore], Awaitable[None]], ...] = (
        _check_roots_are_incrementing,
        _check_hashes,
    )

    async def create_tree(self, store_id: bytes32, status: Status = Status.PENDING) -> bool:
        await self._insert_root(store_id=store_id, node_hash=None, status=status)

        return True

    async def table_is_empty(self, store_id: bytes32) -> bool:
        tree_root = await self.get_tree_root(store_id=store_id)

        return tree_root.node_hash is None

    async def get_store_ids(self) -> Set[bytes32]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT DISTINCT tree_id FROM root")

            store_ids = {bytes32(row["tree_id"]) async for row in cursor}

        return store_ids

    async def get_tree_generation(self, store_id: bytes32) -> int:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT MAX(generation) FROM root WHERE tree_id == :tree_id AND status == :status",
                {"tree_id": store_id, "status": Status.COMMITTED.value},
            )
            row = await cursor.fetchone()

        if row is not None:
            generation: Optional[int] = row["MAX(generation)"]

            if generation is not None:
                return generation

        raise Exception(f"No generations found for store ID: {store_id.hex()}")

    async def get_tree_root(self, store_id: bytes32, generation: Optional[int] = None) -> Root:
        async with self.db_wrapper.reader() as reader:
            if generation is None:
                generation = await self.get_tree_generation(store_id=store_id)
            cursor = await reader.execute(
                """
                SELECT *
                FROM root
                WHERE tree_id == :tree_id AND generation == :generation AND status == :status
                LIMIT 1
                """,
                {"tree_id": store_id, "generation": generation, "status": Status.COMMITTED.value},
            )
            row = await cursor.fetchone()

            if row is None:
                raise Exception(f"unable to find root for id, generation: {store_id.hex()}, {generation}")

        return Root.from_row(row=row)

    async def get_all_pending_batches_roots(self) -> List[Root]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                """
                SELECT * FROM root WHERE status == :status
                """,
                {"status": Status.PENDING_BATCH.value},
            )
            roots = [Root.from_row(row=row) async for row in cursor]
            store_ids = [root.store_id for root in roots]
            if len(set(store_ids)) != len(store_ids):
                raise Exception("Internal error: multiple pending batches for a store")
            return roots

    async def store_id_exists(self, store_id: bytes32) -> bool:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT 1 FROM root WHERE tree_id == :tree_id AND status == :status LIMIT 1",
                {"tree_id": store_id, "status": Status.COMMITTED.value},
            )
            row = await cursor.fetchone()

        if row is None:
            return False
        return True

    async def get_roots_between(self, store_id: bytes32, generation_begin: int, generation_end: int) -> List[Root]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT * FROM root WHERE tree_id == :tree_id "
                "AND generation >= :generation_begin AND generation < :generation_end ORDER BY generation ASC",
                {"tree_id": store_id, "generation_begin": generation_begin, "generation_end": generation_end},
            )
            roots = [Root.from_row(row=row) async for row in cursor]

        return roots

    async def get_last_tree_root_by_hash(
        self, store_id: bytes32, hash: Optional[bytes32], max_generation: Optional[int] = None
    ) -> Optional[Root]:
        async with self.db_wrapper.reader() as reader:
            max_generation_str = "AND generation < :max_generation " if max_generation is not None else ""
            node_hash_str = "AND node_hash == :node_hash " if hash is not None else "AND node_hash is NULL "
            cursor = await reader.execute(
                "SELECT * FROM root WHERE tree_id == :tree_id "
                f"{max_generation_str}"
                f"{node_hash_str}"
                "ORDER BY generation DESC LIMIT 1",
                {"tree_id": store_id, "node_hash": hash, "max_generation": max_generation},
            )
            row = await cursor.fetchone()

        if row is None:
            return None
        return Root.from_row(row=row)

    async def get_ancestors(
        self,
        node_hash: bytes32,
        store_id: bytes32,
        root_hash: Optional[bytes32] = None,
    ) -> List[InternalNode]:
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(store_id=store_id)
                root_hash = root.node_hash
            if root_hash is None:
                raise Exception(f"Root hash is unspecified for store ID: {store_id.hex()}")
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
        self,
        node_hash: bytes32,
        store_id: bytes32,
        generation: Optional[int] = None,
        root_hash: Optional[bytes32] = None,
    ) -> List[InternalNode]:
        async with self.db_wrapper.reader():
            nodes = []
            if root_hash is None:
                root = await self.get_tree_root(store_id=store_id, generation=generation)
                root_hash = root.node_hash

            if root_hash is None:
                return []

            while True:
                internal_node = await self._get_one_ancestor(node_hash, store_id, generation)
                if internal_node is None:
                    break
                nodes.append(internal_node)
                node_hash = internal_node.hash

            if len(nodes) > 0:
                if root_hash != nodes[-1].hash:
                    raise RuntimeError("Ancestors list didn't produce the root as top result.")

            return nodes

    async def get_internal_nodes(self, store_id: bytes32, root_hash: Optional[bytes32] = None) -> List[InternalNode]:
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(store_id=store_id)
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
                {"root_hash": root_hash, "node_type": NodeType.INTERNAL},
            )

            internal_nodes: List[InternalNode] = []
            async for row in cursor:
                node = row_to_node(row=row)
                if not isinstance(node, InternalNode):
                    raise Exception(f"Unexpected internal node found: {node.hash.hex()}")
                internal_nodes.append(node)

        return internal_nodes

    async def get_keys_values_cursor(
        self,
        reader: aiosqlite.Connection,
        root_hash: Optional[bytes32],
        only_keys: bool = False,
    ) -> aiosqlite.Cursor:
        select_clause = "SELECT hash, key" if only_keys else "SELECT *"
        maybe_value = "" if only_keys else "value, "
        select_node_clause = "node.hash, node.node_type, node.left, node.right, node.key" if only_keys else "node.*"
        return await reader.execute(
            f"""
            WITH RECURSIVE
                tree_from_root_hash(hash, node_type, left, right, key, {maybe_value}depth, rights) AS (
                    SELECT {select_node_clause}, 0 AS depth, 0 AS rights FROM node WHERE node.hash == :root_hash
                    UNION ALL
                    SELECT
                        {select_node_clause},
                        tree_from_root_hash.depth + 1 AS depth,
                        CASE
                            WHEN node.hash == tree_from_root_hash.right
                            THEN tree_from_root_hash.rights + (1 << (62 - tree_from_root_hash.depth))
                            ELSE tree_from_root_hash.rights
                            END AS rights
                        FROM node, tree_from_root_hash
                    WHERE node.hash == tree_from_root_hash.left OR node.hash == tree_from_root_hash.right
                )
            {select_clause} FROM tree_from_root_hash
            WHERE node_type == :node_type
            ORDER BY depth ASC, rights ASC
            """,
            {"root_hash": root_hash, "node_type": NodeType.TERMINAL},
        )

    async def get_keys_values(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> List[TerminalNode]:
        async with self.db_wrapper.reader() as reader:
            resolved_root_hash: Optional[bytes32]
            if root_hash is unspecified:
                root = await self.get_tree_root(store_id=store_id)
                resolved_root_hash = root.node_hash
            else:
                resolved_root_hash = root_hash

            cursor = await self.get_keys_values_cursor(reader, resolved_root_hash)
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

    async def get_keys_values_compressed(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> KeysValuesCompressed:
        async with self.db_wrapper.reader() as reader:
            resolved_root_hash: Optional[bytes32]
            if root_hash is unspecified:
                root = await self.get_tree_root(store_id=store_id)
                resolved_root_hash = root.node_hash
            else:
                resolved_root_hash = root_hash

            cursor = await self.get_keys_values_cursor(reader, resolved_root_hash)
            keys_values_hashed: Dict[bytes32, bytes32] = {}
            key_hash_to_length: Dict[bytes32, int] = {}
            leaf_hash_to_length: Dict[bytes32, int] = {}
            async for row in cursor:
                if row["depth"] > 62:
                    raise Exception("Tree depth exceeded 62, unable to guarantee left-to-right node order.")
                node = row_to_node(row=row)
                if not isinstance(node, TerminalNode):
                    raise Exception(f"Unexpected internal node found: {node.hash.hex()}")
                keys_values_hashed[key_hash(node.key)] = leaf_hash(node.key, node.value)
                key_hash_to_length[key_hash(node.key)] = len(node.key)
                leaf_hash_to_length[leaf_hash(node.key, node.value)] = len(node.key) + len(node.value)

            return KeysValuesCompressed(keys_values_hashed, key_hash_to_length, leaf_hash_to_length, resolved_root_hash)

    async def get_leaf_hashes_by_hashed_key(
        self, store_id: bytes32, root_hash: Optional[bytes32] = None
    ) -> Dict[bytes32, bytes32]:
        result: Dict[bytes32, bytes32] = {}
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(store_id=store_id)
                root_hash = root.node_hash

            cursor = await self.get_keys_values_cursor(reader, root_hash, True)
            async for row in cursor:
                result[key_hash(row["key"])] = bytes32(row["hash"])

        return result

    async def get_keys_paginated(
        self,
        store_id: bytes32,
        page: int,
        max_page_size: int,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> KeysPaginationData:
        keys_values_compressed = await self.get_keys_values_compressed(store_id, root_hash)
        pagination_data = get_hashes_for_page(page, keys_values_compressed.key_hash_to_length, max_page_size)

        keys: List[bytes] = []
        for hash in pagination_data.hashes:
            leaf_hash = keys_values_compressed.keys_values_hashed[hash]
            node = await self.get_node(leaf_hash)
            assert isinstance(node, TerminalNode)
            keys.append(node.key)

        return KeysPaginationData(
            pagination_data.total_pages,
            pagination_data.total_bytes,
            keys,
            keys_values_compressed.root_hash,
        )

    async def get_keys_values_paginated(
        self,
        store_id: bytes32,
        page: int,
        max_page_size: int,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> KeysValuesPaginationData:
        keys_values_compressed = await self.get_keys_values_compressed(store_id, root_hash)
        pagination_data = get_hashes_for_page(page, keys_values_compressed.leaf_hash_to_length, max_page_size)

        keys_values: List[TerminalNode] = []
        for hash in pagination_data.hashes:
            node = await self.get_node(hash)
            assert isinstance(node, TerminalNode)
            keys_values.append(node)

        return KeysValuesPaginationData(
            pagination_data.total_pages,
            pagination_data.total_bytes,
            keys_values,
            keys_values_compressed.root_hash,
        )

    async def get_kv_diff_paginated(
        self,
        store_id: bytes32,
        page: int,
        max_page_size: int,
        # NOTE: empty is expressed as zeros
        hash1: bytes32,
        hash2: bytes32,
    ) -> KVDiffPaginationData:
        old_pairs = await self.get_keys_values_compressed(store_id, hash1)
        if len(old_pairs.keys_values_hashed) == 0 and hash1 != bytes32([0] * 32):
            raise Exception(f"Unable to diff: Can't find keys and values for {hash1}")

        new_pairs = await self.get_keys_values_compressed(store_id, hash2)
        if len(new_pairs.keys_values_hashed) == 0 and hash2 != bytes32([0] * 32):
            raise Exception(f"Unable to diff: Can't find keys and values for {hash2}")

        old_pairs_leaf_hashes = {v for v in old_pairs.keys_values_hashed.values()}
        new_pairs_leaf_hashes = {v for v in new_pairs.keys_values_hashed.values()}
        insertions = {k for k in new_pairs_leaf_hashes if k not in old_pairs_leaf_hashes}
        deletions = {k for k in old_pairs_leaf_hashes if k not in new_pairs_leaf_hashes}
        lengths = {}
        for hash in insertions:
            lengths[hash] = new_pairs.leaf_hash_to_length[hash]
        for hash in deletions:
            lengths[hash] = old_pairs.leaf_hash_to_length[hash]

        pagination_data = get_hashes_for_page(page, lengths, max_page_size)
        kv_diff: List[DiffData] = []

        for hash in pagination_data.hashes:
            node = await self.get_node(hash)
            assert isinstance(node, TerminalNode)
            if hash in insertions:
                kv_diff.append(DiffData(OperationType.INSERT, node.key, node.value))
            else:
                kv_diff.append(DiffData(OperationType.DELETE, node.key, node.value))

        return KVDiffPaginationData(
            pagination_data.total_pages,
            pagination_data.total_bytes,
            kv_diff,
        )

    async def get_node_type(self, node_hash: bytes32) -> NodeType:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT node_type FROM node WHERE hash == :hash LIMIT 1",
                {"hash": node_hash},
            )
            raw_node_type = await cursor.fetchone()

        if raw_node_type is None:
            raise Exception(f"No node found for specified hash: {node_hash.hex()}")

        return NodeType(raw_node_type["node_type"])

    async def get_terminal_node_for_seed(
        self, store_id: bytes32, seed: bytes32, root_hash: Optional[bytes32] = None
    ) -> Optional[bytes32]:
        path = "".join(reversed("".join(f"{b:08b}" for b in seed)))
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(store_id)
                root_hash = root.node_hash
            if root_hash is None:
                return None

            async with reader.execute(
                """
                WITH RECURSIVE
                    random_leaf(hash, node_type, left, right, depth, side) AS (
                        SELECT
                            node.hash AS hash,
                            node.node_type AS node_type,
                            node.left AS left,
                            node.right AS right,
                            1 AS depth,
                            SUBSTR(:path, 1, 1) as side
                        FROM node
                        WHERE node.hash == :root_hash
                        UNION ALL
                        SELECT
                            node.hash AS hash,
                            node.node_type AS node_type,
                            node.left AS left,
                            node.right AS right,
                            random_leaf.depth + 1 AS depth,
                            SUBSTR(:path, random_leaf.depth + 1, 1) as side
                        FROM node, random_leaf
                        WHERE (
                            (random_leaf.side == "0" AND node.hash == random_leaf.left)
                            OR (random_leaf.side != "0" AND node.hash == random_leaf.right)
                        )
                    )
                SELECT hash AS hash FROM random_leaf
                WHERE node_type == :node_type
                LIMIT 1
                """,
                {"root_hash": root_hash, "node_type": NodeType.TERMINAL, "path": path},
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    # No cover since this is an error state that should be unreachable given the code
                    # above has already verified that there is a non-empty tree.
                    raise Exception("No terminal node found for seed")  # pragma: no cover
                return bytes32(row["hash"])

    def get_side_for_seed(self, seed: bytes32) -> Side:
        side_seed = bytes(seed)[0]
        return Side.LEFT if side_seed < 128 else Side.RIGHT

    async def autoinsert(
        self,
        key: bytes,
        value: bytes,
        store_id: bytes32,
        use_optimized: bool = True,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
    ) -> InsertResult:
        async with self.db_wrapper.writer():
            if root is None:
                root = await self.get_tree_root(store_id=store_id)

            was_empty = root.node_hash is None

            if was_empty:
                reference_node_hash = None
                side = None
            else:
                seed = leaf_hash(key=key, value=value)
                reference_node_hash = await self.get_terminal_node_for_seed(store_id, seed, root_hash=root.node_hash)
                side = self.get_side_for_seed(seed)

            return await self.insert(
                key=key,
                value=value,
                store_id=store_id,
                reference_node_hash=reference_node_hash,
                side=side,
                use_optimized=use_optimized,
                status=status,
                root=root,
            )

    async def get_keys_values_dict(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> Dict[bytes, bytes]:
        pairs = await self.get_keys_values(store_id=store_id, root_hash=root_hash)
        return {node.key: node.value for node in pairs}

    async def get_keys(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> List[bytes]:
        async with self.db_wrapper.reader() as reader:
            if root_hash is unspecified:
                root = await self.get_tree_root(store_id=store_id)
                resolved_root_hash = root.node_hash
            else:
                resolved_root_hash = root_hash
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
                {"root_hash": resolved_root_hash, "node_type": NodeType.TERMINAL},
            )

            keys: List[bytes] = [row["key"] async for row in cursor]

        return keys

    async def get_ancestors_common(
        self,
        node_hash: bytes32,
        store_id: bytes32,
        root_hash: Optional[bytes32],
        generation: Optional[int] = None,
        use_optimized: bool = True,
    ) -> List[InternalNode]:
        if use_optimized:
            ancestors: List[InternalNode] = await self.get_ancestors_optimized(
                node_hash=node_hash,
                store_id=store_id,
                generation=generation,
                root_hash=root_hash,
            )
        else:
            ancestors = await self.get_ancestors_optimized(
                node_hash=node_hash,
                store_id=store_id,
                generation=generation,
                root_hash=root_hash,
            )
            ancestors_2: List[InternalNode] = await self.get_ancestors(
                node_hash=node_hash, store_id=store_id, root_hash=root_hash
            )
            if ancestors != ancestors_2:
                raise RuntimeError("Ancestors optimized didn't produce the expected result.")

        if len(ancestors) >= 62:
            raise RuntimeError("Tree exceeds max height of 62.")
        return ancestors

    async def update_ancestor_hashes_on_insert(
        self,
        store_id: bytes32,
        left: bytes32,
        right: bytes32,
        traversal_node_hash: bytes32,
        ancestors: List[InternalNode],
        status: Status,
        root: Root,
    ) -> Root:
        # update ancestors after inserting root, to keep table constraints.
        insert_ancestors_cache: List[Tuple[bytes32, bytes32, bytes32]] = []
        new_generation = root.generation + 1
        # create first new internal node
        new_hash = await self._insert_internal_node(left_hash=left, right_hash=right)
        insert_ancestors_cache.append((left, right, store_id))

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
            insert_ancestors_cache.append((left, right, store_id))

        new_root = await self._insert_root(
            store_id=store_id,
            node_hash=new_hash,
            status=status,
            generation=new_generation,
        )

        if status == Status.COMMITTED:
            for left_hash, right_hash, store_id in insert_ancestors_cache:
                await self._insert_ancestor_table(left_hash, right_hash, store_id, new_generation)

        return new_root

    async def insert(
        self,
        key: bytes,
        value: bytes,
        store_id: bytes32,
        reference_node_hash: Optional[bytes32],
        side: Optional[Side],
        use_optimized: bool = True,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
    ) -> InsertResult:
        async with self.db_wrapper.writer():
            if root is None:
                root = await self.get_tree_root(store_id=store_id)

            try:
                await self.get_node_by_key(key=key, store_id=store_id)
                raise Exception(f"Key already present: {key.hex()}")
            except KeyNotFoundError:
                pass

            was_empty = root.node_hash is None
            if reference_node_hash is None:
                if not was_empty:
                    raise Exception(f"Reference node hash must be specified for non-empty tree: {store_id.hex()}")
            else:
                reference_node_type = await self.get_node_type(node_hash=reference_node_hash)
                if reference_node_type == NodeType.INTERNAL:
                    raise Exception("can not insert a new key/value on an internal node")

            # create new terminal node
            new_terminal_node_hash = await self._insert_terminal_node(key=key, value=value)

            if was_empty:
                if side is not None:
                    raise Exception("Tree was empty so side must be unspecified, got: {side!r}")

                new_root = await self._insert_root(
                    store_id=store_id,
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

                if side == Side.LEFT:
                    left = new_terminal_node_hash
                    right = reference_node_hash
                elif side == Side.RIGHT:
                    left = reference_node_hash
                    right = new_terminal_node_hash
                else:
                    raise Exception(f"Internal error, unknown side: {side!r}")

                ancestors = await self.get_ancestors_common(
                    node_hash=reference_node_hash,
                    store_id=store_id,
                    root_hash=root.node_hash,
                    generation=root.generation,
                    use_optimized=use_optimized,
                )
                new_root = await self.update_ancestor_hashes_on_insert(
                    store_id=store_id,
                    left=left,
                    right=right,
                    traversal_node_hash=reference_node_hash,
                    ancestors=ancestors,
                    status=status,
                    root=root,
                )

            return InsertResult(node_hash=new_terminal_node_hash, root=new_root)

    async def delete(
        self,
        key: bytes,
        store_id: bytes32,
        use_optimized: bool = True,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
    ) -> Optional[Root]:
        root_hash = None if root is None else root.node_hash
        async with self.db_wrapper.writer():
            try:
                node = await self.get_node_by_key(key=key, store_id=store_id)
                node_hash = node.hash
                assert isinstance(node, TerminalNode)
            except KeyNotFoundError:
                log.debug(f"Request to delete an unknown key ignored: {key.hex()}")
                return root

            ancestors: List[InternalNode] = await self.get_ancestors_common(
                node_hash=node_hash,
                store_id=store_id,
                root_hash=root_hash,
                use_optimized=use_optimized,
            )

            if len(ancestors) == 0:
                # the only node is being deleted
                return await self._insert_root(
                    store_id=store_id,
                    node_hash=None,
                    status=status,
                )

            parent = ancestors[0]
            other_hash = parent.other_child_hash(hash=node_hash)

            if len(ancestors) == 1:
                # the parent is the root so the other side will become the new root
                return await self._insert_root(
                    store_id=store_id,
                    node_hash=other_hash,
                    status=status,
                )

            old_child_hash = parent.hash
            new_child_hash = other_hash
            if root is None:
                new_generation = await self.get_tree_generation(store_id) + 1
            else:
                new_generation = root.generation + 1
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
                insert_ancestors_cache.append((left_hash, right_hash, store_id))
                old_child_hash = ancestor.hash

            new_root = await self._insert_root(
                store_id=store_id,
                node_hash=new_child_hash,
                status=status,
                generation=new_generation,
            )
            if status == Status.COMMITTED:
                for left_hash, right_hash, store_id in insert_ancestors_cache:
                    await self._insert_ancestor_table(left_hash, right_hash, store_id, new_generation)

        return new_root

    async def upsert(
        self,
        key: bytes,
        new_value: bytes,
        store_id: bytes32,
        use_optimized: bool = True,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
    ) -> InsertResult:
        async with self.db_wrapper.writer():
            if root is None:
                root = await self.get_tree_root(store_id=store_id)

            try:
                old_node = await self.get_node_by_key(key=key, store_id=store_id)
            except KeyNotFoundError:
                log.debug(f"Key not found: {key.hex()}. Doing an autoinsert instead")
                return await self.autoinsert(
                    key=key,
                    value=new_value,
                    store_id=store_id,
                    use_optimized=use_optimized,
                    status=status,
                    root=root,
                )
            if old_node.value == new_value:
                log.debug(f"New value matches old value in upsert operation: {key.hex()}. Ignoring upsert")
                return InsertResult(leaf_hash(key, new_value), root)

            # create new terminal node
            new_terminal_node_hash = await self._insert_terminal_node(key=key, value=new_value)

            ancestors = await self.get_ancestors_common(
                node_hash=old_node.hash,
                store_id=store_id,
                root_hash=root.node_hash,
                generation=root.generation,
                use_optimized=use_optimized,
            )

            # Store contains only the old root, replace it with a new root having the terminal node.
            if len(ancestors) == 0:
                new_root = await self._insert_root(
                    store_id=store_id,
                    node_hash=new_terminal_node_hash,
                    status=status,
                )
            else:
                parent = ancestors[0]
                if parent.left_hash == old_node.hash:
                    left = new_terminal_node_hash
                    right = parent.right_hash
                elif parent.right_hash == old_node.hash:
                    left = parent.left_hash
                    right = new_terminal_node_hash
                else:
                    raise Exception("Internal error.")

                new_root = await self.update_ancestor_hashes_on_insert(
                    store_id=store_id,
                    left=left,
                    right=right,
                    traversal_node_hash=parent.hash,
                    ancestors=ancestors[1:],
                    status=status,
                    root=root,
                )

            return InsertResult(node_hash=new_terminal_node_hash, root=new_root)

    async def clean_node_table(self, writer: Optional[aiosqlite.Connection] = None) -> None:
        query = """
            WITH RECURSIVE pending_nodes AS (
                SELECT node_hash AS hash FROM root
                WHERE status IN (:pending_status, :pending_batch_status)
                UNION ALL
                SELECT n.left FROM node n
                INNER JOIN pending_nodes pn ON n.hash = pn.hash
                WHERE n.left IS NOT NULL
                UNION ALL
                SELECT n.right FROM node n
                INNER JOIN pending_nodes pn ON n.hash = pn.hash
                WHERE n.right IS NOT NULL
            )
            DELETE FROM node
            WHERE hash IN (
                SELECT n.hash FROM node n
                LEFT JOIN ancestors a ON n.hash = a.hash
                LEFT JOIN pending_nodes pn ON n.hash = pn.hash
                WHERE a.hash IS NULL AND pn.hash IS NULL
            )
        """
        params = {"pending_status": Status.PENDING.value, "pending_batch_status": Status.PENDING_BATCH.value}
        if writer is None:
            async with self.db_wrapper.writer(foreign_key_enforcement_enabled=False) as writer:
                await writer.execute(query, params)
        else:
            await writer.execute(query, params)

    async def get_nodes(self, node_hashes: List[bytes32]) -> List[Node]:
        query_parameter_place_holders = ",".join("?" for _ in node_hashes)
        async with self.db_wrapper.reader() as reader:
            # TODO: handle SQLITE_MAX_VARIABLE_NUMBER
            cursor = await reader.execute(
                f"SELECT * FROM node WHERE hash IN ({query_parameter_place_holders})",
                [*node_hashes],
            )
            rows = await cursor.fetchall()

        hash_to_node = {row["hash"]: row_to_node(row=row) for row in rows}

        missing_hashes = [node_hash.hex() for node_hash in node_hashes if node_hash not in hash_to_node]
        if missing_hashes:
            raise Exception(f"Nodes not found for hashes: {', '.join(missing_hashes)}")

        return [hash_to_node[node_hash] for node_hash in node_hashes]

    async def get_leaf_at_minimum_height(
        self, root_hash: bytes32, hash_to_parent: Dict[bytes32, InternalNode]
    ) -> TerminalNode:
        queue: List[bytes32] = [root_hash]
        batch_size = min(500, SQLITE_MAX_VARIABLE_NUMBER - 10)

        while True:
            assert len(queue) > 0
            nodes = await self.get_nodes(queue[:batch_size])
            queue = queue[batch_size:]

            for node in nodes:
                if isinstance(node, TerminalNode):
                    return node
                hash_to_parent[node.left_hash] = node
                hash_to_parent[node.right_hash] = node
                queue.append(node.left_hash)
                queue.append(node.right_hash)

    async def batch_upsert(
        self,
        hash: bytes32,
        to_update_hashes: Set[bytes32],
        pending_upsert_new_hashes: Dict[bytes32, bytes32],
    ) -> bytes32:
        if hash not in to_update_hashes:
            return hash
        node = await self.get_node(hash)
        if isinstance(node, TerminalNode):
            return pending_upsert_new_hashes[hash]
        new_left_hash = await self.batch_upsert(node.left_hash, to_update_hashes, pending_upsert_new_hashes)
        new_right_hash = await self.batch_upsert(node.right_hash, to_update_hashes, pending_upsert_new_hashes)
        return await self._insert_internal_node(new_left_hash, new_right_hash)

    async def insert_batch(
        self,
        store_id: bytes32,
        changelist: List[Dict[str, Any]],
        status: Status = Status.PENDING,
        enable_batch_autoinsert: bool = True,
    ) -> Optional[bytes32]:
        async with self.transaction():
            old_root = await self.get_tree_root(store_id)
            pending_root = await self.get_pending_root(store_id=store_id)
            if pending_root is None:
                latest_local_root: Optional[Root] = old_root
            else:
                if pending_root.status == Status.PENDING_BATCH:
                    # We have an unfinished batch, continue the current batch on top of it.
                    if pending_root.generation != old_root.generation + 1:
                        raise Exception("Internal error")
                    await self.change_root_status(pending_root, Status.COMMITTED)
                    await self.build_ancestor_table_for_latest_root(store_id=store_id)
                    latest_local_root = pending_root
                else:
                    raise Exception("Internal error")

            assert latest_local_root is not None

            key_hash_frequency: Dict[bytes32, int] = {}
            first_action: Dict[bytes32, str] = {}
            last_action: Dict[bytes32, str] = {}

            for change in changelist:
                key = change["key"]
                hash = key_hash(key)
                key_hash_frequency[hash] = key_hash_frequency.get(hash, 0) + 1
                if hash not in first_action:
                    first_action[hash] = change["action"]
                last_action[hash] = change["action"]

            pending_autoinsert_hashes: List[bytes32] = []
            pending_upsert_new_hashes: Dict[bytes32, bytes32] = {}
            leaf_hashes = await self.get_leaf_hashes_by_hashed_key(store_id)

            for change in changelist:
                if change["action"] == "insert":
                    key = change["key"]
                    value = change["value"]
                    reference_node_hash = change.get("reference_node_hash", None)
                    side = change.get("side", None)
                    if reference_node_hash is None and side is None:
                        hash = key_hash(key)
                        # The key is not referenced in any other operation but this autoinsert, hence the order
                        # of performing these should not matter. We perform all these autoinserts as a batch
                        # at the end, to speed up the tree processing operations.
                        # Additionally, if the first action is a delete, we can still perform the autoinsert at the
                        # end, since the order will be preserved.
                        if enable_batch_autoinsert:
                            if key_hash_frequency[hash] == 1 or (
                                key_hash_frequency[hash] == 2 and first_action[hash] == "delete"
                            ):
                                old_node = await self.maybe_get_node_from_key_hash(leaf_hashes, hash)
                                terminal_node_hash = await self._insert_terminal_node(key, value)

                                if old_node is None:
                                    pending_autoinsert_hashes.append(terminal_node_hash)
                                else:
                                    if key_hash_frequency[hash] == 1:
                                        raise Exception(f"Key already present: {key.hex()}")
                                    else:
                                        pending_upsert_new_hashes[old_node.hash] = terminal_node_hash
                                continue
                        insert_result = await self.autoinsert(
                            key, value, store_id, True, Status.COMMITTED, root=latest_local_root
                        )
                        latest_local_root = insert_result.root
                    else:
                        if reference_node_hash is None or side is None:
                            raise Exception("Provide both reference_node_hash and side or neither.")
                        insert_result = await self.insert(
                            key,
                            value,
                            store_id,
                            reference_node_hash,
                            side,
                            True,
                            Status.COMMITTED,
                            root=latest_local_root,
                        )
                        latest_local_root = insert_result.root
                elif change["action"] == "delete":
                    key = change["key"]
                    hash = key_hash(key)
                    if key_hash_frequency[hash] == 2 and last_action[hash] == "insert" and enable_batch_autoinsert:
                        continue
                    latest_local_root = await self.delete(key, store_id, True, Status.COMMITTED, root=latest_local_root)
                elif change["action"] == "upsert":
                    key = change["key"]
                    new_value = change["value"]
                    hash = key_hash(key)
                    if key_hash_frequency[hash] == 1 and enable_batch_autoinsert:
                        terminal_node_hash = await self._insert_terminal_node(key, new_value)
                        old_node = await self.maybe_get_node_from_key_hash(leaf_hashes, hash)
                        if old_node is not None:
                            pending_upsert_new_hashes[old_node.hash] = terminal_node_hash
                        else:
                            pending_autoinsert_hashes.append(terminal_node_hash)
                        continue
                    insert_result = await self.upsert(
                        key, new_value, store_id, True, Status.COMMITTED, root=latest_local_root
                    )
                    latest_local_root = insert_result.root
                else:
                    raise Exception(f"Operation in batch is not insert or delete: {change}")

            if len(pending_upsert_new_hashes) > 0:
                to_update_hashes: Set[bytes32] = set(pending_upsert_new_hashes.keys())
                to_update_queue: List[bytes32] = list(pending_upsert_new_hashes.keys())
                batch_size = min(500, SQLITE_MAX_VARIABLE_NUMBER - 10)

                while len(to_update_queue) > 0:
                    nodes = await self._get_one_ancestor_multiple_hashes(to_update_queue[:batch_size], store_id)
                    to_update_queue = to_update_queue[batch_size:]
                    for node in nodes:
                        if node.hash not in to_update_hashes:
                            to_update_hashes.add(node.hash)
                            to_update_queue.append(node.hash)

                assert latest_local_root is not None
                assert latest_local_root.node_hash is not None
                new_root_hash = await self.batch_upsert(
                    latest_local_root.node_hash,
                    to_update_hashes,
                    pending_upsert_new_hashes,
                )
                latest_local_root = await self._insert_root(store_id, new_root_hash, Status.COMMITTED)

            # Start with the leaf nodes and pair them to form new nodes at the next level up, repeating this process
            # in a bottom-up fashion until a single root node remains. This constructs a balanced tree from the leaves.
            while len(pending_autoinsert_hashes) > 1:
                new_hashes: List[bytes32] = []
                for i in range(0, len(pending_autoinsert_hashes) - 1, 2):
                    internal_node_hash = await self._insert_internal_node(
                        pending_autoinsert_hashes[i], pending_autoinsert_hashes[i + 1]
                    )
                    new_hashes.append(internal_node_hash)
                if len(pending_autoinsert_hashes) % 2 != 0:
                    new_hashes.append(pending_autoinsert_hashes[-1])

                pending_autoinsert_hashes = new_hashes

            if len(pending_autoinsert_hashes):
                subtree_hash = pending_autoinsert_hashes[0]
                if latest_local_root is None or latest_local_root.node_hash is None:
                    await self._insert_root(store_id=store_id, node_hash=subtree_hash, status=Status.COMMITTED)
                else:
                    hash_to_parent: Dict[bytes32, InternalNode] = {}
                    min_height_leaf = await self.get_leaf_at_minimum_height(latest_local_root.node_hash, hash_to_parent)
                    ancestors: List[InternalNode] = []
                    hash = min_height_leaf.hash
                    while hash in hash_to_parent:
                        node = hash_to_parent[hash]
                        ancestors.append(node)
                        hash = node.hash

                    await self.update_ancestor_hashes_on_insert(
                        store_id=store_id,
                        left=min_height_leaf.hash,
                        right=subtree_hash,
                        traversal_node_hash=min_height_leaf.hash,
                        ancestors=ancestors,
                        status=Status.COMMITTED,
                        root=latest_local_root,
                    )

            root = await self.get_tree_root(store_id=store_id)
            if root.node_hash == old_root.node_hash:
                if len(changelist) != 0:
                    await self.rollback_to_generation(store_id, old_root.generation)
                raise ValueError("Changelist resulted in no change to tree data")
            # We delete all "temporary" records stored in root and ancestor tables and store only the final result.
            await self.rollback_to_generation(store_id, old_root.generation)
            await self.insert_root_with_ancestor_table(store_id=store_id, node_hash=root.node_hash, status=status)
            if status in (Status.PENDING, Status.PENDING_BATCH):
                new_root = await self.get_pending_root(store_id=store_id)
                assert new_root is not None
            elif status == Status.COMMITTED:
                new_root = await self.get_tree_root(store_id=store_id)
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
        store_id: bytes32,
        generation: Optional[int] = None,
    ) -> Optional[InternalNode]:
        async with self.db_wrapper.reader() as reader:
            if generation is None:
                generation = await self.get_tree_generation(store_id=store_id)
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
                {"hash": node_hash, "tree_id": store_id, "generation": generation},
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return InternalNode.from_row(row=row)

    async def _get_one_ancestor_multiple_hashes(
        self,
        node_hashes: List[bytes32],
        store_id: bytes32,
        generation: Optional[int] = None,
    ) -> List[InternalNode]:
        async with self.db_wrapper.reader() as reader:
            node_hashes_place_holders = ",".join("?" for _ in node_hashes)
            if generation is None:
                generation = await self.get_tree_generation(store_id=store_id)
            cursor = await reader.execute(
                f"""
                SELECT * from node INNER JOIN (
                    SELECT ancestors.ancestor AS hash, MAX(ancestors.generation) AS generation
                    FROM ancestors
                    WHERE ancestors.hash IN ({node_hashes_place_holders})
                    AND ancestors.tree_id == ?
                    AND ancestors.generation <= ?
                    GROUP BY hash
                ) asc on asc.hash == node.hash
                """,
                [*node_hashes, store_id, generation],
            )
            rows = await cursor.fetchall()
            return [InternalNode.from_row(row=row) for row in rows]

    async def build_ancestor_table_for_latest_root(self, store_id: bytes32) -> None:
        async with self.db_wrapper.writer() as writer:
            root = await self.get_tree_root(store_id=store_id)
            if root.node_hash is None:
                return

            await writer.execute(
                """
                WITH RECURSIVE tree_from_root_hash AS (
                    SELECT
                        node.hash,
                        node.left,
                        node.right,
                        NULL AS ancestor
                    FROM node
                    WHERE node.hash = :root_hash
                    UNION ALL
                    SELECT
                        node.hash,
                        node.left,
                        node.right,
                        tree_from_root_hash.hash AS ancestor
                    FROM node
                    JOIN tree_from_root_hash ON node.hash = tree_from_root_hash.left
                    OR node.hash = tree_from_root_hash.right
                )
                INSERT OR REPLACE INTO ancestors (hash, ancestor, tree_id, generation)
                SELECT
                    tree_from_root_hash.hash,
                    tree_from_root_hash.ancestor,
                    :tree_id,
                    :generation
                FROM tree_from_root_hash
                """,
                {"root_hash": root.node_hash, "tree_id": store_id, "generation": root.generation},
            )

    async def insert_root_with_ancestor_table(
        self, store_id: bytes32, node_hash: Optional[bytes32], status: Status = Status.PENDING
    ) -> None:
        async with self.db_wrapper.writer():
            await self._insert_root(store_id=store_id, node_hash=node_hash, status=status)
            # Don't update the ancestor table for non-committed status.
            if status == Status.COMMITTED:
                await self.build_ancestor_table_for_latest_root(store_id=store_id)

    async def get_node_by_key_latest_generation(self, key: bytes, store_id: bytes32) -> TerminalNode:
        async with self.db_wrapper.reader() as reader:
            root = await self.get_tree_root(store_id=store_id)
            if root.node_hash is None:
                raise KeyNotFoundError(key=key)

            cursor = await reader.execute(
                """
                SELECT a.hash FROM ancestors a
                JOIN node n ON a.hash = n.hash
                WHERE n.key = :key
                AND a.tree_id = :tree_id
                ORDER BY a.generation DESC
                LIMIT 1
                """,
                {"key": key, "tree_id": store_id},
            )

            row = await cursor.fetchone()
            if row is None:
                raise KeyNotFoundError(key=key)

            node = await self.get_node(row["hash"])
            node_hash = node.hash
            while True:
                internal_node = await self._get_one_ancestor(node_hash, store_id)
                if internal_node is None:
                    break
                node_hash = internal_node.hash

            if node_hash != root.node_hash:
                raise KeyNotFoundError(key=key)
            assert isinstance(node, TerminalNode)
            return node

    async def maybe_get_node_from_key_hash(
        self, leaf_hashes: Dict[bytes32, bytes32], hash: bytes32
    ) -> Optional[TerminalNode]:
        if hash in leaf_hashes:
            leaf_hash = leaf_hashes[hash]
            node = await self.get_node(leaf_hash)
            assert isinstance(node, TerminalNode)
            return node

        return None

    async def maybe_get_node_by_key(self, key: bytes, store_id: bytes32) -> Optional[TerminalNode]:
        try:
            node = await self.get_node_by_key_latest_generation(key, store_id)
            return node
        except KeyNotFoundError:
            return None

    async def get_node_by_key(
        self,
        key: bytes,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> TerminalNode:
        if root_hash is unspecified:
            return await self.get_node_by_key_latest_generation(key, store_id)

        nodes = await self.get_keys_values(store_id=store_id, root_hash=root_hash)

        for node in nodes:
            if node.key == key:
                return node

        raise KeyNotFoundError(key=key)

    async def get_node(self, node_hash: bytes32) -> Node:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT * FROM node WHERE hash == :hash LIMIT 1", {"hash": node_hash})
            row = await cursor.fetchone()

        if row is None:
            raise Exception(f"Node not found for requested hash: {node_hash.hex()}")

        node = row_to_node(row=row)
        return node

    async def get_tree_as_nodes(self, store_id: bytes32) -> Node:
        async with self.db_wrapper.reader() as reader:
            root = await self.get_tree_root(store_id=store_id)
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
                    node = replace(node, left=hash_to_node[node.left_hash], right=hash_to_node[node.right_hash])
                hash_to_node[node.hash] = node

            root_node = hash_to_node[root_node.hash]

        return root_node

    async def get_proof_of_inclusion_by_hash(
        self,
        node_hash: bytes32,
        store_id: bytes32,
        root_hash: Optional[bytes32] = None,
        use_optimized: bool = False,
    ) -> ProofOfInclusion:
        """Collect the information for a proof of inclusion of a hash in the Merkle
        tree.
        """

        # Ideally this would use get_ancestors_common, but this _common function has this interesting property
        # when used with use_optimized=False - it will compare both methods in this case and raise an exception.
        # this is undesirable in the DL Offers flow where PENDING roots can cause the optimized code to fail.
        if use_optimized:
            ancestors = await self.get_ancestors_optimized(node_hash=node_hash, store_id=store_id, root_hash=root_hash)
        else:
            ancestors = await self.get_ancestors(node_hash=node_hash, store_id=store_id, root_hash=root_hash)

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
        store_id: bytes32,
    ) -> ProofOfInclusion:
        """Collect the information for a proof of inclusion of a key and its value in
        the Merkle tree.
        """
        async with self.db_wrapper.reader():
            node = await self.get_node_by_key(key=key, store_id=store_id)
            return await self.get_proof_of_inclusion_by_hash(node_hash=node.hash, store_id=store_id)

    async def get_first_generation(self, node_hash: bytes32, store_id: bytes32) -> int:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT MIN(generation) AS generation FROM ancestors WHERE hash == :hash AND tree_id == :tree_id",
                {"hash": node_hash, "tree_id": store_id},
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
        store_id: bytes32,
        deltas_only: bool,
        writer: BinaryIO,
    ) -> None:
        if node_hash == bytes32([0] * 32):
            return

        if deltas_only:
            generation = await self.get_first_generation(node_hash, store_id)
            # Root's generation is not the first time we see this hash, so it's not a new delta.
            if root.generation != generation:
                return
        node = await self.get_node(node_hash)
        to_write = b""
        if isinstance(node, InternalNode):
            await self.write_tree_to_file(root, node.left_hash, store_id, deltas_only, writer)
            await self.write_tree_to_file(root, node.right_hash, store_id, deltas_only, writer)
            to_write = bytes(SerializedNode(False, bytes(node.left_hash), bytes(node.right_hash)))
        elif isinstance(node, TerminalNode):
            to_write = bytes(SerializedNode(True, node.key, node.value))
        else:
            raise Exception(f"Node is neither InternalNode nor TerminalNode: {node}")

        writer.write(len(to_write).to_bytes(4, byteorder="big"))
        writer.write(to_write)

    async def update_subscriptions_from_wallet(self, store_id: bytes32, new_urls: List[str]) -> None:
        async with self.db_wrapper.writer() as writer:
            cursor = await writer.execute(
                "SELECT * FROM subscriptions WHERE from_wallet == 1 AND tree_id == :tree_id",
                {
                    "tree_id": store_id,
                },
            )
            old_urls = [row["url"] async for row in cursor]
            cursor = await writer.execute(
                "SELECT * FROM subscriptions WHERE from_wallet == 0 AND tree_id == :tree_id",
                {
                    "tree_id": store_id,
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
                        "tree_id": store_id,
                    },
                )
            for url in additions:
                if url not in from_subscriptions_urls:
                    await writer.execute(
                        "INSERT INTO subscriptions(tree_id, url, ignore_till, num_consecutive_failures, from_wallet) "
                        "VALUES (:tree_id, :url, 0, 0, 1)",
                        {
                            "tree_id": store_id,
                            "url": url,
                        },
                    )

    async def subscribe(self, subscription: Subscription) -> None:
        async with self.db_wrapper.writer() as writer:
            # Add a fake subscription, so we always have the store_id, even with no URLs.
            await writer.execute(
                "INSERT INTO subscriptions(tree_id, url, ignore_till, num_consecutive_failures, from_wallet) "
                "VALUES (:tree_id, NULL, NULL, NULL, 0)",
                {
                    "tree_id": subscription.store_id,
                },
            )
            all_subscriptions = await self.get_subscriptions()
            old_subscription = next(
                (
                    old_subscription
                    for old_subscription in all_subscriptions
                    if old_subscription.store_id == subscription.store_id
                ),
                None,
            )
            old_urls = set()
            if old_subscription is not None:
                old_urls = {server_info.url for server_info in old_subscription.servers_info}
            new_servers = [server_info for server_info in subscription.servers_info if server_info.url not in old_urls]
            for server_info in new_servers:
                await writer.execute(
                    "INSERT INTO subscriptions(tree_id, url, ignore_till, num_consecutive_failures, from_wallet) "
                    "VALUES (:tree_id, :url, :ignore_till, :num_consecutive_failures, 0)",
                    {
                        "tree_id": subscription.store_id,
                        "url": server_info.url,
                        "ignore_till": server_info.ignore_till,
                        "num_consecutive_failures": server_info.num_consecutive_failures,
                    },
                )

    async def remove_subscriptions(self, store_id: bytes32, urls: List[str]) -> None:
        async with self.db_wrapper.writer() as writer:
            for url in urls:
                await writer.execute(
                    "DELETE FROM subscriptions WHERE tree_id == :tree_id AND url == :url",
                    {
                        "tree_id": store_id,
                        "url": url,
                    },
                )

    async def delete_store_data(self, store_id: bytes32) -> None:
        async with self.db_wrapper.writer(foreign_key_enforcement_enabled=False) as writer:
            await self.clean_node_table(writer)
            cursor = await writer.execute(
                """
                WITH RECURSIVE all_nodes AS (
                    SELECT a.hash, n.left, n.right
                    FROM ancestors AS a
                    JOIN node AS n ON a.hash = n.hash
                    WHERE a.tree_id = :tree_id
                ),
                pending_nodes AS (
                    SELECT node_hash AS hash FROM root
                    WHERE status IN (:pending_status, :pending_batch_status)
                    UNION ALL
                    SELECT n.left FROM node n
                    INNER JOIN pending_nodes pn ON n.hash = pn.hash
                    WHERE n.left IS NOT NULL
                    UNION ALL
                    SELECT n.right FROM node n
                    INNER JOIN pending_nodes pn ON n.hash = pn.hash
                    WHERE n.right IS NOT NULL
                )

                SELECT hash, left, right
                FROM all_nodes
                WHERE hash NOT IN (SELECT hash FROM ancestors WHERE tree_id != :tree_id)
                AND hash NOT IN (SELECT hash from pending_nodes)
                """,
                {
                    "tree_id": store_id,
                    "pending_status": Status.PENDING.value,
                    "pending_batch_status": Status.PENDING_BATCH.value,
                },
            )
            to_delete: Dict[bytes, Tuple[bytes, bytes]] = {}
            ref_counts: Dict[bytes, int] = {}
            async for row in cursor:
                hash = row["hash"]
                left = row["left"]
                right = row["right"]
                if hash in to_delete:
                    prev_left, prev_right = to_delete[hash]
                    assert prev_left == left
                    assert prev_right == right
                    continue
                to_delete[hash] = (left, right)
                if left is not None:
                    ref_counts[left] = ref_counts.get(left, 0) + 1
                if right is not None:
                    ref_counts[right] = ref_counts.get(right, 0) + 1

            await writer.execute("DELETE FROM ancestors WHERE tree_id == ?", (store_id,))
            await writer.execute("DELETE FROM root WHERE tree_id == ?", (store_id,))
            queue = [hash for hash in to_delete if ref_counts.get(hash, 0) == 0]
            while queue:
                hash = queue.pop(0)
                if hash not in to_delete:
                    continue
                await writer.execute("DELETE FROM node WHERE hash == ?", (hash,))

                left, right = to_delete[hash]
                if left is not None:
                    ref_counts[left] -= 1
                    if ref_counts[left] == 0:
                        queue.append(left)

                if right is not None:
                    ref_counts[right] -= 1
                    if ref_counts[right] == 0:
                        queue.append(right)

    async def unsubscribe(self, store_id: bytes32) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "DELETE FROM subscriptions WHERE tree_id == :tree_id",
                {"tree_id": store_id},
            )

    async def rollback_to_generation(self, store_id: bytes32, target_generation: int) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "DELETE FROM ancestors WHERE tree_id == :tree_id AND generation > :target_generation",
                {"tree_id": store_id, "target_generation": target_generation},
            )
            await writer.execute(
                "DELETE FROM root WHERE tree_id == :tree_id AND generation > :target_generation",
                {"tree_id": store_id, "target_generation": target_generation},
            )

    async def update_server_info(self, store_id: bytes32, server_info: ServerInfo) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "UPDATE subscriptions SET ignore_till = :ignore_till, "
                "num_consecutive_failures = :num_consecutive_failures WHERE tree_id = :tree_id AND url = :url",
                {
                    "ignore_till": server_info.ignore_till,
                    "num_consecutive_failures": server_info.num_consecutive_failures,
                    "tree_id": store_id,
                    "url": server_info.url,
                },
            )

    async def received_incorrect_file(self, store_id: bytes32, server_info: ServerInfo, timestamp: int) -> None:
        SEVEN_DAYS_BAN = 7 * 24 * 60 * 60
        new_server_info = replace(
            server_info,
            num_consecutive_failures=server_info.num_consecutive_failures + 1,
            ignore_till=max(server_info.ignore_till, timestamp + SEVEN_DAYS_BAN),
        )
        await self.update_server_info(store_id, new_server_info)

    async def received_correct_file(self, store_id: bytes32, server_info: ServerInfo) -> None:
        new_server_info = replace(
            server_info,
            num_consecutive_failures=0,
        )
        await self.update_server_info(store_id, new_server_info)

    async def server_misses_file(self, store_id: bytes32, server_info: ServerInfo, timestamp: int) -> ServerInfo:
        # Max banned time is 1 hour.
        BAN_TIME_BY_MISSING_COUNT = [5 * 60] * 3 + [15 * 60] * 3 + [30 * 60] * 2 + [60 * 60]
        index = min(server_info.num_consecutive_failures, len(BAN_TIME_BY_MISSING_COUNT) - 1)
        new_server_info = replace(
            server_info,
            num_consecutive_failures=server_info.num_consecutive_failures + 1,
            ignore_till=max(server_info.ignore_till, timestamp + BAN_TIME_BY_MISSING_COUNT[index]),
        )
        await self.update_server_info(store_id, new_server_info)
        return new_server_info

    async def get_available_servers_for_store(self, store_id: bytes32, timestamp: int) -> List[ServerInfo]:
        subscriptions = await self.get_subscriptions()
        subscription = next((subscription for subscription in subscriptions if subscription.store_id == store_id), None)
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
                store_id = bytes32(row["tree_id"])
                url = row["url"]
                ignore_till = row["ignore_till"]
                num_consecutive_failures = row["num_consecutive_failures"]
                subscription = next(
                    (subscription for subscription in subscriptions if subscription.store_id == store_id), None
                )
                if subscription is None:
                    if url is not None and num_consecutive_failures is not None and ignore_till is not None:
                        subscriptions.append(
                            Subscription(store_id, [ServerInfo(url, num_consecutive_failures, ignore_till)])
                        )
                    else:
                        subscriptions.append(Subscription(store_id, []))
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
        store_id: bytes32,
        # NOTE: empty is expressed as zeros
        hash_1: bytes32,
        hash_2: bytes32,
    ) -> Set[DiffData]:
        async with self.db_wrapper.reader():
            old_pairs = set(await self.get_keys_values(store_id, hash_1))
            if len(old_pairs) == 0 and hash_1 != bytes32([0] * 32):
                raise Exception(f"Unable to diff: Can't find keys and values for {hash_1}")

            new_pairs = set(await self.get_keys_values(store_id, hash_2))
            if len(new_pairs) == 0 and hash_2 != bytes32([0] * 32):
                raise Exception(f"Unable to diff: Can't find keys and values for {hash_2}")

            insertions = {
                DiffData(type=OperationType.INSERT, key=node.key, value=node.value)
                for node in new_pairs
                if node not in old_pairs
            }
            deletions = {
                DiffData(type=OperationType.DELETE, key=node.key, value=node.value)
                for node in old_pairs
                if node not in new_pairs
            }
            return set.union(insertions, deletions)
