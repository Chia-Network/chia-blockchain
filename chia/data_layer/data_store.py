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
    _debug_dump,
    get_hashes_for_page,
    internal_hash,
    key_hash,
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
                # await writer.execute(
                #     """
                #         CREATE TABLE IF NOT EXISTS blob(
                #             hash BLOB PRIMARY KEY NULL CHECK(length(hash) == 32),
                #             blob BLOB
                #         )
                #         """
                # )
                # TODO: parent should be a reference, as should left and right.
                #       except for the null-ness or the 00000....ness or...
                await writer.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS node(
                        tree_id BLOB NOT NULL CHECK(length(tree_id) == 32),
                        generation INTEGER NOT NULL CHECK(generation >= 0),
                        hash BLOB NOT NULL CHECK(length(hash) == 32),
                        parent BLOB,
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
                        left BLOB,
                        right BLOB,
                        key BLOB,
                        value BLOB,
                        PRIMARY KEY(tree_id, generation, hash)
                    )
                    """
                    # TODO: can we get some check on this?  problem being insertion then post-update-of-parent
                    # UNIQUE(tree_id, generation, parent)
                    # TODO: can we recover these foreign key constraints?
                    # FOREIGN KEY(tree_id, generation, parent) REFERENCES node(tree_id, generation, hash)
                    # FOREIGN KEY(tree_id, generation, left) REFERENCES node(tree_id, generation, hash)
                    # FOREIGN KEY(tree_id, generation, right) REFERENCES node(tree_id, generation, hash)
                )
                # TODO: replace with only setting a node from no parent to having a parent?
                # await writer.execute(
                #     """
                #     CREATE TRIGGER IF NOT EXISTS no_node_updates
                #     BEFORE UPDATE ON node
                #     BEGIN
                #         SELECT RAISE(FAIL, 'updates not allowed to the node table');
                #     END
                #     """
                # )
                await writer.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS root(
                        tree_id BLOB NOT NULL CHECK(length(tree_id) == 32),
                        generation INTEGER NOT NULL CHECK(generation >= 0),
                        status INTEGER NOT NULL CHECK(
                            {" OR ".join(f"status == {status}" for status in Status)}
                        ),
                        PRIMARY KEY(tree_id, generation)
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
                    CREATE INDEX IF NOT EXISTS node_key_index ON node(key)
                    """
                )
                # await writer.execute(
                #     """
                #     CREATE INDEX IF NOT EXISTS node_hash_index ON node(hash)
                #     """
                # )
                # await writer.execute(
                #     """
                #     CREATE INDEX IF NOT EXISTS node_left_index ON node(left)
                #     """
                # )
                # await writer.execute(
                #     """
                #     CREATE INDEX IF NOT EXISTS node_right_index ON node(right)
                #     """
                # )
                # await writer.execute(
                #     """
                #     CREATE INDEX IF NOT EXISTS node_tree_id_generation_left_index ON node(tree_id, generation, left)
                #     """
                # )
                # await writer.execute(
                #     """
                #     CREATE INDEX IF NOT EXISTS node_tree_id_generation_right_index ON node(tree_id, generation, right)
                #     """
                # )
                # await writer.execute(
                #     """
                #     CREATE INDEX IF NOT EXISTS node_tree_id_generation_hash_index ON node(tree_id, generation, hash)
                #     """
                # )
                # await writer.execute(
                #     """
                #     CREATE INDEX IF NOT EXISTS node_tree_id_generation_hash_index ON node(tree_id, generation, parent)
                #     """
                # )

            yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self.db_wrapper.writer():
            yield

    async def _get_root_hash(self, tree_id: bytes32, generation: int) -> Optional[bytes32]:
        # TODO: should not be handled this way
        async with self.db_wrapper.reader() as reader:
            # await _debug_dump(db=self.db_wrapper, description=f"Reading {bytes(tree_id)} {generation}")
            cursor = await reader.execute(
                """
                SELECT hash
                FROM node
                WHERE tree_id = :tree_id AND generation = :generation AND parent IS NULL
                LIMIT 1
                """,
                {"tree_id": tree_id, "generation": generation},
            )
            hash_row = await cursor.fetchone()

        if hash_row is None:
            node_hash = None
        else:
            node_hash = bytes32(hash_row["hash"])

        return node_hash

    async def _insert_root(
        self,
        tree_id: bytes32,
        node_hash: Optional[bytes32],
        status: Status,
        # TODO: review calls for it now being optional and defaulted
        #       but this seems a bit high level to be auto-picking in this method
        generation: Optional[int] = None,
    ) -> Root:
        # TODO: should this be 'removed' and just use the new generation method?
        # This should be replaced by an SQLite schema level check.
        # https://github.com/Chia-Network/chia-blockchain/pull/9284
        tree_id = bytes32(tree_id)

        async with self.db_wrapper.writer() as writer:
            if generation is None:
                try:
                    existing_generation = await self.get_tree_generation(tree_id=tree_id)
                except Exception as e:
                    if not str(e).startswith("No generations found for tree ID:"):
                        raise
                    generation = 0
                else:
                    generation = existing_generation + 1

            new_root = Root(
                tree_id=tree_id,
                node_hash=node_hash,
                generation=generation,
                status=status,
            )

            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, status)
                VALUES(:tree_id, :generation, :status)
                ON CONFLICT(tree_id, generation)
                DO UPDATE SET status = :status
                """,
                new_root.to_row(),
            )

            return new_root

    async def _insert_node(
        self,
        tree_id: bytes32,
        generation: int,
        node_hash: bytes32,
        parent_hash: Optional[bytes32],
        node_type: NodeType,
        left_hash: Optional[bytes32],
        right_hash: Optional[bytes32],
        key: Optional[bytes],
        value: Optional[bytes],
    ) -> None:
        # TODO: can we get sqlite to do this check?
        values = {
            "tree_id": tree_id,
            "generation": generation,
            "hash": node_hash,
            "parent": parent_hash,
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
                    INSERT INTO node(tree_id, generation, hash, parent, node_type, left, right, key, value)
                    VALUES(:tree_id, :generation, :hash, :parent, :node_type, :left, :right, :key, :value)
                    """,
                    values,
                )
            except aiosqlite.IntegrityError as e:
                if not e.args[0].startswith("UNIQUE constraint"):
                    # UNIQUE constraint failed: node.hash
                    raise

                # TODO: this probably needs updated for newer primary key and schema structure
                cursor = await writer.execute(
                    "SELECT * FROM node WHERE hash == :hash LIMIT 1",
                    {"hash": node_hash},
                )
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

    async def insert_node(
        self,
        tree_id: bytes32,
        generation: int,
        parent_hash: Optional[bytes32],
        node_type: NodeType,
        value1: bytes,
        value2: bytes,
    ) -> None:
        if node_type == NodeType.INTERNAL:
            left_hash = bytes32(value1)
            right_hash = bytes32(value2)
            node_hash = internal_hash(left_hash, right_hash)
            await self._insert_node(
                tree_id=tree_id,
                generation=generation,
                node_hash=node_hash,
                parent_hash=parent_hash,
                node_type=node_type,
                left_hash=bytes32(value1),
                right_hash=bytes32(value2),
                key=None,
                value=None,
            )
        else:
            node_hash = leaf_hash(key=value1, value=value2)
            await self._insert_node(
                tree_id=tree_id,
                generation=generation,
                node_hash=node_hash,
                parent_hash=parent_hash,
                node_type=node_type,
                left_hash=None,
                right_hash=None,
                key=value1,
                value=value2,
            )

    async def _insert_internal_node(
        self,
        tree_id: bytes32,
        generation: int,
        parent_hash: Optional[bytes32],
        left_hash: bytes32,
        right_hash: bytes32,
    ) -> bytes32:
        node_hash: bytes32 = internal_hash(left_hash=left_hash, right_hash=right_hash)

        await self._insert_node(
            tree_id=tree_id,
            generation=generation,
            node_hash=node_hash,
            parent_hash=parent_hash,
            node_type=NodeType.INTERNAL,
            left_hash=left_hash,
            right_hash=right_hash,
            key=None,
            value=None,
        )

        return node_hash

    async def _insert_terminal_node(
        self,
        tree_id: bytes32,
        generation: int,
        parent_hash: Optional[bytes32],
        key: bytes,
        value: bytes,
    ) -> bytes32:
        # forcing type hint here for:
        # https://github.com/Chia-Network/clvm/pull/102
        # https://github.com/Chia-Network/clvm/pull/106
        node_hash: bytes32 = Program.to((key, value)).get_tree_hash()

        await self._insert_node(
            tree_id=tree_id,
            generation=generation,
            node_hash=node_hash,
            parent_hash=parent_hash,
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
                """
                SELECT * FROM root WHERE tree_id == :tree_id
                AND status IN (:pending_status, :pending_batch_status) LIMIT 2
                """,
                {
                    "tree_id": tree_id,
                    "pending_status": Status.PENDING.value,
                    "pending_batch_status": Status.PENDING_BATCH.value,
                },
            )

            row = await cursor.fetchone()

            if row is None:
                return None

            maybe_extra_result = await cursor.fetchone()
            if maybe_extra_result is not None:
                raise Exception(f"multiple pending roots found for id: {tree_id.hex()}")

        return await Root.from_row(row=row, data_store=self)

    async def clear_pending_roots(self, tree_id: bytes32) -> Optional[Root]:
        async with self.db_wrapper.writer() as writer:
            pending_root = await self.get_pending_root(tree_id=tree_id)

            if pending_root is not None:
                await writer.execute(
                    "DELETE FROM root WHERE tree_id == :tree_id AND status IN (:pending_status, :pending_batch_status)",
                    {
                        "tree_id": tree_id,
                        "pending_status": Status.PENDING.value,
                        "pending_batch_status": Status.PENDING_BATCH.value,
                    },
                )

        return pending_root

    async def shift_root_generations(self, tree_id: bytes32, shift_size: int) -> None:
        async with self.db_wrapper.writer():
            root = await self.get_tree_root(tree_id=tree_id)
            for shift in range(shift_size):
                await self._insert_root(
                    tree_id=tree_id,
                    node_hash=root.node_hash,
                    status=Status.COMMITTED,
                    generation=root.generation + shift,
                )

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
            roots = [await Root.from_row(row=row, data_store=self) async for row in cursor]

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

    _checks: Tuple[Callable[[DataStore], Awaitable[None]], ...] = (
        _check_roots_are_incrementing,
        _check_hashes,
    )

    async def create_tree(self, tree_id: bytes32, status: Status = Status.PENDING) -> bool:
        await self._insert_root(tree_id=tree_id, node_hash=None, status=status, generation=0)

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

        if row is not None:
            generation: Optional[int] = row["MAX(generation)"]

            if generation is not None:
                return generation

        raise Exception(f"No generations found for tree ID: {tree_id.hex()}")

    async def get_tree_root(self, tree_id: bytes32, generation: Optional[int] = None) -> Root:
        async with self.db_wrapper.reader() as reader:
            if generation is None:
                generation = await self.get_tree_generation(tree_id=tree_id)
            cursor = await reader.execute(
                """
                SELECT *
                FROM root
                WHERE tree_id == :tree_id AND generation == :generation AND status == :status
                LIMIT 1
                """,
                {"tree_id": tree_id, "generation": generation, "status": Status.COMMITTED.value},
            )
            row = await cursor.fetchone()

            if row is None:
                raise Exception(f"unable to find root for id, generation: {tree_id.hex()}, {generation}")

        return await Root.from_row(row=row, data_store=self)

    async def tree_id_exists(self, tree_id: bytes32) -> bool:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT 1 FROM root WHERE tree_id == :tree_id AND status == :status LIMIT 1",
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
            roots = [await Root.from_row(row=row, data_store=self) async for row in cursor]

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
        return await Root.from_row(row=row, data_store=self)

    # async def _get_latest_generation(self, tree_id: bytes32, root: Optional[bytes32]) -> int:
    #     # TODO: checks and implementation around empty generations
    #     async with self.db_wrapper.reader() as reader:
    #         async with reader.execute(
    #             """
    #             SELECT generation
    #             FROM node
    #             WHERE tree_id = :tree_id AND parent = :parent AND hash = root
    #             ORDER BY generation DESC LIMIT 1
    #             """,
    #             {"tree_id": tree_id, "root": root},
    #         ) as cursor:
    #             [row] = await cursor.fetchone()
    #
    #     return row["generation"]

    async def get_lineage(
        self,
        node_hash: bytes32,
        tree_id: bytes32,
        generation: int,
    ) -> List[Union[InternalNode, TerminalNode]]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                # TODO: do we need ordering?
                """
                WITH RECURSIVE
                    ancestors(tree_id, generation, hash, parent, node_type, left, right, key, value) AS (
                        SELECT *
                        FROM node
                        WHERE (
                            node.tree_id = :tree_id
                            AND node.generation = :generation
                            AND node.hash = :reference_hash
                        )
                        UNION ALL
                        SELECT node.*
                        FROM node, ancestors
                        WHERE (
                            node.tree_id = :tree_id
                            AND node.generation = :generation
                            AND ancestors.parent IS NOT NULL
                            AND node.hash = ancestors.parent
                        )
                    )
                SELECT * FROM ancestors
                """,
                {"reference_hash": node_hash, "tree_id": tree_id, "generation": generation},
            )

            rows = await cursor.fetchall()

        # The resulting rows must represent internal nodes.  InternalNode.from_row()
        # does some amount of validation in the sense that it will fail if left
        # or right can't turn into a bytes32 as expected.  There is room for more
        # validation here if desired.
        lineage: List[InternalNode] = [row_to_node(row=row) for row in rows]

        # TODO: real checks
        assert all(isinstance(node, InternalNode) for node in lineage[1:])
        return lineage

    async def get_ancestors(
        self,
        node_hash: bytes32,
        tree_id: bytes32,
        generation: Optional[int] = None,
    ) -> List[InternalNode]:
        if generation is None:
            generation = await self.get_tree_generation(tree_id=tree_id)
        lineage = await self.get_lineage(node_hash=node_hash, tree_id=tree_id, generation=generation)
        return lineage[1:]

    async def get_internal_nodes(self, tree_id: bytes32, root_hash: Optional[bytes32] = None) -> List[InternalNode]:
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(tree_id=tree_id)
                root_hash = root.node_hash
            cursor = await reader.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(tree_id, generation, hash, parent, node_type, left, right, key, value) AS (
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

    async def get_keys_values_cursor(
        self,
        reader: aiosqlite.Connection,
        root_hash: Optional[bytes32],
        tree_id: bytes32,
        generation: int,
    ) -> aiosqlite.Cursor:
        # TODO: still have the 62 or whatever limit here at this point
        return await reader.execute(
            """
            WITH RECURSIVE
                tree_from_root_hash(
                    tree_id,
                    generation,
                    hash,
                    parent,
                    node_type,
                    left,
                    right,
                    key,
                    value,
                    depth,
                    rights
                ) AS (
                    SELECT node.*, 0 AS depth, 0 AS rights
                    FROM node
                    WHERE tree_id = :tree_id AND generation = :generation AND node.hash == :root_hash
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
                    WHERE (
                        node.tree_id = :tree_id
                        AND node.generation = :generation
                        AND (
                            node.hash == tree_from_root_hash.left
                            OR node.hash == tree_from_root_hash.right
                        )
                    )
                )
            SELECT * FROM tree_from_root_hash
            WHERE node_type == :node_type
            ORDER BY depth ASC, rights ASC
            """,
            {"tree_id": tree_id, "generation": generation, "root_hash": root_hash, "node_type": NodeType.TERMINAL},
        )

    async def get_keys_values(self, tree_id: bytes32, root_hash: Optional[bytes32] = None) -> List[TerminalNode]:
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(tree_id=tree_id)
                root_hash = root.node_hash

            # TODO: too assuming
            generation = await self.get_tree_generation(tree_id=tree_id)

            cursor = await self.get_keys_values_cursor(
                reader=reader, root_hash=root_hash, tree_id=tree_id, generation=generation
            )
            terminal_nodes: List[TerminalNode] = []
            async for row in cursor:
                # TODO: 62 depth limit
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
        self, tree_id: bytes32, root_hash: Optional[bytes32] = None
    ) -> KeysValuesCompressed:
        async with self.db_wrapper.reader() as reader:
            if root_hash is None:
                root = await self.get_tree_root(tree_id=tree_id)
                root_hash = root.node_hash

            cursor = await self.get_keys_values_cursor(reader, root_hash)
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

            return KeysValuesCompressed(keys_values_hashed, key_hash_to_length, leaf_hash_to_length, root_hash)

    async def get_keys_paginated(
        self, tree_id: bytes32, page: int, max_page_size: int, root_hash: Optional[bytes32] = None
    ) -> KeysPaginationData:
        keys_values_compressed = await self.get_keys_values_compressed(tree_id, root_hash)
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
        self, tree_id: bytes32, page: int, max_page_size: int, root_hash: Optional[bytes32] = None
    ) -> KeysValuesPaginationData:
        keys_values_compressed = await self.get_keys_values_compressed(tree_id, root_hash)
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
        self, tree_id: bytes32, page: int, max_page_size: int, hash1: bytes32, hash2: bytes32
    ) -> KVDiffPaginationData:
        old_pairs = await self.get_keys_values_compressed(tree_id, hash1)
        new_pairs = await self.get_keys_values_compressed(tree_id, hash2)
        if len(old_pairs.keys_values_hashed) == 0 and hash1 != bytes32([0] * 32):
            return KVDiffPaginationData(1, 0, [])
        if len(new_pairs.keys_values_hashed) == 0 and hash2 != bytes32([0] * 32):
            return KVDiffPaginationData(1, 0, [])

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
        self,
        root: Root,
        seed: bytes32,
    ) -> Optional[bytes32]:
        path = "".join(reversed("".join(f"{b:08b}" for b in seed)))
        reference_node_hash = root.node_hash
        for raw_side in path:
            node = await self.get_node(
                tree_id=root.tree_id,
                generation=root.generation,
                node_hash=reference_node_hash,
            )
            # cursor = await reader.execute(
            #     """
            #     SELECT *
            #     FROM node
            #     WHERE tree_id = :tree_id AND generation = :generation AND hash = :hash
            #     LIMIT 1
            #     """,
            #     {"tree_id": root.tree_id, "generation": root.generation, "hash": reference_node_hash},
            # )
            # row = await cursor.fetchone()
            # node = row_to_node(row=row)
            if isinstance(node, TerminalNode):
                break

            if raw_side == "0":
                reference_node_hash = node.left_hash
            else:
                reference_node_hash = node.right_hash
        return reference_node_hash

    def get_side_for_seed(self, seed: bytes32) -> Side:
        side_seed = bytes(seed)[0]
        return Side.LEFT if side_seed < 128 else Side.RIGHT

    async def autoinsert(
        self,
        key: bytes,
        value: bytes,
        tree_id: bytes32,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
        new_generation: Optional[int] = None,
    ) -> InsertResult:
        async with self.db_wrapper.writer():
            if root is None:
                root = await self.get_tree_root(tree_id=tree_id)

            was_empty = root.node_hash is None

            if was_empty:
                reference_node_hash = None
                side = None
            else:
                seed = leaf_hash(key=key, value=value)
                reference_node_hash = await self.get_terminal_node_for_seed(root=root, seed=seed)
                side = self.get_side_for_seed(seed)

            return await self.insert(
                key=key,
                value=value,
                tree_id=tree_id,
                reference_node_hash=reference_node_hash,
                side=side,
                status=status,
                root=root,
                new_generation=new_generation,
            )

    async def get_keys_values_dict(self, tree_id: bytes32, root_hash: Optional[bytes32] = None) -> Dict[bytes, bytes]:
        pairs = await self.get_keys_values(tree_id=tree_id, root_hash=root_hash)
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

    async def _create_new_generation(self, tree_id: bytes32) -> int:
        # TODO: what protections could we add around this?
        async with self.db_wrapper.writer() as writer:
            old_generation = await self.get_tree_generation(tree_id=tree_id)
            new_generation = old_generation + 1

            # # TODO: for debug
            # async with writer.execute(
            #     """
            #     SELECT tree_id, :new_generation, hash, parent, node_type, left, right, key, value
            #     FROM node
            #     WHERE tree_id = :tree_id AND generation = :old_generation
            #     """,
            #     {"tree_id": tree_id, "old_generation": old_generation, "new_generation": new_generation},
            # ) as cursor:
            #     rows = await cursor.fetchall()
            #     d = [dict(row) for row in rows]
            #     # await _debug_dump(db=self.db_wrapper, description="hum")

            await writer.execute(
                """
                INSERT INTO node(tree_id, generation, hash, parent, node_type, left, right, key, value)
                SELECT tree_id, :new_generation, hash, parent, node_type, left, right, key, value
                FROM node
                WHERE tree_id = :tree_id AND generation = :old_generation
                """,
                {"tree_id": tree_id, "old_generation": old_generation, "new_generation": new_generation},
            )

            # TODO: can we do the root here as well?

        return new_generation

    async def update_ancestor_hashes_on_insert(
        self,
        tree_id: bytes32,
        left: bytes32,
        right: bytes32,
        traversal_node_hash: bytes32,
        ancestors: List[InternalNode],
        status: Status,
        # TODO: remove this?
        root: Root,
        terminal_hash: bytes32,
        new_generation: int,
    ) -> Root:
        # create first new internal node
        new_hash = await self._insert_internal_node(
            tree_id=tree_id, generation=new_generation, parent_hash=None, left_hash=left, right_hash=right
        )

        # await _debug_dump(db=self.db_wrapper, description="before ._set_parent()")
        # TODO: add to ._insert_internal_node()?
        for hash in [left, right]:
            await self._set_parent(
                tree_id=tree_id,
                generation=new_generation,
                node_hash=hash,
                parent_hash=new_hash,
            )
        await _debug_dump(db=self.db_wrapper, description="after ._set_parent()")
        child_hash = new_hash

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

            async with self.db_wrapper.writer() as writer:
                await writer.execute(
                    """
                    DELETE FROM node
                    WHERE tree_id = :tree_id AND generation = :generation AND hash = :hash
                    """,
                    {"tree_id": tree_id, "generation": new_generation, "hash": ancestor.hash},
                )

            await _debug_dump(db=self.db_wrapper, description="after delete")

            new_hash = await self._insert_internal_node(
                tree_id=tree_id, generation=new_generation, parent_hash=None, left_hash=left, right_hash=right
            )
            for hash in [left, right]:
                await self._set_parent(
                    tree_id=tree_id,
                    generation=new_generation,
                    node_hash=hash,
                    parent_hash=new_hash,
                )
            # await self._set_parent(
            #     tree_id=tree_id,
            #     generation=new_generation,
            #     node_hash=child_hash,
            #     parent_hash=new_hash,
            # )
            # child_hash = new_hash
            # new_hash = t

        new_root = await self._insert_root(
            tree_id=tree_id,
            node_hash=new_hash,
            status=status,
            generation=new_generation,
        )

        return new_root

    async def _set_parent(
        self,
        tree_id: bytes32,
        generation: int,
        node_hash: bytes32,
        parent_hash: Optional[bytes32],
    ) -> None:
        # TODO: maybe set an sql check to only allow NULL -> blob?
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                """
                UPDATE node
                SET parent = :parent
                WHERE tree_id = :tree_id AND generation = :generation AND hash = :hash
                """,
                {"tree_id": tree_id, "generation": generation, "hash": node_hash, "parent": parent_hash},
            )

    async def _propagate_update_through_lineage(
        self,
        tree_id: bytes32,
        generation: int,
        parent_hash: bytes32,
        original_child_hash: bytes32,
        new_child_hash: bytes32,
    ) -> bytes32:
        async with self.db_wrapper.writer() as writer:
            # await _debug_dump(db=self.db_wrapper, description="before get lineage")
            lineage = await self.get_lineage(
                node_hash=parent_hash,
                tree_id=tree_id,
                generation=generation,
            )

            if len(lineage) == 0:
                await _debug_dump(db=self.db_wrapper, description="no lineage")
                print(f"{parent_hash=} {tree_id=} {generation=}")
                # TODO: debug for now
                assert False

            update_parameters = []
            parent_parameters = []

            for node in lineage:
                if original_child_hash == node.left_hash:
                    updated_node = replace(
                        node,
                        left_hash=new_child_hash,
                        hash=internal_hash(left_hash=new_child_hash, right_hash=node.right_hash),
                    )
                elif original_child_hash == node.right_hash:
                    updated_node = replace(
                        node,
                        right_hash=new_child_hash,
                        hash=internal_hash(left_hash=node.left_hash, right_hash=new_child_hash),
                    )
                else:
                    # TODO: provide a real error
                    assert False

                update_parameters.append(
                    {
                        "original_hash": node.hash,
                        "tree_id": tree_id,
                        "generation": generation,
                        "new_hash": updated_node.hash,
                        "left": updated_node.left_hash,
                        "right": updated_node.right_hash,
                    },
                )

                for side_hash in [updated_node.left_hash, updated_node.right_hash]:
                    parent_parameters.append(
                        {
                            "tree_id": tree_id,
                            "generation": generation,
                            "hash": side_hash,
                            "parent": updated_node.hash,
                        },
                    )
                    # await self._set_parent(
                    #     tree_id=tree_id,
                    #     generation=generation,
                    #     node_hash=side_hash,
                    #     parent_hash=updated_node.hash,
                    # )

                original_child_hash = node.hash
                new_child_hash = updated_node.hash

                # async with writer.execute(
                #     """
                #     SELECT *
                #     FROM node
                #     WHERE tree_id = :tree_id AND generation = :generation AND hash = :new_hash
                #     LIMIT 1
                #     """,
                #     {
                #         "tree_id": tree_id,
                #         "generation": generation,
                #         "new_hash": new_hash,
                #     },
                # ) as cursor:
                #     [row] = await cursor.fetchone()
                # updated_node = InternalNode.from_row(row=row)

            await writer.executemany(
                """
                UPDATE node
                SET hash = :new_hash, left = :left, right = :right
                WHERE tree_id = :tree_id AND generation = :generation AND hash = :original_hash
                """,
                update_parameters,
            )

            await writer.executemany(
                """
                UPDATE node
                SET parent = :parent
                WHERE tree_id = :tree_id AND generation = :generation AND hash = :hash
                """,
                parent_parameters,
            )

        return updated_node.hash

    async def insert(
        self,
        key: bytes,
        value: bytes,
        tree_id: bytes32,
        reference_node_hash: Optional[bytes32],
        side: Optional[Side],
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
        new_generation: Optional[int] = None,
    ) -> InsertResult:
        async with self.db_wrapper.writer():
            # modify_existing_generation: bool = False,
            if new_generation is None:
                generation = await self._create_new_generation(tree_id=tree_id)
            else:
                generation = new_generation

            # await _debug_dump(db=self.db_wrapper, description="")

            if root is None:
                root = await self.get_tree_root(tree_id=tree_id)

            try:
                await self.get_node_by_key(root=root, key=key)
                raise Exception(f"Key already present: {key.hex()}")
            except KeyNotFoundError:
                pass

            was_empty = root.node_hash is None
            if reference_node_hash is None:
                if not was_empty:
                    raise Exception(f"Reference node hash must be specified for non-empty tree: {tree_id.hex()}")
            else:
                reference_node = await self.get_node(
                    tree_id=tree_id,
                    generation=generation,
                    node_hash=reference_node_hash,
                )
                if isinstance(reference_node, InternalNode):
                    raise Exception("can not insert a new key/value adjacent to an internal node")

            # create new terminal node
            new_terminal_node_hash = await self._insert_terminal_node(
                tree_id=tree_id, generation=generation, parent_hash=None, key=key, value=value
            )

            if was_empty:
                if side is not None:
                    raise Exception("Tree was empty so side must be unspecified, got: {side!r}")

                new_root = await self._insert_root(
                    tree_id=tree_id,
                    node_hash=new_terminal_node_hash,
                    status=status,
                    generation=generation,
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

                new_internal_node_hash = await self._insert_internal_node(
                    tree_id=tree_id,
                    generation=generation,
                    parent_hash=reference_node.parent_hash,
                    left_hash=left,
                    right_hash=right,
                )
                for side_hash in [left, right]:
                    await self._set_parent(
                        tree_id=tree_id,
                        generation=generation,
                        node_hash=side_hash,
                        parent_hash=new_internal_node_hash,
                    )
                # new_internal_node = await self.get_node(
                #     tree_id=tree_id,
                #     generation=generation,
                #     node_hash=new_internal_node_hash,
                # )

                if reference_node.parent_hash is None:
                    new_root_hash = new_internal_node_hash
                else:
                    new_root_hash = await self._propagate_update_through_lineage(
                        tree_id=tree_id,
                        generation=generation,
                        parent_hash=reference_node.parent_hash,
                        original_child_hash=reference_node.hash,
                        new_child_hash=new_internal_node_hash,
                    )

                # ancestors = await self.get_ancestors(
                #     node_hash=reference_node_hash,
                #     tree_id=tree_id,
                #     root_hash=root.node_hash,
                #     generation=generation,
                # )
                # new_root = await self.update_ancestor_hashes_on_insert(
                #     tree_id=tree_id,
                #     left=left,
                #     right=right,
                #     traversal_node_hash=reference_node_hash,
                #     ancestors=ancestors,
                #     status=status,
                #     root=root,
                #     terminal_hash=new_terminal_node_hash,
                #     new_generation=generation,
                # )

                new_root = await self._insert_root(
                    tree_id=tree_id,
                    node_hash=new_root_hash,
                    status=status,
                    generation=generation,
                )

            return InsertResult(node_hash=new_terminal_node_hash, root=new_root)

    async def delete(
        self,
        key: bytes,
        tree_id: bytes32,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
        new_generation: Optional[int] = None,
    ) -> Optional[Root]:
        async with self.db_wrapper.writer() as writer:
            if root is None:
                if new_generation is None:
                    generation = await self._create_new_generation(tree_id=tree_id)
                else:
                    generation = new_generation
                root = await self.get_tree_root(tree_id=tree_id, generation=generation)

            try:
                node = await self.get_node_by_key(root=root, key=key)
                node_hash = node.hash
                assert isinstance(node, TerminalNode)
            except KeyNotFoundError:
                log.debug(f"Request to delete an unknown key ignored: {key.hex()}")
                return root

            await writer.execute(
                """
                    DELETE
                    FROM node
                    WHERE tree_id = :tree_id AND generation = :generation AND hash = :hash
                    """,
                {"tree_id": tree_id, "generation": generation, "hash": node.hash},
            )

            if node.parent_hash is None:
                return await self._insert_root(tree_id=tree_id, generation=generation, node_hash=None, status=status)

            parent = await self.get_node(tree_id=tree_id, generation=generation, node_hash=node.parent_hash)
            await writer.execute(
                """
                    DELETE
                    FROM node
                    WHERE tree_id = :tree_id AND generation = :generation AND hash = :hash
                    """,
                {"tree_id": tree_id, "generation": generation, "hash": parent.hash},
            )

            other_child_hash = parent.other_child_hash(hash=node.hash)
            if parent.parent_hash is None:
                await self._set_parent(
                    tree_id=tree_id,
                    generation=generation,
                    node_hash=other_child_hash,
                    parent_hash=None,
                )
            else:
                await self._propagate_update_through_lineage(
                    tree_id=tree_id,
                    generation=generation,
                    parent_hash=parent.parent_hash,
                    original_child_hash=parent.hash,
                    new_child_hash=other_child_hash,
                )

        return await self._insert_root(tree_id=tree_id, generation=generation, node_hash=None, status=status)

    async def upsert(
        self,
        key: bytes,
        new_value: bytes,
        tree_id: bytes32,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
        new_generation: Optional[int] = None,
    ) -> InsertResult:
        async with self.db_wrapper.writer() as writer:
            if root is None:
                root = await self.get_tree_root(tree_id=tree_id)

            try:
                old_node = await self.get_node_by_key(root=root, key=key)
            except KeyNotFoundError:
                log.debug(f"Key not found: {key.hex()}. Doing an autoinsert instead")
                return await self.autoinsert(
                    key=key,
                    value=new_value,
                    tree_id=tree_id,
                    status=status,
                    root=root,
                    new_generation=new_generation,
                )
            if old_node.value == new_value:
                log.debug(f"New value matches old value in upsert operation: {key.hex()}. Ignoring upsert")
                return InsertResult(leaf_hash(key, new_value), root)

            if new_generation is None:
                generation = await self._create_new_generation(tree_id=tree_id)
            else:
                generation = new_generation

            await writer.execute(
                """
                DELETE
                FROM node
                WHERE tree_id = :tree_id AND generation = :generation AND hash = :hash
                """,
                {"tree_id": tree_id, "generation": generation, "hash": old_node.hash},
            )
            # create new terminal node
            new_terminal_node_hash = await self._insert_terminal_node(
                tree_id=tree_id,
                generation=generation,
                parent_hash=None,
                key=key,
                value=new_value,
            )

            if old_node.parent_hash is None:
                new_root_hash = new_terminal_node_hash
            else:
                new_root_hash = await self._propagate_update_through_lineage(
                    tree_id=tree_id,
                    generation=generation,
                    parent_hash=old_node.parent_hash,
                    original_child_hash=old_node.hash,
                    new_child_hash=new_terminal_node_hash,
                )

            new_root = await self._insert_root(
                tree_id=tree_id,
                node_hash=new_root_hash,
                status=status,
                generation=generation,
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

    async def insert_batch(
        self,
        tree_id: bytes32,
        changelist: List[Dict[str, Any]],
        status: Status = Status.PENDING,
    ) -> Optional[bytes32]:
        async with self.db_wrapper.writer() as writer:
            old_root = await self.get_tree_root(tree_id)
            pending_root = await self.get_pending_root(tree_id=tree_id)
            if pending_root is None:
                latest_local_root: Optional[Root] = old_root
            else:
                if pending_root.status == Status.PENDING_BATCH:
                    # We have an unfinished batch, continue the current batch on top of it.
                    if pending_root.generation != old_root.generation + 1:
                        raise Exception("Internal error")
                    await self.change_root_status(pending_root, Status.COMMITTED)
                    await self.build_ancestor_table_for_latest_root(tree_id=tree_id)
                    latest_local_root = pending_root
                else:
                    raise Exception("Internal error")

            assert latest_local_root is not None

            new_generation = await self._create_new_generation(tree_id=tree_id)

            for index, change in enumerate(changelist):
                print(f"{index=} {change=}")
                if change["action"] == "insert":
                    key = change["key"]
                    value = change["value"]
                    reference_node_hash = change.get("reference_node_hash", None)
                    side = change.get("side", None)
                    if reference_node_hash is None and side is None:
                        insert_result = await self.autoinsert(
                            key=key,
                            value=value,
                            tree_id=tree_id,
                            status=status,
                            root=latest_local_root,
                            new_generation=new_generation,
                        )
                        latest_local_root = insert_result.root
                    else:
                        # TODO: delete redundant (?) check?
                        if reference_node_hash is None or side is None:
                            raise Exception("Provide both reference_node_hash and side or neither.")
                        insert_result = await self.insert(
                            key=key,
                            value=value,
                            tree_id=tree_id,
                            reference_node_hash=reference_node_hash,
                            side=side,
                            status=status,
                            root=latest_local_root,
                            new_generation=new_generation,
                        )
                        latest_local_root = insert_result.root
                elif change["action"] == "delete":
                    key = change["key"]
                    latest_local_root = await self.delete(
                        key=key,
                        tree_id=tree_id,
                        status=status,
                        root=latest_local_root,
                        new_generation=new_generation,
                    )
                elif change["action"] == "upsert":
                    key = change["key"]
                    new_value = change["value"]
                    insert_result = await self.upsert(
                        key=key,
                        new_value=new_value,
                        tree_id=tree_id,
                        status=status,
                        root=latest_local_root,
                        new_generation=new_generation,
                    )
                    latest_local_root = insert_result.root
                else:
                    raise Exception(f"Operation in batch is not insert or delete: {change}")

            await _debug_dump(db=self.db_wrapper)
            cursor = await writer.execute(
                """
                SELECT hash
                FROM node
                WHERE tree_id = :tree_id AND generation = :generation AND parent IS NULL
                LIMIT 1
                """,
                {"tree_id": tree_id, "generation": new_generation},
            )
            maybe_row = await cursor.fetchone()

            if maybe_row is None:
                new_root_hash = None
            else:
                new_root_hash = maybe_row["hash"]

            root = await self._insert_root(
                tree_id=tree_id,
                node_hash=new_root_hash,
                status=Status.COMMITTED,  # status,
                generation=new_generation,
            )

            await _debug_dump(db=self.db_wrapper)
            if root.node_hash == old_root.node_hash:
                # if len(changelist) != 0:
                #     await self.rollback_to_generation(tree_id, old_root.generation)
                raise ValueError("Changelist resulted in no change to tree data")
            # await self.root
            # async with writer.execute(
            #     """
            #     UPDATE root
            #     SET status = :status
            #     WHERE
            #     """,
            #     {},
            # )
            if status in (Status.PENDING, Status.PENDING_BATCH):
                new_root = await self.get_pending_root(tree_id=tree_id)
                assert new_root is not None
            elif status == Status.COMMITTED:
                new_root = await self.get_tree_root(tree_id=tree_id)
            else:
                raise Exception(f"No known status: {status}")
            if new_root.node_hash != root.node_hash:
                await _debug_dump(db=self.db_wrapper)
                import sys

                sys.stdout.flush()
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
                SELECT *
                FROM node
                WHERE (
                    tree_id = :tree_id
                    AND generation = :generation
                    AND (
                        left = :node_hash
                        OR right = :node_hash
                    )
                )
                LIMIT 1
                """,
                {"tree_id": tree_id, "generation": generation, "node_hash": node_hash},
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
                known_hashes: Set[bytes32] = {node.hash for node in previous_internal_nodes}
            else:
                known_hashes = set()
            internal_nodes: List[InternalNode] = await self.get_internal_nodes(
                tree_id=tree_id,
                root_hash=root.node_hash,
            )

    async def insert_root_with_ancestor_table(
        self, tree_id: bytes32, node_hash: Optional[bytes32], status: Status = Status.PENDING
    ) -> None:
        async with self.db_wrapper.writer():
            await self._insert_root(tree_id=tree_id, node_hash=node_hash, status=status)
            # Don't update the ancestor table for non-committed status.
            if status == Status.COMMITTED:
                await self.build_ancestor_table_for_latest_root(tree_id=tree_id)

    # async def get_node_by_key_latest_generation(self, key: bytes, tree_id: bytes32) -> TerminalNode:
    #     async with self.db_wrapper.reader() as reader:
    #         root = await self.get_tree_root(tree_id=tree_id)
    #         if root.node_hash is None:
    #             raise KeyNotFoundError(key=key)
    #
    #         # await _debug_dump(
    #         #     db=self.db_wrapper,
    #         #     description=f"get_node_by_key_latest_generation() {tree_id.hex()=} {root.generation=} {key=}",
    #         # )
    #         async with reader.execute(
    #             """
    #             SELECT *
    #             FROM node
    #             WHERE tree_id = :tree_id AND generation = :generation AND key = :key
    #             LIMIT 1
    #             """,
    #             {"tree_id": tree_id, "generation": root.generation, "key": key},
    #         ) as cursor:
    #             row = await cursor.fetchone()
    #             if row is None:
    #                 raise KeyNotFoundError(key=key)
    #
    #         return TerminalNode.from_row(row=row)

    async def get_node_by_key(
        self,
        root: Root,
        key: bytes,
    ) -> TerminalNode:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                """
                SELECT *
                FROM node
                WHERE tree_id = :tree_id AND generation = :generation AND key = :key
                LIMIT 1
                """,
                {"tree_id": root.tree_id, "generation": root.generation, "key": key},
            )
            row = await cursor.fetchone()
            if row is None:
                raise KeyNotFoundError(key=key)

        return TerminalNode.from_row(row=row)

    async def get_node(self, tree_id: bytes32, generation: int, node_hash: bytes32) -> Node:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                """
                SELECT *
                FROM node
                WHERE tree_id = :tree_id AND generation = :generation AND hash = :hash
                LIMIT 1
                """,
                {"tree_id": tree_id, "generation": generation, "hash": node_hash},
            )
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
            root_node = await self.get_node(node_hash=root.node_hash, tree_id=tree_id, generation=root.generation)

            cursor = await reader.execute(
                """
                WITH RECURSIVE
                    tree_from_root_hash(tree_id, generation, hash, parent, node_type, left, right, key, value) AS (
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
                old_urls = {server_info.url for server_info in old_subscription.servers_info}
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

    async def delete_store_data(self, tree_id: bytes32) -> None:
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
                    "tree_id": tree_id,
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

            await writer.execute("DELETE FROM ancestors WHERE tree_id == ?", (tree_id,))
            await writer.execute("DELETE FROM root WHERE tree_id == ?", (tree_id,))
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

    async def unsubscribe(self, tree_id: bytes32) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "DELETE FROM subscriptions WHERE tree_id == :tree_id",
                {"tree_id": tree_id},
            )

    async def rollback_to_generation(self, tree_id: bytes32, target_generation: int) -> None:
        async with self.db_wrapper.writer() as writer:
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

    async def server_misses_file(self, tree_id: bytes32, server_info: ServerInfo, timestamp: int) -> ServerInfo:
        # Max banned time is 1 hour.
        BAN_TIME_BY_MISSING_COUNT = [5 * 60] * 3 + [15 * 60] * 3 + [30 * 60] * 2 + [60 * 60]
        index = min(server_info.num_consecutive_failures, len(BAN_TIME_BY_MISSING_COUNT) - 1)
        new_server_info = replace(
            server_info,
            num_consecutive_failures=server_info.num_consecutive_failures + 1,
            ignore_till=max(server_info.ignore_till, timestamp + BAN_TIME_BY_MISSING_COUNT[index]),
        )
        await self.update_server_info(tree_id, new_server_info)
        return new_server_info

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
