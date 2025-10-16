from __future__ import annotations

import contextlib
import copy
import itertools
import logging
import shutil
import sqlite3
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Iterable, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from typing import Any, BinaryIO, Callable, Optional, Union

import aiosqlite
import anyio.to_thread
import chia_rs.datalayer
import zstd
from chia_rs.datalayer import (
    DeltaFileCache,
    DeltaReader,
    KeyAlreadyPresentError,
    KeyId,
    MerkleBlob,
    ProofOfInclusion,
    TreeIndex,
    ValueId,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import int64

from chia.data_layer.data_layer_errors import KeyNotFoundError, MerkleBlobNotFoundError, TreeGenerationIncrementingError
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
    unspecified,
)
from chia.util.batches import to_batches
from chia.util.cpu import available_logical_cores
from chia.util.db_wrapper import SQLITE_MAX_VARIABLE_NUMBER, DBWrapper2
from chia.util.log_exceptions import log_exceptions
from chia.util.lru_cache import LRUCache

log = logging.getLogger(__name__)


# TODO: review exceptions for values that shouldn't be displayed
# TODO: pick exception types other than Exception

KeyOrValueId = int64

default_prefer_file_kv_blob_length: int = 4096


@dataclass
class DataStore:
    """A key/value store with the pairs being terminal nodes in a CLVM object tree."""

    db_wrapper: DBWrapper2
    recent_merkle_blobs: LRUCache[bytes32, MerkleBlob]
    merkle_blobs_path: Path
    key_value_blobs_path: Path
    unconfirmed_keys_values: dict[bytes32, list[bytes32]] = field(default_factory=dict)
    prefer_db_kv_blob_length: int = default_prefer_file_kv_blob_length

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(
        cls,
        database: Union[str, Path],
        merkle_blobs_path: Path,
        key_value_blobs_path: Path,
        uri: bool = False,
        sql_log_path: Optional[Path] = None,
        cache_capacity: int = 1,
        prefer_db_kv_blob_length: int = default_prefer_file_kv_blob_length,
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
            recent_merkle_blobs: LRUCache[bytes32, MerkleBlob] = LRUCache(capacity=cache_capacity)
            self = cls(
                db_wrapper=db_wrapper,
                recent_merkle_blobs=recent_merkle_blobs,
                merkle_blobs_path=merkle_blobs_path,
                key_value_blobs_path=key_value_blobs_path,
                prefer_db_kv_blob_length=prefer_db_kv_blob_length,
            )

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
                    CREATE TABLE IF NOT EXISTS ids(
                        kv_id INTEGER PRIMARY KEY,
                        hash BLOB NOT NULL CHECK(length(store_id) == 32),
                        blob BLOB,
                        store_id BLOB NOT NULL CHECK(length(store_id) == 32)
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
                    CREATE UNIQUE INDEX IF NOT EXISTS ids_hash_index ON ids(hash, store_id)
                    """
                )
                await writer.execute(
                    """
                    CREATE INDEX IF NOT EXISTS nodes_generation_index ON nodes(generation)
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
        delta_reader: Optional[DeltaReader] = None,
    ) -> Optional[DeltaReader]:
        async with self.db_wrapper.writer():
            with self.manage_kv_files(store_id):
                if root_hash is None:
                    merkle_blob = MerkleBlob(b"")
                else:
                    root = await self.get_tree_root(store_id=store_id)
                    if delta_reader is None:
                        delta_reader = DeltaReader(internal_nodes={}, leaf_nodes={})
                        if root.node_hash is not None:
                            delta_reader.collect_from_merkle_blob(
                                self.get_merkle_path(store_id=store_id, root_hash=root.node_hash),
                                indexes=[TreeIndex(0)],
                            )

                    internal_nodes, terminal_nodes = await self.read_from_file(filename, store_id)
                    delta_reader.add_internal_nodes(internal_nodes)
                    delta_reader.add_leaf_nodes(terminal_nodes)

                    missing_hashes = await anyio.to_thread.run_sync(delta_reader.get_missing_hashes, root_hash)

                    if len(missing_hashes) > 0:
                        # TODO: consider adding transactions around this code
                        merkle_blob_queries = await self.build_merkle_blob_queries_for_missing_hashes(
                            missing_hashes, store_id
                        )
                        if len(merkle_blob_queries) > 0:
                            jobs = [
                                (self.get_merkle_path(store_id=store_id, root_hash=old_root_hash), indexes)
                                for old_root_hash, indexes in merkle_blob_queries.items()
                            ]
                            await anyio.to_thread.run_sync(delta_reader.collect_from_merkle_blobs, jobs)
                        await self.build_cache_and_collect_missing_hashes(root, root_hash, store_id, delta_reader)

                    merkle_blob = delta_reader.create_merkle_blob_and_filter_unused_nodes(root_hash, set())

                # Don't store these blob objects into cache, since their data structures are not calculated yet.
                await self.insert_root_from_merkle_blob(merkle_blob, store_id, Status.COMMITTED, update_cache=False)
                return delta_reader

    async def build_merkle_blob_queries_for_missing_hashes(
        self,
        missing_hashes: set[bytes32],
        store_id: bytes32,
    ) -> defaultdict[bytes32, list[TreeIndex]]:
        queries = defaultdict[bytes32, list[TreeIndex]](list)

        batch_size = min(500, SQLITE_MAX_VARIABLE_NUMBER - 10)

        async with self.db_wrapper.reader() as reader:
            for batch in to_batches(missing_hashes, batch_size):
                placeholders = ",".join(["?"] * len(batch.entries))
                query = f"""
                    SELECT hash, root_hash, idx
                    FROM nodes
                    WHERE store_id = ? AND hash IN ({placeholders})
                    LIMIT {len(batch.entries)}
                """

                async with reader.execute(query, (store_id, *batch.entries)) as cursor:
                    rows = await cursor.fetchall()
                    for row in rows:
                        root_hash_blob = bytes32(row["root_hash"])
                        index = TreeIndex(row["idx"])
                        queries[root_hash_blob].append(index)

        return queries

    async def build_cache_and_collect_missing_hashes(
        self,
        root: Root,
        root_hash: bytes32,
        store_id: bytes32,
        delta_reader: DeltaReader,
    ) -> None:
        missing_hashes = delta_reader.get_missing_hashes(root_hash)

        if len(missing_hashes) == 0:
            return

        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                # TODO: the INDEXED BY seems like it shouldn't be needed, figure out why it is
                #       https://sqlite.org/lang_indexedby.html: admonished to omit all use of INDEXED BY
                #       https://sqlite.org/queryplanner-ng.html#howtofix
                "SELECT MAX(generation) FROM nodes INDEXED BY nodes_generation_index WHERE store_id = ?",
                (store_id,),
            )
            generation_row = await cursor.fetchone()
            if generation_row is None or generation_row[0] is None:
                current_generation = 0
            else:
                current_generation = generation_row[0]
        generations: Sequence[int] = [current_generation]

        while missing_hashes:
            if current_generation >= root.generation:
                raise Exception("Invalid delta file, cannot find all the required hashes")

            current_generation = generations[-1] + 1

            batch_size = available_logical_cores()
            generations = range(
                current_generation,
                min(current_generation + batch_size, root.generation),
            )
            jobs: list[tuple[bytes32, Path]] = []
            generations_by_root_hash: dict[bytes32, int] = {}
            for generation in generations:
                generation_root = await self.get_tree_root(store_id=store_id, generation=generation)
                if generation_root.node_hash is None:
                    # no need to process an empty generation
                    continue
                path = self.get_merkle_path(store_id=store_id, root_hash=generation_root.node_hash)
                jobs.append((generation_root.node_hash, path))
                generations_by_root_hash[generation_root.node_hash] = generation

            found = await anyio.to_thread.run_sync(
                delta_reader.collect_and_return_from_merkle_blobs,
                jobs,
                missing_hashes,
            )
            async with self.db_wrapper.writer() as writer:
                await writer.executemany(
                    """
                    INSERT
                    OR IGNORE INTO nodes(store_id, hash, root_hash, generation, idx)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        (store_id, hash, root_hash, generations_by_root_hash[root_hash], index.raw)
                        for root_hash, map in found
                        for hash, index in map.items()
                    ),
                )

            missing_hashes = delta_reader.get_missing_hashes(root_hash)

            log.info(f"Missing hashes: added old hashes from generation {current_generation}")

    async def read_from_file(
        self, filename: Path, store_id: bytes32
    ) -> tuple[dict[bytes32, tuple[bytes32, bytes32]], dict[bytes32, tuple[KeyId, ValueId]]]:
        internal_nodes: dict[bytes32, tuple[bytes32, bytes32]] = {}
        terminal_nodes: dict[bytes32, tuple[KeyId, ValueId]] = {}

        with open(filename, "rb") as reader:
            async with self.db_wrapper.writer() as writer:
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
                        kid, vid = await self.add_key_value(
                            serialized_node.value1,
                            serialized_node.value2,
                            store_id,
                            writer=writer,
                        )
                        node_hash = leaf_hash(serialized_node.value1, serialized_node.value2)
                        terminal_nodes[node_hash] = (kid, vid)

        return internal_nodes, terminal_nodes

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
                all_roots.append([*roots, root])
            except Exception as e:
                if "unable to find root for id, generation" in str(e):
                    log.error(f"Cannot find roots for {store_id}. Skipping it.")

        log.info(f"Initiating migration to version {version}. Found {len(all_roots)} stores to migrate")

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
                    PRIMARY KEY(tree_id, generation)
                )
                """
            )
            for old_table in old_tables:
                await writer.execute(f"DROP TABLE IF EXISTS {old_table}")
            await writer.execute("ALTER TABLE new_root RENAME TO root")
            await writer.execute("INSERT INTO schema (version_id) VALUES (?)", (version,))
            log.info(f"Initialized new DB schema {version}.")

            total_generations = 0
            synced_generations = 0
            for roots in all_roots:
                assert len(roots) > 0
                total_generations += len(roots)

            for roots in all_roots:
                store_id = roots[0].store_id
                await self.create_tree(store_id=store_id, status=Status.COMMITTED)

                expected_synced_generations = synced_generations + len(roots)
                for root in roots:
                    recovery_filename: Optional[Path] = None

                    for group_by_store in (True, False):
                        filename = get_delta_filename_path(
                            server_files_location,
                            store_id,
                            bytes32.zeros if root.node_hash is None else root.node_hash,
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
                        synced_generations += 1
                        log.info(
                            f"Successfully recovered root from {filename}. "
                            f"Total roots processed: {(synced_generations / total_generations * 100):.2f}%"
                        )
                    except Exception as e:
                        log.error(f"Cannot recover data from {filename}: {e}")
                        break

                if synced_generations < expected_synced_generations:
                    log.error(
                        f"Could not recover {expected_synced_generations - synced_generations} generations. "
                        f"Consider resyncing the store {store_id} once the migration is complete."
                    )
                    # Reset the counter as if we synced correctly, so the percentages add to 100% at the end.
                    synced_generations = expected_synced_generations

    async def get_merkle_blob(
        self,
        store_id: bytes32,
        root_hash: Optional[bytes32],
        read_only: bool = False,
        update_cache: bool = True,
    ) -> MerkleBlob:
        if root_hash is None:
            return MerkleBlob(blob=b"")
        if self.recent_merkle_blobs.get_capacity() == 0:
            update_cache = False

        existing_blob = self.recent_merkle_blobs.get(root_hash)
        if existing_blob is not None:
            return existing_blob if read_only else copy.deepcopy(existing_blob)

        try:
            with log_exceptions(log=log, message="Error while getting merkle blob"):
                path = self.get_merkle_path(store_id=store_id, root_hash=root_hash)
                # TODO: consider file-system based locking of either the file or the store directory
                merkle_blob = MerkleBlob.from_path(path)
        except Exception as e:
            raise MerkleBlobNotFoundError(root_hash=root_hash) from e

        if update_cache:
            self.recent_merkle_blobs.put(root_hash, copy.deepcopy(merkle_blob))

        return merkle_blob

    def get_bytes_path(self, bytes_: bytes) -> Path:
        raw = bytes_.hex()
        segment_sizes = [2, 2, 2]
        start = 0
        segments = []
        for size in segment_sizes:
            segments.append(raw[start : start + size])
            start += size

        return Path(*segments, raw)

    def get_merkle_path(self, store_id: bytes32, root_hash: Optional[bytes32]) -> Path:
        store_root = self.merkle_blobs_path.joinpath(store_id.hex())
        if root_hash is None:
            return store_root

        return store_root.joinpath(self.get_bytes_path(bytes_=root_hash))

    def get_key_value_path(self, store_id: bytes32, blob_hash: Optional[bytes32]) -> Path:
        store_root = self.key_value_blobs_path.joinpath(store_id.hex())
        if blob_hash is None:
            return store_root

        return store_root.joinpath(self.get_bytes_path(bytes_=blob_hash))

    async def insert_root_from_merkle_blob(
        self,
        merkle_blob: MerkleBlob,
        store_id: bytes32,
        status: Status,
        old_root: Optional[Root] = None,
        update_cache: bool = True,
    ) -> Root:
        if not merkle_blob.empty():
            merkle_blob.calculate_lazy_hashes()
        if self.recent_merkle_blobs.get_capacity() == 0:
            update_cache = False

        root_hash = merkle_blob.get_root_hash()
        if old_root is not None and old_root.node_hash == root_hash:
            raise ValueError("Changelist resulted in no change to tree data")

        if root_hash is not None:
            log.info(f"inserting merkle blob: {len(merkle_blob)} bytes {root_hash.hex()}")
            blob_path = self.get_merkle_path(store_id=store_id, root_hash=merkle_blob.get_root_hash())
            if not blob_path.exists():
                blob_path.parent.mkdir(parents=True, exist_ok=True)
                # TODO: consider file-system based locking of either the file or the store directory
                merkle_blob.to_path(blob_path)

            if update_cache:
                self.recent_merkle_blobs.put(root_hash, copy.deepcopy(merkle_blob))

        return await self._insert_root(store_id, root_hash, status)

    def _use_file_for_new_kv_blob(self, blob: bytes) -> bool:
        return len(blob) > self.prefer_db_kv_blob_length

    async def get_kvid(self, blob: bytes, store_id: bytes32) -> Optional[KeyOrValueId]:
        blob_hash = bytes32(sha256(blob).digest())

        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT kv_id FROM ids WHERE hash = ? AND store_id = ?",
                (
                    blob_hash,
                    store_id,
                ),
            )
            row = await cursor.fetchone()

            if row is None:
                return None

            return KeyOrValueId(row[0])

    def get_blob_from_file(self, blob_hash: bytes32, store_id: bytes32) -> bytes:
        # TODO: seems that zstd needs hinting
        # TODO: consider file-system based locking of either the file or the store directory
        return zstd.decompress(self.get_key_value_path(store_id=store_id, blob_hash=blob_hash).read_bytes())  # type: ignore[no-any-return]

    async def get_blob_from_kvid(self, kv_id: KeyOrValueId, store_id: bytes32) -> Optional[bytes]:
        async with self.db_wrapper.reader() as reader:
            cursor = await reader.execute(
                "SELECT hash, blob FROM ids WHERE kv_id = ? AND store_id = ?",
                (
                    kv_id,
                    store_id,
                ),
            )
            row = await cursor.fetchone()

            if row is None:
                return None

        blob: bytes = row["blob"]
        if blob is not None:
            return blob

        blob_hash = bytes32(row["hash"])
        return self.get_blob_from_file(blob_hash, store_id)

    async def get_terminal_node(self, kid: KeyId, vid: ValueId, store_id: bytes32) -> TerminalNode:
        key = await self.get_blob_from_kvid(kid.raw, store_id)
        value = await self.get_blob_from_kvid(vid.raw, store_id)
        if key is None or value is None:
            raise Exception("Cannot find the key/value pair")

        return TerminalNode(hash=leaf_hash(key, value), key=key, value=value)

    async def add_kvid(self, blob: bytes, store_id: bytes32, writer: aiosqlite.Connection) -> KeyOrValueId:
        use_file = self._use_file_for_new_kv_blob(blob)
        blob_hash = bytes32(sha256(blob).digest())
        if use_file:
            table_blob = None
        else:
            table_blob = blob
        try:
            row = await writer.execute_insert(
                "INSERT INTO ids (hash, blob, store_id) VALUES (?, ?, ?)",
                (
                    blob_hash,
                    table_blob,
                    store_id,
                ),
            )
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                kv_id = await self.get_kvid(blob, store_id)
                if kv_id is None:
                    raise Exception("Internal error") from e
                return kv_id

            raise

        if row is None:
            raise Exception("Internal error")
        if use_file:
            path = self.get_key_value_path(store_id=store_id, blob_hash=blob_hash)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.unconfirmed_keys_values[store_id].append(blob_hash)
            # TODO: consider file-system based locking of either the file or the store directory
            path.write_bytes(zstd.compress(blob))
        return KeyOrValueId(row[0])

    def delete_unconfirmed_kvids(self, store_id: bytes32) -> None:
        for blob_hash in self.unconfirmed_keys_values[store_id]:
            with log_exceptions(log=log, consume=True):
                path = self.get_key_value_path(store_id=store_id, blob_hash=blob_hash)
                try:
                    path.unlink()
                except FileNotFoundError:
                    log.error(f"Cannot find key/value path {path} for hash {blob_hash}")
        del self.unconfirmed_keys_values[store_id]

    def confirm_all_kvids(self, store_id: bytes32) -> None:
        del self.unconfirmed_keys_values[store_id]

    @contextmanager
    def manage_kv_files(self, store_id: bytes32) -> Iterator[None]:
        if store_id not in self.unconfirmed_keys_values:
            self.unconfirmed_keys_values[store_id] = []
        else:
            raise Exception("Internal error: unconfirmed keys values cache not cleaned")

        try:
            yield
        except:
            self.delete_unconfirmed_kvids(store_id)
            raise
        else:
            self.confirm_all_kvids(store_id)

    async def add_key_value(
        self, key: bytes, value: bytes, store_id: bytes32, writer: aiosqlite.Connection
    ) -> tuple[KeyId, ValueId]:
        kid = KeyId(await self.add_kvid(key, store_id, writer=writer))
        vid = ValueId(await self.add_kvid(value, store_id, writer=writer))

        return (kid, vid)

    async def get_terminal_node_by_hash(
        self,
        node_hash: bytes32,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> TerminalNode:
        resolved_root_hash: Optional[bytes32]
        if root_hash is unspecified:
            root = await self.get_tree_root(store_id=store_id)
            resolved_root_hash = root.node_hash
        else:
            resolved_root_hash = root_hash

        merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=resolved_root_hash)
        kid, vid = merkle_blob.get_node_by_hash(node_hash)
        return await self.get_terminal_node(kid, vid, store_id)

    async def get_terminal_nodes_by_hashes(
        self,
        node_hashes: list[bytes32],
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> list[TerminalNode]:
        resolved_root_hash: Optional[bytes32]
        if root_hash is unspecified:
            root = await self.get_tree_root(store_id=store_id)
            resolved_root_hash = root.node_hash
        else:
            resolved_root_hash = root_hash

        merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=resolved_root_hash)
        kv_ids: list[tuple[KeyId, ValueId]] = []
        for node_hash in node_hashes:
            kid, vid = merkle_blob.get_node_by_hash(node_hash)
            kv_ids.append((kid, vid))
        kv_ids_unpacked = (KeyOrValueId(id.raw) for kv_id in kv_ids for id in kv_id)
        table_blobs = await self.get_table_blobs(kv_ids_unpacked, store_id)

        terminal_nodes: list[TerminalNode] = []
        for kid, vid in kv_ids:
            terminal_nodes.append(self.get_terminal_node_from_table_blobs(kid, vid, table_blobs, store_id))

        return terminal_nodes

    async def get_existing_hashes(self, node_hashes: list[bytes32], store_id: bytes32) -> set[bytes32]:
        result: set[bytes32] = set()
        batch_size = min(500, SQLITE_MAX_VARIABLE_NUMBER - 10)

        async with self.db_wrapper.reader() as reader:
            for i in range(0, len(node_hashes), batch_size):
                chunk = node_hashes[i : i + batch_size]
                placeholders = ",".join(["?"] * len(chunk))
                query = f"SELECT hash FROM nodes WHERE store_id = ? AND hash IN ({placeholders}) LIMIT {len(chunk)}"

                async with reader.execute(query, (store_id, *chunk)) as cursor:
                    rows = await cursor.fetchall()
                    result.update(row["hash"] for row in rows)

        return result

    async def add_node_hashes(self, store_id: bytes32, generation: Optional[int] = None) -> None:
        root = await self.get_tree_root(store_id=store_id, generation=generation)
        if root.node_hash is None:
            return

        merkle_blob = await self.get_merkle_blob(
            store_id=store_id, root_hash=root.node_hash, read_only=True, update_cache=False
        )
        hash_to_index = merkle_blob.get_hashes_indexes()

        existing_hashes = await self.get_existing_hashes(list(hash_to_index.keys()), store_id)
        async with self.db_wrapper.writer() as writer:
            await writer.executemany(
                """
                INSERT INTO nodes(store_id, hash, root_hash, generation, idx)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (store_id, hash, root.node_hash, root.generation, index.raw)
                    for hash, index in hash_to_index.items()
                    if hash not in existing_hashes
                ),
            )

    async def _insert_root(
        self,
        store_id: bytes32,
        node_hash: Optional[bytes32],
        status: Status,
        generation: Optional[int] = None,
    ) -> Root:
        async with self.db_wrapper.writer_maybe_transaction() as writer:
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

    async def check(self) -> None:
        for check in self._checks:
            await check(self)

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

            merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=root_hash)
            reference_kid, _ = merkle_blob.get_node_by_hash(node_hash)

        reference_index = merkle_blob.get_key_index(reference_kid)
        lineage = merkle_blob.get_lineage_with_indexes(reference_index)
        result: list[InternalNode] = []
        for index, node in itertools.islice(lineage, 1, None):
            assert isinstance(node, chia_rs.datalayer.InternalNode)
            result.append(
                InternalNode(
                    hash=node.hash,
                    left_hash=merkle_blob.get_hash_at_index(node.left),
                    right_hash=merkle_blob.get_hash_at_index(node.right),
                )
            )
        return result

    def get_terminal_node_from_table_blobs(
        self,
        kid: KeyId,
        vid: ValueId,
        table_blobs: dict[KeyOrValueId, tuple[bytes32, Optional[bytes]]],
        store_id: bytes32,
    ) -> TerminalNode:
        key = table_blobs[KeyOrValueId(kid.raw)][1]
        if key is None:
            key_hash = table_blobs[KeyOrValueId(kid.raw)][0]
            key = self.get_blob_from_file(key_hash, store_id)

        value = table_blobs[KeyOrValueId(vid.raw)][1]
        if value is None:
            value_hash = table_blobs[KeyOrValueId(vid.raw)][0]
            value = self.get_blob_from_file(value_hash, store_id)

        return TerminalNode(hash=leaf_hash(key, value), key=key, value=value)

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
                merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=resolved_root_hash)
            except MerkleBlobNotFoundError:
                return []

            kv_ids = merkle_blob.get_keys_values()
            kv_ids_unpacked = (KeyOrValueId(id.raw) for pair in kv_ids.items() for id in pair)
            table_blobs = await self.get_table_blobs(kv_ids_unpacked, store_id)

            terminal_nodes: list[TerminalNode] = []
            for kid, vid in kv_ids.items():
                terminal_nodes.append(self.get_terminal_node_from_table_blobs(kid, vid, table_blobs, store_id))

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
                    merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=resolved_root_hash)
                except MerkleBlobNotFoundError:
                    return KeysValuesCompressed({}, {}, {}, resolved_root_hash)

                kv_ids = merkle_blob.get_keys_values()
                kv_ids_unpacked = (KeyOrValueId(id.raw) for pair in kv_ids.items() for id in pair)
                table_blobs = await self.get_table_blobs(kv_ids_unpacked, store_id)

                for kid, vid in kv_ids.items():
                    node = self.get_terminal_node_from_table_blobs(kid, vid, table_blobs, store_id)
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
        leaf_hashes: list[bytes32] = []
        for hash in pagination_data.hashes:
            leaf_hash = keys_values_compressed.keys_values_hashed[hash]
            leaf_hashes.append(leaf_hash)
        nodes = await self.get_terminal_nodes_by_hashes(leaf_hashes, store_id, root_hash)
        keys = [node.key for node in nodes]

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

        keys_values = await self.get_terminal_nodes_by_hashes(pagination_data.hashes, store_id, root_hash)
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
        insertion_hashes: list[bytes32] = []
        deletion_hashes: list[bytes32] = []
        for hash in pagination_data.hashes:
            if hash in insertions:
                insertion_hashes.append(hash)
            else:
                deletion_hashes.append(hash)
        if hash2 != bytes32.zeros:
            insertion_nodes = await self.get_terminal_nodes_by_hashes(insertion_hashes, store_id, hash2)
        else:
            insertion_nodes = []
        if hash1 != bytes32.zeros:
            deletion_nodes = await self.get_terminal_nodes_by_hashes(deletion_hashes, store_id, hash1)
        else:
            deletion_nodes = []
        for node in insertion_nodes:
            kv_diff.append(DiffData(OperationType.INSERT, node.key, node.value))
        for node in deletion_nodes:
            kv_diff.append(DiffData(OperationType.DELETE, node.key, node.value))

        return KVDiffPaginationData(
            pagination_data.total_pages,
            pagination_data.total_bytes,
            kv_diff,
        )

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
                merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=resolved_root_hash)
            except MerkleBlobNotFoundError:
                return []

            kv_ids = merkle_blob.get_keys_values()
            raw_key_ids = (KeyOrValueId(id.raw) for id in kv_ids.keys())
            table_blobs = await self.get_table_blobs(raw_key_ids, store_id)
            keys: list[bytes] = []
            for kid in kv_ids.keys():
                blob_hash, blob = table_blobs[KeyOrValueId(kid.raw)]
                if blob is None:
                    blob = self.get_blob_from_file(blob_hash, store_id)
                keys.append(blob)

        return keys

    def get_reference_kid_side(self, merkle_blob: MerkleBlob, seed: bytes32) -> tuple[KeyId, Side]:
        side_seed = bytes(seed)[0]
        side = Side.LEFT if side_seed < 128 else Side.RIGHT
        reference_node = merkle_blob.get_random_leaf_node(seed)
        kid = reference_node.key
        return (kid, side)

    async def get_terminal_node_from_kid(self, merkle_blob: MerkleBlob, kid: KeyId, store_id: bytes32) -> TerminalNode:
        index = merkle_blob.get_key_index(kid)
        raw_node = merkle_blob.get_raw_node(index)
        assert isinstance(raw_node, chia_rs.datalayer.LeafNode)
        return await self.get_terminal_node(raw_node.key, raw_node.value, store_id)

    async def get_terminal_node_for_seed(self, seed: bytes32, store_id: bytes32) -> Optional[TerminalNode]:
        root = await self.get_tree_root(store_id=store_id)
        if root is None or root.node_hash is None:
            return None

        merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=root.node_hash)
        assert not merkle_blob.empty()
        kid, _ = self.get_reference_kid_side(merkle_blob, seed)
        return await self.get_terminal_node_from_kid(merkle_blob, kid, store_id)

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
        async with self.db_wrapper.writer() as writer:
            with self.manage_kv_files(store_id):
                if root is None:
                    root = await self.get_tree_root(store_id=store_id)
                merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=root.node_hash)

                kid, vid = await self.add_key_value(key, value, store_id, writer=writer)
                hash = leaf_hash(key, value)
                reference_kid = None
                if reference_node_hash is not None:
                    reference_kid, _ = merkle_blob.get_node_by_hash(reference_node_hash)

                was_empty = root.node_hash is None
                if not was_empty and reference_kid is None:
                    if side is not None:
                        raise Exception("Side specified without reference node hash")

                    seed = leaf_hash(key=key, value=value)
                    reference_kid, side = self.get_reference_kid_side(merkle_blob, seed)

                merkle_blob.insert(kid, vid, hash, reference_kid, side)

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
            merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=root.node_hash)

            kid = await self.get_kvid(key, store_id)
            if kid is not None:
                merkle_blob.delete(KeyId(kid))

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
        async with self.db_wrapper.writer() as writer:
            with self.manage_kv_files(store_id):
                if root is None:
                    root = await self.get_tree_root(store_id=store_id)
                merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=root.node_hash)

                kid, vid = await self.add_key_value(key, new_value, store_id, writer=writer)
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
        async with self.db_wrapper.writer() as writer:
            with self.manage_kv_files(store_id):
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

                merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=old_root.node_hash)

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

                batch_keys_values: list[tuple[KeyId, ValueId]] = []
                batch_hashes: list[bytes32] = []

                for change in changelist:
                    if change["action"] == "insert":
                        key = change["key"]
                        value = change["value"]

                        reference_node_hash = change.get("reference_node_hash", None)
                        side = change.get("side", None)
                        reference_kid: Optional[KeyId] = None
                        if reference_node_hash is not None:
                            reference_kid, _ = merkle_blob.get_node_by_hash(reference_node_hash)

                        key_hashed = key_hash(key)
                        kid, vid = await self.add_key_value(key, value, store_id, writer=writer)
                        try:
                            merkle_blob.get_key_index(kid)
                        except chia_rs.datalayer.UnknownKeyError:
                            pass
                        else:
                            raise KeyAlreadyPresentError(kid)
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
                                seed = leaf_hash(key=key, value=value)
                                reference_kid, side = self.get_reference_kid_side(merkle_blob, seed)

                        merkle_blob.insert(kid, vid, hash, reference_kid, side)
                    elif change["action"] == "delete":
                        key = change["key"]
                        deletion_kid = await self.get_kvid(key, store_id)
                        if deletion_kid is not None:
                            merkle_blob.delete(KeyId(deletion_kid))
                    elif change["action"] == "upsert":
                        key = change["key"]
                        new_value = change["value"]
                        kid, vid = await self.add_key_value(key, new_value, store_id, writer=writer)
                        hash = leaf_hash(key, new_value)
                        merkle_blob.upsert(kid, vid, hash)
                    else:
                        raise Exception(f"Operation in batch is not insert or delete: {change}")

                if len(batch_keys_values) > 0:
                    merkle_blob.batch_insert(batch_keys_values, batch_hashes)

                new_root = await self.insert_root_from_merkle_blob(merkle_blob, store_id, status, old_root)
                return new_root.node_hash

    async def get_node_by_key(
        self,
        key: bytes,
        store_id: bytes32,
        root_hash: Union[bytes32, Unspecified] = unspecified,
    ) -> TerminalNode:
        async with self.db_wrapper.reader():
            resolved_root_hash: Optional[bytes32]
            if root_hash is unspecified:
                root = await self.get_tree_root(store_id=store_id)
                resolved_root_hash = root.node_hash
            else:
                resolved_root_hash = root_hash

            try:
                merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=resolved_root_hash)
            except MerkleBlobNotFoundError:
                raise KeyNotFoundError(key=key)

            kvid = await self.get_kvid(key, store_id)
            if kvid is None:
                raise KeyNotFoundError(key=key)
            kid = KeyId(kvid)
            return await self.get_terminal_node_from_kid(merkle_blob, kid, store_id)

    async def get_tree_as_nodes(self, store_id: bytes32) -> Node:
        async with self.db_wrapper.reader():
            root = await self.get_tree_root(store_id=store_id)
            # TODO: consider actual proper behavior
            assert root.node_hash is not None

            merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=root.node_hash)

            nodes = merkle_blob.get_nodes_with_indexes()
            hash_to_node: dict[bytes32, Node] = {}
            tree_node: Node
            for _, node in reversed(nodes):
                if isinstance(node, chia_rs.datalayer.InternalNode):
                    left_hash = merkle_blob.get_hash_at_index(node.left)
                    right_hash = merkle_blob.get_hash_at_index(node.right)
                    tree_node = InternalNode.from_child_nodes(
                        left=hash_to_node[left_hash], right=hash_to_node[right_hash]
                    )
                else:
                    assert isinstance(node, chia_rs.datalayer.LeafNode)
                    tree_node = await self.get_terminal_node(node.key, node.value, store_id)
                hash_to_node[node.hash] = tree_node

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
        merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=root_hash)
        kid, _ = merkle_blob.get_node_by_hash(node_hash)
        return merkle_blob.get_proof_of_inclusion(kid)

    async def get_proof_of_inclusion_by_key(
        self,
        key: bytes,
        store_id: bytes32,
    ) -> ProofOfInclusion:
        root = await self.get_tree_root(store_id=store_id)
        merkle_blob = await self.get_merkle_blob(store_id=store_id, root_hash=root.node_hash)
        kvid = await self.get_kvid(key, store_id)
        if kvid is None:
            raise Exception(f"Cannot find key: {key.hex()}")
        kid = KeyId(kvid)
        return merkle_blob.get_proof_of_inclusion(kid)

    async def get_nodes_for_file(
        self,
        root: Root,
        node_hash: bytes32,
        store_id: bytes32,
        deltas_only: bool,
        delta_file_cache: DeltaFileCache,
        tree_nodes: list[SerializedNode],
    ) -> None:
        if deltas_only:
            if delta_file_cache.seen_previous_hash(node_hash):
                return

        raw_index = delta_file_cache.get_index(node_hash)
        raw_node = delta_file_cache.get_raw_node(raw_index)

        if isinstance(raw_node, chia_rs.datalayer.InternalNode):
            left_hash = delta_file_cache.get_hash_at_index(raw_node.left)
            right_hash = delta_file_cache.get_hash_at_index(raw_node.right)
            await self.get_nodes_for_file(root, left_hash, store_id, deltas_only, delta_file_cache, tree_nodes)
            await self.get_nodes_for_file(root, right_hash, store_id, deltas_only, delta_file_cache, tree_nodes)
            tree_nodes.append(SerializedNode(False, bytes(left_hash), bytes(right_hash)))
        elif isinstance(raw_node, chia_rs.datalayer.LeafNode):
            tree_nodes.append(
                SerializedNode(
                    True,
                    raw_node.key.to_bytes(),
                    raw_node.value.to_bytes(),
                )
            )
        else:
            raise Exception(f"Node is neither InternalNode nor TerminalNode: {raw_node}")

    async def get_table_blobs(
        self, kv_ids_iter: Iterable[KeyOrValueId], store_id: bytes32
    ) -> dict[KeyOrValueId, tuple[bytes32, Optional[bytes]]]:
        result: dict[KeyOrValueId, tuple[bytes32, Optional[bytes]]] = {}
        batch_size = min(500, SQLITE_MAX_VARIABLE_NUMBER - 10)
        kv_ids = list(dict.fromkeys(kv_ids_iter))

        async with self.db_wrapper.reader() as reader:
            for i in range(0, len(kv_ids), batch_size):
                chunk = kv_ids[i : i + batch_size]
                placeholders = ",".join(["?"] * len(chunk))
                query = f"""
                    SELECT hash, blob, kv_id
                    FROM ids
                    WHERE store_id = ? AND kv_id IN ({placeholders})
                    LIMIT {len(chunk)}
                """

                async with reader.execute(query, (store_id, *chunk)) as cursor:
                    rows = await cursor.fetchall()
                    result.update({row["kv_id"]: (row["hash"], row["blob"]) for row in rows})

        if len(result) != len(kv_ids):
            raise Exception("Cannot retrieve all the requested kv_ids")

        return result

    async def write_tree_to_file(
        self,
        root: Root,
        node_hash: bytes32,
        store_id: bytes32,
        deltas_only: bool,
        writer: BinaryIO,
    ) -> None:
        if node_hash == bytes32.zeros:
            return

        with log_exceptions(log=log, message="Error while getting merkle blob"):
            root_path = self.get_merkle_path(store_id=store_id, root_hash=root.node_hash)
        delta_file_cache = DeltaFileCache(root_path)

        if root.generation > 0:
            previous_root = await self.get_tree_root(store_id=store_id, generation=root.generation - 1)
            if previous_root.node_hash is not None:
                with log_exceptions(log=log, message="Error while getting previous merkle blob"):
                    previous_root_path = self.get_merkle_path(store_id=store_id, root_hash=previous_root.node_hash)
                delta_file_cache.load_previous_hashes(previous_root_path)

        tree_nodes: list[SerializedNode] = []

        await self.get_nodes_for_file(root, node_hash, store_id, deltas_only, delta_file_cache, tree_nodes)
        kv_ids = (
            KeyOrValueId.from_bytes(raw_id)
            for node in tree_nodes
            if node.is_terminal
            for raw_id in (node.value1, node.value2)
        )
        table_blobs = await self.get_table_blobs(kv_ids, store_id)

        for node in tree_nodes:
            if node.is_terminal:
                blobs = []
                for raw_id in (node.value1, node.value2):
                    id = KeyOrValueId.from_bytes(raw_id)
                    blob_hash, blob = table_blobs[id]
                    if blob is None:
                        blob = self.get_blob_from_file(blob_hash, store_id)
                    blobs.append(blob)
                to_write = bytes(SerializedNode(True, blobs[0], blobs[1]))
            else:
                to_write = bytes(node)
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
                "DELETE FROM ids WHERE store_id == :store_id",
                {"store_id": store_id},
            )
            await writer.execute(
                "DELETE FROM nodes WHERE store_id == :store_id",
                {"store_id": store_id},
            )

            with contextlib.suppress(FileNotFoundError):
                shutil.rmtree(self.get_merkle_path(store_id=store_id, root_hash=None))

            with contextlib.suppress(FileNotFoundError):
                shutil.rmtree(self.get_key_value_path(store_id=store_id, blob_hash=None))

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
                elif url is not None and num_consecutive_failures is not None and ignore_till is not None:
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
