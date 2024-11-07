from __future__ import annotations

import contextlib
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, BinaryIO, Callable, Optional, Union

import aiosqlite

from chia.data_layer.data_layer_errors import KeyNotFoundError, TreeGenerationIncrementingError
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
    Root,
    SerializedNode,
    ServerInfo,
    Side,
    Status,
    Subscription,
    TerminalNode,
    Unspecified,
    get_delta_filename_path,
    get_hashes_for_page,
    internal_hash,
    key_hash,
    leaf_hash,
    row_to_node,
    unspecified,
)
from chia.data_layer.util.merkle_blob import KVId, MerkleBlob, NodeMetadata
from chia.data_layer.util.merkle_blob import NodeType as NodeTypeMerkleBlob
from chia.data_layer.util.merkle_blob import (
    RawInternalMerkleNode,
    RawLeafMerkleNode,
    TreeIndex,
    null_parent,
    pack_raw_node,
    undefined_index,
)
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
                await writer.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS root(
                        tree_id BLOB NOT NULL CHECK(length(tree_id) == 32),
                        generation INTEGER NOT NULL CHECK(generation >= 0),
                        node_hash BLOB,
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
                    CREATE TABLE IF NOT EXISTS merkleblob(
                        hash BLOB,
                        blob BLOB,
                        store_id BLOB NOT NULL CHECK(length(store_id) == 32),
                        PRIMARY KEY(store_id, hash)
                    )
                    """
                )
                await writer.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ids(
                        kv_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        blob BLOB,
                        store_id BLOB NOT NULL CHECK(length(store_id) == 32)
                    )
                    """
                )
                await writer.execute(
                    """
                    CREATE TABLE IF NOT EXISTS hashes(
                        hash BLOB,
                        kid INTEGER,
                        vid INTEGER,
                        store_id BLOB NOT NULL CHECK(length(store_id) == 32),
                        PRIMARY KEY(store_id, hash),
                        FOREIGN KEY (kid) REFERENCES ids(kv_id),
                        FOREIGN KEY (vid) REFERENCES ids(kv_id)
                    )
                    """
                )
                await writer.execute(
                    """
                    CREATE TABLE IF NOT EXISTS nodes(
                        store_id BLOB NOT NULL CHECK(length(store_id) == 32),
                        hash BLOB NOT NULL,
                        root_hash BLOB NOT NULL,
                        generation INTEGER NOT NULL CHECK(generation >= 0),
                        idx INTEGER NOT NULL,
                        PRIMARY KEY(store_id, hash)
                    )
                    """
                )
                await writer.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_ids ON ids(blob)
                    """
                )
                await writer.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx2_ids ON ids(store_id)
                    """
                )

            yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self.db_wrapper.writer():
            yield

    async def insert_into_data_store_from_file(
        self,
        store_id: bytes32,
        root_hash: Optional[bytes32],
        filename: Path,
    ) -> None:
        internal_nodes: dict[bytes32, tuple[bytes32, bytes32]] = {}
        terminal_nodes: dict[bytes32, tuple[KVId, KVId]] = {}

        with open(filename, "rb") as reader:
            while True:
                chunk = b""
                while len(chunk) < 4:
                    size_to_read = 4 - len(chunk)
                    cur_chunk = reader.read(size_to_read)
                    if cur_chunk is None or cur_chunk == b"":
                        if size_to_read < 4:
                            raise Exception("Incomplete read of length.")
                        break
                    chunk += cur_chunk
                if chunk == b"":
                    break

                size = int.from_bytes(chunk, byteorder="big")
                serialize_nodes_bytes = b""
                while len(serialize_nodes_bytes) < size:
                    size_to_read = size - len(serialize_nodes_bytes)
                    cur_chunk = reader.read(size_to_read)
                    if cur_chunk is None or cur_chunk == b"":
                        raise Exception("Incomplete read of blob.")
                    serialize_nodes_bytes += cur_chunk
                serialized_node = SerializedNode.from_bytes(serialize_nodes_bytes)

                node_type = NodeType.TERMINAL if serialized_node.is_terminal else NodeType.INTERNAL
                if node_type == NodeType.INTERNAL:
                    node_hash = internal_hash(bytes32(serialized_node.value1), bytes32(serialized_node.value2))
                    internal_nodes[node_hash] = (bytes32(serialized_node.value1), bytes32(serialized_node.value2))
                else:
                    kid, vid = await self.add_key_value(serialized_node.value1, serialized_node.value2, store_id)
                    node_hash = leaf_hash(serialized_node.value1, serialized_node.value2)
                    terminal_nodes[node_hash] = (kid, vid)

        merkle_blob = MerkleBlob(blob=bytearray())
        if root_hash is not None:
            await self.build_blob_from_nodes(internal_nodes, terminal_nodes, root_hash, merkle_blob)

        await self.insert_root_from_merkle_blob(merkle_blob, store_id, Status.COMMITTED)
        await self.add_node_hashes(store_id)

    async def migrate_db(self, server_files_location: Path) -> None:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT * FROM schema")
            rows = await cursor.fetchall()
            all_versions = {"v1.0", "v2.0"}

            for row in rows:
                version = row["version_id"]
                if version not in all_versions:
                    raise Exception("Unknown version")
                if version == "v2.0":
                    log.info(f"Found DB schema version {version}. No migration needed.")
                    return

        version = "v2.0"
        old_tables = ["node", "root", "ancestors"]
        all_stores = await self.get_store_ids()
        all_roots: list[list[Root]] = []
        for store_id in all_stores:
            try:
                root = await self.get_tree_root(store_id=store_id)
                roots = await self.get_roots_between(store_id, 1, root.generation)
                all_roots.append(roots + [root])
            except Exception as e:
                if "unable to find root for id, generation" in str(e):
                    log.error(f"Cannot find roots for {store_id}. Skipping it.")

        log.info(f"Initiating migration to version {version}. Found {len(all_roots)} stores to migrate")

        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                f"""
                CREATE TABLE IF NOT EXISTS new_root(
                    tree_id BLOB NOT NULL CHECK(length(tree_id) == 32),
                    generation INTEGER NOT NULL CHECK(generation >= 0),
                    node_hash BLOB,
                    status INTEGER NOT NULL CHECK(
                        {" OR ".join(f"status == {status}" for status in Status)}
                    ),
                    PRIMARY KEY(tree_id, generation)
                )
                """
            )
            for old_table in old_tables:
                await writer.execute(f"DROP TABLE IF EXISTS {old_table}")
            await writer.execute("ALTER TABLE new_root RENAME TO root")
            await writer.execute("INSERT INTO schema (version_id) VALUES (?)", (version,))
            log.info(f"Initialized new DB schema {version}.")

            for roots in all_roots:
                assert len(roots) > 0
                store_id = roots[0].store_id
                await self.create_tree(store_id=store_id, status=Status.COMMITTED)

                for root in roots:
                    recovery_filename: Optional[Path] = None

                    for group_by_store in (True, False):
                        filename = get_delta_filename_path(
                            server_files_location,
                            store_id,
                            bytes32([0] * 32) if root.node_hash is None else root.node_hash,
                            root.generation,
                            group_by_store,
                        )

                        if filename.exists():
                            log.info(f"Found filename {filename}. Recovering data from it")
                            recovery_filename = filename
                            break

                    if recovery_filename is None:
                        log.error(f"Cannot find any recovery file for root {root}")
                        break

                    try:
                        await self.insert_into_data_store_from_file(store_id, root.node_hash, recovery_filename)
                    except Exception as e:
                        log.error(f"Cannot recover data from {filename}: {e}")
                        break

    async def get_merkle_blob(self, root_hash: Optional[bytes32]) -> MerkleBlob:
        if root_hash is None:
            return MerkleBlob(blob=bytearray())

        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT blob FROM merkleblob WHERE hash == :root_hash",
                {
                    "root_hash": root_hash,
                },
            )

            row = await cursor.fetchone()

            if row is None:
                raise Exception(f"Cannot find merkle blob for root hash {root_hash.hex()}")

            merkle_blob = MerkleBlob(blob=bytearray(row["blob"]))
            return merkle_blob

    async def insert_root_from_merkle_blob(
        self,
        merkle_blob: MerkleBlob,
        store_id: bytes32,
        status: Status,
        old_root: Optional[Root] = None,
    ) -> Root:
        if not merkle_blob.empty():
            merkle_blob.calculate_lazy_hashes()

        root_hash = merkle_blob.get_root_hash()
        if old_root is not None and old_root.node_hash == root_hash:
            raise ValueError("Changelist resulted in no change to tree data")

        if root_hash is not None:
            async with self.db_wrapper.writer() as writer:
                await writer.execute(
                    """
                    INSERT OR REPLACE INTO merkleblob (hash, blob, store_id)
                    VALUES (?, ?, ?)
                    """,
                    (root_hash, merkle_blob.blob, store_id),
                )

        return await self._insert_root(store_id, root_hash, status)

    async def get_kvid(self, blob: bytes, store_id: bytes32) -> Optional[KVId]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT kv_id FROM ids WHERE blob = ? AND store_id = ?", (blob,store_id,))
            row = await cursor.fetchone()

            if row is None:
                return None

            return KVId(row[0])

    async def get_blob_from_kvid(self, kv_id: KVId, store_id: bytes32) -> Optional[bytes]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT blob FROM ids WHERE kv_id = ? AND store_id = ?", (kv_id,store_id,))
            row = await cursor.fetchone()

            if row is None:
                return None

            return bytes(row[0])

    async def get_terminal_node(self, kid: KVId, vid: KVId, store_id: bytes32) -> TerminalNode:
        key = await self.get_blob_from_kvid(kid, store_id)
        value = await self.get_blob_from_kvid(vid, store_id)
        if key is None or value is None:
            raise Exception("Cannot find the key/value pair")

        return TerminalNode(hash=leaf_hash(key, value), key=key, value=value)

    async def add_kvid(self, blob: bytes, store_id: bytes32) -> KVId:
        kv_id = await self.get_kvid(blob, store_id)
        if kv_id is not None:
            return kv_id

        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "INSERT INTO ids (blob, store_id) VALUES (?, ?)",
                (
                    blob,
                    store_id,
                ),
            )

        kv_id = await self.get_kvid(blob, store_id)
        if kv_id is None:
            raise Exception("Internal error")
        return kv_id

    async def add_key_value(self, key: bytes, value: bytes, store_id: bytes32) -> tuple[KVId, KVId]:
        kid = await self.add_kvid(key, store_id)
        vid = await self.add_kvid(value, store_id)
        hash = leaf_hash(key, value)
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "INSERT OR REPLACE INTO hashes (hash, kid, vid, store_id) VALUES (?, ?, ?, ?)",
                (
                    hash,
                    kid,
                    vid,
                    store_id,
                ),
            )
        return (kid, vid)

    async def get_node_by_hash(self, hash: bytes32, store_id: bytes32) -> tuple[KVId, KVId]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT * FROM hashes WHERE hash = ? AND store_id = ?", (hash,store_id,))

            row = await cursor.fetchone()

            if row is None:
                raise Exception(f"Cannot find node by hash {hash.hex()}")

            kid = KVId(row["kid"])
            vid = KVId(row["vid"])
            return (kid, vid)

    async def get_terminal_node_by_hash(self, node_hash: bytes32, store_id: bytes32) -> TerminalNode:
        kid, vid = await self.get_node_by_hash(node_hash, store_id)
        return await self.get_terminal_node(kid, vid, store_id)

    async def get_first_generation(self, node_hash: bytes32, store_id: bytes32) -> Optional[int]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT generation FROM nodes WHERE hash = ? AND store_id = ?",
                (
                    node_hash,
                    store_id,
                ),
            )

            row = await cursor.fetchone()
            if row is None:
                return None

            return int(row[0])

    async def add_node_hash(
        self, store_id: bytes32, hash: bytes32, root_hash: bytes32, generation: int, index: int
    ) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                """
                INSERT INTO nodes(store_id, hash, root_hash, generation, idx)
                VALUES (?, ?, ?, ?, ?)
                """,
                (store_id, hash, root_hash, generation, index),
            )

    async def add_node_hashes(self, store_id: bytes32) -> None:
        root = await self.get_tree_root(store_id=store_id)
        if root.node_hash is None:
            return

        merkle_blob = await self.get_merkle_blob(root_hash=root.node_hash)
        hash_to_index = merkle_blob.get_hashes_indexes()
        for hash, index in hash_to_index.items():
            existing_generation = await self.get_first_generation(hash, store_id)
            if existing_generation is None:
                await self.add_node_hash(store_id, hash, root.node_hash, root.generation, index)

    async def build_blob_from_nodes(
        self,
        internal_nodes: dict[bytes32, tuple[bytes32, bytes32]],
        terminal_nodes: dict[bytes32, tuple[KVId, KVId]],
        node_hash: bytes32,
        merkle_blob: MerkleBlob,
    ) -> TreeIndex:
        if node_hash not in terminal_nodes and node_hash not in internal_nodes:
            async with self.db_wrapper.reader() as reader:
                cursor = await reader.execute("SELECT root_hash, idx FROM nodes WHERE hash = ?", (node_hash,))

                row = await cursor.fetchone()
                if row is None:
                    raise Exception(f"Unknown hash {node_hash}")

                root_hash = row["root_hash"]
                index = row["idx"]

            other_merkle_blob = await self.get_merkle_blob(root_hash)
            nodes = other_merkle_blob.get_nodes_with_indexes(index=index)
            index_to_hash = {index: bytes32(node.hash) for index, node in nodes}
            for _, node in nodes:
                if isinstance(node, RawLeafMerkleNode):
                    terminal_nodes[bytes32(node.hash)] = (node.key, node.value)
                elif isinstance(node, RawInternalMerkleNode):
                    internal_nodes[bytes32(node.hash)] = (index_to_hash[node.left], index_to_hash[node.right])

        index = merkle_blob.get_new_index()
        if node_hash in terminal_nodes:
            kid, vid = terminal_nodes[node_hash]
            merkle_blob.insert_entry_to_blob(
                index,
                NodeMetadata(type=NodeTypeMerkleBlob.leaf, dirty=False).pack()
                + pack_raw_node(RawLeafMerkleNode(node_hash, null_parent, kid, vid)),
            )
        elif node_hash in internal_nodes:
            merkle_blob.insert_entry_to_blob(
                index,
                NodeMetadata(type=NodeTypeMerkleBlob.internal, dirty=False).pack()
                + pack_raw_node(
                    RawInternalMerkleNode(
                        node_hash,
                        null_parent,
                        undefined_index,
                        undefined_index,
                    )
                ),
            )
            left_hash, right_hash = internal_nodes[node_hash]
            left_index = await self.build_blob_from_nodes(internal_nodes, terminal_nodes, left_hash, merkle_blob)
            right_index = await self.build_blob_from_nodes(internal_nodes, terminal_nodes, right_hash, merkle_blob)
            for child_index in (left_index, right_index):
                merkle_blob.update_entry(index=child_index, parent=index)
            merkle_blob.update_entry(index=index, left=left_index, right=right_index)

        return TreeIndex(index)

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
            return new_root

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
            if root.node_hash is not None and status == Status.COMMITTED:
                await self.add_node_hashes(root.store_id)

    async def check(self) -> None:
        for check in self._checks:
            # pylint seems to think these are bound methods not unbound methods.
            await check(self)  # pylint: disable=too-many-function-args

    async def _check_roots_are_incrementing(self) -> None:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute("SELECT * FROM root ORDER BY tree_id, generation")
            roots = [Root.from_row(row=row) async for row in cursor]

            roots_by_tree: dict[bytes32, list[Root]] = defaultdict(list)
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

    _checks: tuple[Callable[[DataStore], Awaitable[None]], ...] = (_check_roots_are_incrementing,)

    async def create_tree(self, store_id: bytes32, status: Status = Status.PENDING) -> bool:
        await self._insert_root(store_id=store_id, node_hash=None, status=status)

        return True

    async def table_is_empty(self, store_id: bytes32) -> bool:
        tree_root = await self.get_tree_root(store_id=store_id)

        return tree_root.node_hash is None

    async def get_store_ids(self) -> set[bytes32]:
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

    async def get_all_pending_batches_roots(self) -> list[Root]:
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

    async def get_roots_between(self, store_id: bytes32, generation_begin: int, generation_end: int) -> list[Root]:
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
        generation: Optional[int] = None,
    ) -> list[InternalNode]:
        async with self.db_wrapper.reader():
            if root_hash is None:
                root = await self.get_tree_root(store_id=store_id, generation=generation)
                root_hash = root.node_hash
            if root_hash is None:
                raise Exception(f"Root hash is unspecified for store ID: {store_id.hex()}")

            merkle_blob = await self.get_merkle_blob(root_hash=root_hash)
            reference_kid, _ = await self.get_node_by_hash(node_hash, store_id)

        return merkle_blob.get_lineage_by_key_id(reference_kid)

    async def get_internal_nodes(self, store_id: bytes32, root_hash: Optional[bytes32] = None) -> list[InternalNode]:
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

            internal_nodes: list[InternalNode] = []
            async for row in cursor:
                node = row_to_node(row=row)
                if not isinstance(node, InternalNode):
                    raise Exception(f"Unexpected internal node found: {node.hash.hex()}")
                internal_nodes.append(node)

        return internal_nodes

    async def get_keys_values(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> list[TerminalNode]:
        async with self.db_wrapper.reader():
            resolved_root_hash: Optional[bytes32]
            if root_hash is unspecified:
                root = await self.get_tree_root(store_id=store_id)
                resolved_root_hash = root.node_hash
            else:
                resolved_root_hash = root_hash

            try:
                merkle_blob = await self.get_merkle_blob(root_hash=resolved_root_hash)
            except Exception as e:
                if str(e).startswith("Cannot find merkle blob for root hash"):
                    return []
                raise

            kv_ids = merkle_blob.get_keys_values()

            terminal_nodes: list[TerminalNode] = []
            for kid, vid in kv_ids.items():
                terminal_node = await self.get_terminal_node(kid, vid, store_id)
                terminal_nodes.append(terminal_node)

        return terminal_nodes

    async def get_keys_values_compressed(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> KeysValuesCompressed:
        async with self.db_wrapper.reader():
            resolved_root_hash: Optional[bytes32]
            if root_hash is unspecified:
                root = await self.get_tree_root(store_id=store_id)
                resolved_root_hash = root.node_hash
            else:
                resolved_root_hash = root_hash

            keys_values_hashed: dict[bytes32, bytes32] = {}
            key_hash_to_length: dict[bytes32, int] = {}
            leaf_hash_to_length: dict[bytes32, int] = {}
            if resolved_root_hash is not None:
                try:
                    merkle_blob = await self.get_merkle_blob(root_hash=resolved_root_hash)
                except Exception as e:
                    if str(e).startswith("Cannot find merkle blob for root hash"):
                        return KeysValuesCompressed({}, {}, {}, resolved_root_hash)
                    raise
                kv_ids = merkle_blob.get_keys_values()
                for kid, vid in kv_ids.items():
                    node = await self.get_terminal_node(kid, vid, store_id)

                    keys_values_hashed[key_hash(node.key)] = leaf_hash(node.key, node.value)
                    key_hash_to_length[key_hash(node.key)] = len(node.key)
                    leaf_hash_to_length[leaf_hash(node.key, node.value)] = len(node.key) + len(node.value)

            return KeysValuesCompressed(keys_values_hashed, key_hash_to_length, leaf_hash_to_length, resolved_root_hash)

    async def get_keys_paginated(
        self,
        store_id: bytes32,
        page: int,
        max_page_size: int,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> KeysPaginationData:
        keys_values_compressed = await self.get_keys_values_compressed(store_id, root_hash)
        pagination_data = get_hashes_for_page(page, keys_values_compressed.key_hash_to_length, max_page_size)

        keys: list[bytes] = []
        for hash in pagination_data.hashes:
            leaf_hash = keys_values_compressed.keys_values_hashed[hash]
            node = await self.get_terminal_node_by_hash(leaf_hash, store_id)
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

        keys_values: list[TerminalNode] = []
        for hash in pagination_data.hashes:
            node = await self.get_terminal_node_by_hash(hash, store_id)
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
        if len(old_pairs.keys_values_hashed) == 0 and hash1 != bytes32.zeros:
            raise Exception(f"Unable to diff: Can't find keys and values for {hash1}")

        new_pairs = await self.get_keys_values_compressed(store_id, hash2)
        if len(new_pairs.keys_values_hashed) == 0 and hash2 != bytes32.zeros:
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
        kv_diff: list[DiffData] = []

        for hash in pagination_data.hashes:
            node = await self.get_terminal_node_by_hash(hash, store_id)
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

    async def autoinsert(
        self,
        key: bytes,
        value: bytes,
        store_id: bytes32,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
    ) -> InsertResult:
        return await self.insert(
            key=key,
            value=value,
            store_id=store_id,
            reference_node_hash=None,
            side=None,
            status=status,
            root=root,
        )

    async def get_keys_values_dict(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> dict[bytes, bytes]:
        pairs = await self.get_keys_values(store_id=store_id, root_hash=root_hash)
        return {node.key: node.value for node in pairs}

    async def get_keys(
        self,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> list[bytes]:
        async with self.db_wrapper.reader():
            if root_hash is unspecified:
                root = await self.get_tree_root(store_id=store_id)
                resolved_root_hash = root.node_hash
            else:
                resolved_root_hash = root_hash

            try:
                merkle_blob = await self.get_merkle_blob(root_hash=resolved_root_hash)
            except Exception as e:
                if str(e).startswith("Cannot find merkle blob for root hash"):
                    return []
                raise

            kv_ids = merkle_blob.get_keys_values()
            keys: list[bytes] = []
            for kid in kv_ids.keys():
                key = await self.get_blob_from_kvid(kid, store_id)
                if key is None:
                    raise Exception(f"Unknown key corresponding to KVId: {kid}")
                keys.append(key)

        return keys

    def get_reference_kid_side(self, merkle_blob: MerkleBlob, key: bytes, value: bytes) -> tuple[KVId, Side]:
        seed = leaf_hash(key=key, value=value)
        side_seed = bytes(seed)[0]
        side = Side.LEFT if side_seed < 128 else Side.RIGHT
        reference_node = merkle_blob.get_random_leaf_node(seed)
        kid = reference_node.key
        return (kid, side)

    async def insert(
        self,
        key: bytes,
        value: bytes,
        store_id: bytes32,
        reference_node_hash: Optional[bytes32] = None,
        side: Optional[Side] = None,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
    ) -> InsertResult:
        async with self.db_wrapper.writer():
            if root is None:
                root = await self.get_tree_root(store_id=store_id)
            merkle_blob = await self.get_merkle_blob(root_hash=root.node_hash)

            kid, vid = await self.add_key_value(key, value, store_id)
            hash = leaf_hash(key, value)
            reference_kid = None
            if reference_node_hash is not None:
                reference_kid, _ = await self.get_node_by_hash(reference_node_hash, store_id)

            was_empty = root.node_hash is None
            if not was_empty and reference_kid is None:
                if side is not None:
                    raise Exception("Side specified without reference node hash")
                reference_kid, side = self.get_reference_kid_side(merkle_blob, key, value)

            try:
                merkle_blob.insert(kid, vid, hash, reference_kid, side)
            except Exception as e:
                if str(e) == "Key already present":
                    raise Exception(f"Key already present: {key.hex()}")
                raise

            new_root = await self.insert_root_from_merkle_blob(merkle_blob, store_id, status)
            return InsertResult(node_hash=hash, root=new_root)

    async def delete(
        self,
        key: bytes,
        store_id: bytes32,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
    ) -> Optional[Root]:
        async with self.db_wrapper.writer():
            if root is None:
                root = await self.get_tree_root(store_id=store_id)
            merkle_blob = await self.get_merkle_blob(root_hash=root.node_hash)

            kid = await self.get_kvid(key, store_id)
            if kid is not None:
                merkle_blob.delete(kid)

            new_root = await self.insert_root_from_merkle_blob(merkle_blob, store_id, status)

        return new_root

    async def upsert(
        self,
        key: bytes,
        new_value: bytes,
        store_id: bytes32,
        status: Status = Status.PENDING,
        root: Optional[Root] = None,
    ) -> InsertResult:
        async with self.db_wrapper.writer():
            if root is None:
                root = await self.get_tree_root(store_id=store_id)
            merkle_blob = await self.get_merkle_blob(root_hash=root.node_hash)

            kid, vid = await self.add_key_value(key, new_value, store_id)
            hash = leaf_hash(key, new_value)
            merkle_blob.upsert(kid, vid, hash)

            new_root = await self.insert_root_from_merkle_blob(merkle_blob, store_id, status)
            return InsertResult(node_hash=hash, root=new_root)

    async def insert_batch(
        self,
        store_id: bytes32,
        changelist: list[dict[str, Any]],
        status: Status = Status.PENDING,
        enable_batch_autoinsert: bool = True,
    ) -> Optional[bytes32]:
        async with self.transaction():
            old_root = await self.get_tree_root(store_id=store_id)
            pending_root = await self.get_pending_root(store_id=store_id)
            if pending_root is not None:
                if pending_root.status == Status.PENDING_BATCH:
                    # We have an unfinished batch, continue the current batch on top of it.
                    if pending_root.generation != old_root.generation + 1:
                        raise Exception("Internal error")
                    old_root = pending_root
                    await self.clear_pending_roots(store_id)
                else:
                    raise Exception("Internal error")

            merkle_blob = await self.get_merkle_blob(root_hash=old_root.node_hash)

            key_hash_frequency: dict[bytes32, int] = {}
            first_action: dict[bytes32, str] = {}
            last_action: dict[bytes32, str] = {}

            for change in changelist:
                key = change["key"]
                hash = key_hash(key)
                key_hash_frequency[hash] = key_hash_frequency.get(hash, 0) + 1
                if hash not in first_action:
                    first_action[hash] = change["action"]
                last_action[hash] = change["action"]

            batch_keys_values: list[tuple[KVId, KVId]] = []
            batch_hashes: list[bytes] = []

            for change in changelist:
                if change["action"] == "insert":
                    key = change["key"]
                    value = change["value"]

                    reference_node_hash = change.get("reference_node_hash", None)
                    side = change.get("side", None)
                    reference_kid: Optional[KVId] = None
                    if reference_node_hash is not None:
                        reference_kid, _ = await self.get_node_by_hash(reference_node_hash, store_id)

                    key_hashed = key_hash(key)
                    kid, vid = await self.add_key_value(key, value, store_id)
                    if merkle_blob.key_exists(kid):
                        raise Exception(f"Key already present: {key.hex()}")
                    hash = leaf_hash(key, value)

                    if reference_node_hash is None and side is None:
                        if enable_batch_autoinsert and reference_kid is None:
                            if key_hash_frequency[key_hashed] == 1 or (
                                key_hash_frequency[key_hashed] == 2 and first_action[key_hashed] == "delete"
                            ):
                                batch_keys_values.append((kid, vid))
                                batch_hashes.append(hash)
                                continue
                        if not merkle_blob.empty():
                            reference_kid, side = self.get_reference_kid_side(merkle_blob, key, value)

                    merkle_blob.insert(kid, vid, hash, reference_kid, side)
                elif change["action"] == "delete":
                    key = change["key"]
                    deletion_kid = await self.get_kvid(key, store_id)
                    if deletion_kid is not None:
                        merkle_blob.delete(deletion_kid)
                elif change["action"] == "upsert":
                    key = change["key"]
                    new_value = change["value"]
                    kid, vid = await self.add_key_value(key, new_value, store_id)
                    hash = leaf_hash(key, new_value)
                    merkle_blob.upsert(kid, vid, hash)
                else:
                    raise Exception(f"Operation in batch is not insert or delete: {change}")

            if len(batch_keys_values) > 0:
                merkle_blob.batch_insert(batch_keys_values, batch_hashes)

            new_root = await self.insert_root_from_merkle_blob(merkle_blob, store_id, status, old_root)
            return new_root.node_hash

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
        node_hashes: list[bytes32],
        store_id: bytes32,
        generation: Optional[int] = None,
    ) -> list[InternalNode]:
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

    async def get_node_by_key(
        self,
        key: bytes,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> TerminalNode:
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
        async with self.db_wrapper.reader():
            root = await self.get_tree_root(store_id=store_id)
            # TODO: consider actual proper behavior
            assert root.node_hash is not None

            merkle_blob = await self.get_merkle_blob(root_hash=root.node_hash)

            nodes = merkle_blob.get_nodes_with_indexes()
            hash_to_node: dict[bytes32, Node] = {}
            tree_node: Node
            for _, node in reversed(nodes):
                if isinstance(node, RawInternalMerkleNode):
                    left_hash = merkle_blob.get_hash_at_index(node.left)
                    right_hash = merkle_blob.get_hash_at_index(node.right)
                    tree_node = InternalNode.from_child_nodes(
                        left=hash_to_node[left_hash], right=hash_to_node[right_hash]
                    )
                else:
                    assert isinstance(node, RawLeafMerkleNode)
                    tree_node = await self.get_terminal_node(node.key, node.value, store_id)
                hash_to_node[bytes32(node.hash)] = tree_node

            root_node = hash_to_node[root.node_hash]

        return root_node

    async def get_proof_of_inclusion_by_hash(
        self,
        node_hash: bytes32,
        store_id: bytes32,
        root_hash: Optional[bytes32] = None,
    ) -> ProofOfInclusion:
        if root_hash is None:
            root = await self.get_tree_root(store_id=store_id)
            root_hash = root.node_hash
        merkle_blob = await self.get_merkle_blob(root_hash=root_hash)
        kid, _ = await self.get_node_by_hash(node_hash, store_id)
        return merkle_blob.get_proof_of_inclusion(kid)

    async def get_proof_of_inclusion_by_key(
        self,
        key: bytes,
        store_id: bytes32,
    ) -> ProofOfInclusion:
        root = await self.get_tree_root(store_id=store_id)
        merkle_blob = await self.get_merkle_blob(root_hash=root.node_hash)
        kid = await self.get_kvid(key, store_id)
        if kid is None:
            raise Exception(f"Cannot find key: {key.hex()}")
        return merkle_blob.get_proof_of_inclusion(kid)

    async def write_tree_to_file(
        self,
        root: Root,
        node_hash: bytes32,
        store_id: bytes32,
        deltas_only: bool,
        writer: BinaryIO,
        merkle_blob: Optional[MerkleBlob] = None,
        hash_to_index: Optional[dict[bytes32, TreeIndex]] = None,
    ) -> None:
        if node_hash == bytes32.zeros:
            return

        if merkle_blob is None:
            merkle_blob = await self.get_merkle_blob(root.node_hash)
        if hash_to_index is None:
            hash_to_index = merkle_blob.get_hashes_indexes()

        if deltas_only:
            generation = await self.get_first_generation(node_hash, store_id)
            # Root's generation is not the first time we see this hash, so it's not a new delta.
            if root.generation != generation:
                return

        raw_index = hash_to_index[node_hash]
        raw_node = merkle_blob.get_raw_node(raw_index)

        to_write = b""
        if isinstance(raw_node, RawInternalMerkleNode):
            left_hash = merkle_blob.get_hash_at_index(raw_node.left)
            right_hash = merkle_blob.get_hash_at_index(raw_node.right)
            await self.write_tree_to_file(root, left_hash, store_id, deltas_only, writer, merkle_blob, hash_to_index)
            await self.write_tree_to_file(root, right_hash, store_id, deltas_only, writer, merkle_blob, hash_to_index)
            to_write = bytes(SerializedNode(False, bytes(left_hash), bytes(right_hash)))
        elif isinstance(raw_node, RawLeafMerkleNode):
            node = await self.get_terminal_node(raw_node.key, raw_node.value, store_id)
            to_write = bytes(SerializedNode(True, node.key, node.value))
        else:
            raise Exception(f"Node is neither InternalNode nor TerminalNode: {raw_node}")

        writer.write(len(to_write).to_bytes(4, byteorder="big"))
        writer.write(to_write)

    async def update_subscriptions_from_wallet(self, store_id: bytes32, new_urls: list[str]) -> None:
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

    async def remove_subscriptions(self, store_id: bytes32, urls: list[str]) -> None:
        async with self.db_wrapper.writer() as writer:
            for url in urls:
                await writer.execute(
                    "DELETE FROM subscriptions WHERE tree_id == :tree_id AND url == :url",
                    {
                        "tree_id": store_id,
                        "url": url,
                    },
                )

    async def unsubscribe(self, store_id: bytes32) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "DELETE FROM subscriptions WHERE tree_id == :tree_id",
                {"tree_id": store_id},
            )
            await writer.execute(
                "DELETE FROM hashes WHERE store_id == :store_id",
                {"store_id": store_id},
            )
            await writer.execute(
                "DELETE FROM merkleblob WHERE store_id == :store_id",
                {"store_id": store_id},
            )
            await writer.execute(
                "DELETE FROM ids WHERE store_id == :store_id",
                {"store_id": store_id},
            )
            await writer.execute(
                "DELETE FROM nodes WHERE store_id == :store_id",
                {"store_id": store_id},
            )

    async def rollback_to_generation(self, store_id: bytes32, target_generation: int) -> None:
        async with self.db_wrapper.writer() as writer:
            await writer.execute(
                "DELETE FROM root WHERE tree_id == :tree_id AND generation > :target_generation",
                {"tree_id": store_id, "target_generation": target_generation},
            )
            await writer.execute(
                "DELETE FROM nodes WHERE store_id == :store_id AND generation > :target_generation",
                {"store_id": store_id, "target_generation": target_generation},
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

    async def get_available_servers_for_store(self, store_id: bytes32, timestamp: int) -> list[ServerInfo]:
        subscriptions = await self.get_subscriptions()
        subscription = next((subscription for subscription in subscriptions if subscription.store_id == store_id), None)
        if subscription is None:
            return []
        servers_info = []
        for server_info in subscription.servers_info:
            if timestamp > server_info.ignore_till:
                servers_info.append(server_info)
        return servers_info

    async def get_subscriptions(self) -> list[Subscription]:
        subscriptions: list[Subscription] = []

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
    ) -> set[DiffData]:
        async with self.db_wrapper.reader():
            old_pairs = set(await self.get_keys_values(store_id, hash_1))
            if len(old_pairs) == 0 and hash_1 != bytes32.zeros:
                raise Exception(f"Unable to diff: Can't find keys and values for {hash_1}")

            new_pairs = set(await self.get_keys_values(store_id, hash_2))
            if len(new_pairs) == 0 and hash_2 != bytes32.zeros:
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
