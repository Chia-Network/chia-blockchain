from __future__ import annotations

import itertools
import logging
import os
import random
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, cast

import aiohttp
import aiosqlite
import pytest

from chia._tests.core.data_layer.util import Example, add_0123_example, add_01234567_example
from chia._tests.util.misc import BenchmarkRunner, Marks, boolean_datacases, datacases
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
    ServerInfo,
    Side,
    Status,
    Subscription,
    TerminalNode,
    _debug_dump,
    leaf_hash,
)
from chia.data_layer.data_store import DataStore
from chia.data_layer.download_data import (
    get_delta_filename_path,
    get_full_tree_filename_path,
    insert_from_delta_file,
    insert_into_data_store_from_file,
    write_files_for_root,
)
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.db_wrapper import DBWrapper2, generate_in_memory_db_uri

log = logging.getLogger(__name__)


pytestmark = pytest.mark.data_layer


table_columns: Dict[str, List[str]] = {
    "node": ["hash", "node_type", "left", "right", "key", "value"],
    "root": ["tree_id", "generation", "node_hash", "status"],
}


# TODO: Someday add tests for malformed DB data to make sure we handle it gracefully
#       and with good error messages.


@pytest.mark.anyio
async def test_valid_node_values_fixture_are_valid(data_store: DataStore, valid_node_values: Dict[str, Any]) -> None:
    async with data_store.db_wrapper.writer() as writer:
        await writer.execute(
            """
            INSERT INTO node(hash, node_type, left, right, key, value)
            VALUES(:hash, :node_type, :left, :right, :key, :value)
            """,
            valid_node_values,
        )


@pytest.mark.parametrize(argnames=["table_name", "expected_columns"], argvalues=table_columns.items())
@pytest.mark.anyio
async def test_create_creates_tables_and_columns(
    database_uri: str, table_name: str, expected_columns: List[str]
) -> None:
    # Never string-interpolate sql queries...  Except maybe in tests when it does not
    # allow you to parametrize the query.
    query = f"pragma table_info({table_name});"

    async with DBWrapper2.managed(database=database_uri, uri=True, reader_count=1) as db_wrapper:
        async with db_wrapper.reader() as reader:
            cursor = await reader.execute(query)
            columns = await cursor.fetchall()
            assert columns == []

        async with DataStore.managed(database=database_uri, uri=True):
            async with db_wrapper.reader() as reader:
                cursor = await reader.execute(query)
                columns = await cursor.fetchall()
                assert [column[1] for column in columns] == expected_columns


@pytest.mark.anyio
async def test_create_tree_accepts_bytes32(raw_data_store: DataStore) -> None:
    store_id = bytes32(b"\0" * 32)

    await raw_data_store.create_tree(store_id=store_id)


@pytest.mark.parametrize(argnames=["length"], argvalues=[[length] for length in [*range(0, 32), *range(33, 48)]])
@pytest.mark.anyio
async def test_create_store_fails_for_not_bytes32(raw_data_store: DataStore, length: int) -> None:
    bad_store_id = b"\0" * length

    # TODO: require a more specific exception
    with pytest.raises(Exception):
        # type ignore since we are trying to intentionally pass a bad argument
        await raw_data_store.create_tree(store_id=bad_store_id)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_get_trees(raw_data_store: DataStore) -> None:
    expected_store_ids = set()

    for n in range(10):
        store_id = bytes32(b"\0" * 31 + bytes([n]))
        await raw_data_store.create_tree(store_id=store_id)
        expected_store_ids.add(store_id)

    store_ids = await raw_data_store.get_store_ids()

    assert store_ids == expected_store_ids


@pytest.mark.anyio
async def test_table_is_empty(data_store: DataStore, store_id: bytes32) -> None:
    is_empty = await data_store.table_is_empty(store_id=store_id)
    assert is_empty


@pytest.mark.anyio
async def test_table_is_not_empty(data_store: DataStore, store_id: bytes32) -> None:
    key = b"\x01\x02"
    value = b"abc"

    await data_store.insert(
        key=key,
        value=value,
        store_id=store_id,
        reference_node_hash=None,
        side=None,
        status=Status.COMMITTED,
    )

    is_empty = await data_store.table_is_empty(store_id=store_id)
    assert not is_empty


# @pytest.mark.anyio
# async def test_create_root_provides_bytes32(raw_data_store: DataStore, store_id: bytes32) -> None:
#     await raw_data_store.create_tree(store_id=store_id)
#     # TODO: catchup with the node_hash=
#     root_hash = await raw_data_store.create_root(store_id=store_id, node_hash=23)
#
#     assert isinstance(root_hash, bytes32)


@pytest.mark.anyio
async def test_insert_over_empty(data_store: DataStore, store_id: bytes32) -> None:
    key = b"\x01\x02"
    value = b"abc"

    insert_result = await data_store.insert(
        key=key, value=value, store_id=store_id, reference_node_hash=None, side=None
    )
    assert insert_result.node_hash == leaf_hash(key=key, value=value)


@pytest.mark.anyio
async def test_insert_increments_generation(data_store: DataStore, store_id: bytes32) -> None:
    keys = [b"a", b"b", b"c", b"d"]  # efghijklmnopqrstuvwxyz")
    value = b"\x01\x02\x03"

    generations = []
    expected = []

    node_hash = None
    for key, expected_generation in zip(keys, itertools.count(start=1)):
        insert_result = await data_store.insert(
            key=key,
            value=value,
            store_id=store_id,
            reference_node_hash=node_hash,
            side=None if node_hash is None else Side.LEFT,
            status=Status.COMMITTED,
        )
        node_hash = insert_result.node_hash
        generation = await data_store.get_tree_generation(store_id=store_id)
        generations.append(generation)
        expected.append(expected_generation)

    assert generations == expected


@pytest.mark.anyio
async def test_get_tree_generation_returns_none_when_none_available(
    raw_data_store: DataStore,
    store_id: bytes32,
) -> None:
    with pytest.raises(Exception, match=re.escape(f"No generations found for store ID: {store_id.hex()}")):
        await raw_data_store.get_tree_generation(store_id=store_id)


@pytest.mark.anyio
async def test_insert_internal_node_does_nothing_if_matching(data_store: DataStore, store_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, store_id=store_id)

    kv_node = await data_store.get_node_by_key(key=b"\x04", store_id=store_id)
    ancestors = await data_store.get_ancestors(node_hash=kv_node.hash, store_id=store_id)
    parent = ancestors[0]

    async with data_store.db_wrapper.reader() as reader:
        cursor = await reader.execute("SELECT * FROM node")
        before = await cursor.fetchall()

    await data_store._insert_internal_node(left_hash=parent.left_hash, right_hash=parent.right_hash)

    async with data_store.db_wrapper.reader() as reader:
        cursor = await reader.execute("SELECT * FROM node")
        after = await cursor.fetchall()

    assert after == before


@pytest.mark.anyio
async def test_insert_terminal_node_does_nothing_if_matching(data_store: DataStore, store_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, store_id=store_id)

    kv_node = await data_store.get_node_by_key(key=b"\x04", store_id=store_id)

    async with data_store.db_wrapper.reader() as reader:
        cursor = await reader.execute("SELECT * FROM node")
        before = await cursor.fetchall()

    await data_store._insert_terminal_node(key=kv_node.key, value=kv_node.value)

    async with data_store.db_wrapper.reader() as reader:
        cursor = await reader.execute("SELECT * FROM node")
        after = await cursor.fetchall()

    assert after == before


@pytest.mark.anyio
async def test_build_a_tree(
    data_store: DataStore,
    store_id: bytes32,
    create_example: Callable[[DataStore, bytes32], Awaitable[Example]],
) -> None:
    example = await create_example(data_store, store_id)

    await _debug_dump(db=data_store.db_wrapper, description="final")
    actual = await data_store.get_tree_as_nodes(store_id=store_id)
    # print("actual  ", actual.as_python())
    # print("expected", example.expected.as_python())
    assert actual == example.expected


@pytest.mark.anyio
async def test_get_node_by_key(data_store: DataStore, store_id: bytes32) -> None:
    example = await add_0123_example(data_store=data_store, store_id=store_id)

    key_node_hash = example.terminal_nodes[2]

    # TODO: make a nicer relationship between the hash and the key

    actual = await data_store.get_node_by_key(key=b"\x02", store_id=store_id)
    assert actual.hash == key_node_hash


@pytest.mark.anyio
async def test_get_ancestors(data_store: DataStore, store_id: bytes32) -> None:
    example = await add_0123_example(data_store=data_store, store_id=store_id)

    reference_node_hash = example.terminal_nodes[2]

    ancestors = await data_store.get_ancestors(node_hash=reference_node_hash, store_id=store_id)
    hashes = [node.hash.hex() for node in ancestors]

    # TODO: reverify these are correct
    assert hashes == [
        "3ab212e30b0e746d81a993e39f2cb4ba843412d44b402c1117a500d6451309e3",
        "c852ecd8fb61549a0a42f9eb9dde65e6c94a01934dbd9c1d35ab94e2a0ae58e2",
    ]

    ancestors_2 = await data_store.get_ancestors_optimized(node_hash=reference_node_hash, store_id=store_id)
    assert ancestors == ancestors_2


@pytest.mark.anyio
async def test_get_ancestors_optimized(data_store: DataStore, store_id: bytes32) -> None:
    ancestors: List[Tuple[int, bytes32, List[InternalNode]]] = []
    random = Random()
    random.seed(100, version=2)

    first_insertions = [True, False, True, False, True, True, False, True, False, True, True, False, False, True, False]
    deleted_all = False
    node_count = 0
    for i in range(1000):
        is_insert = False
        if i <= 14:
            is_insert = first_insertions[i]
        if i > 14 and i <= 25:
            is_insert = True
        if i > 25 and i <= 200 and random.randint(0, 4):
            is_insert = True
        if i > 200:
            if not deleted_all:
                while node_count > 0:
                    node_count -= 1
                    seed = bytes32(b"0" * 32)
                    node_hash = await data_store.get_terminal_node_for_seed(store_id, seed)
                    assert node_hash is not None
                    node = await data_store.get_node(node_hash)
                    assert isinstance(node, TerminalNode)
                    await data_store.delete(key=node.key, store_id=store_id, status=Status.COMMITTED)
                deleted_all = True
                is_insert = True
            else:
                assert node_count <= 4
                if node_count == 0:
                    is_insert = True
                elif node_count < 4 and random.randint(0, 2):
                    is_insert = True
        key = (i % 200).to_bytes(4, byteorder="big")
        value = (i % 200).to_bytes(4, byteorder="big")
        seed = Program.to((key, value)).get_tree_hash()
        node_hash = await data_store.get_terminal_node_for_seed(store_id, seed)
        if is_insert:
            node_count += 1
            side = None if node_hash is None else data_store.get_side_for_seed(seed)

            insert_result = await data_store.insert(
                key=key,
                value=value,
                store_id=store_id,
                reference_node_hash=node_hash,
                side=side,
                use_optimized=False,
                status=Status.COMMITTED,
            )
            node_hash = insert_result.node_hash
            if node_hash is not None:
                generation = await data_store.get_tree_generation(store_id=store_id)
                current_ancestors = await data_store.get_ancestors(node_hash=node_hash, store_id=store_id)
                ancestors.append((generation, node_hash, current_ancestors))
        else:
            node_count -= 1
            assert node_hash is not None
            node = await data_store.get_node(node_hash)
            assert isinstance(node, TerminalNode)
            await data_store.delete(key=node.key, store_id=store_id, use_optimized=False, status=Status.COMMITTED)

    for generation, node_hash, expected_ancestors in ancestors:
        current_ancestors = await data_store.get_ancestors_optimized(
            node_hash=node_hash, store_id=store_id, generation=generation
        )
        assert current_ancestors == expected_ancestors


@pytest.mark.anyio
@pytest.mark.parametrize(
    "use_optimized",
    [True, False],
)
@pytest.mark.parametrize(
    "num_batches",
    [1, 5, 10, 25],
)
async def test_batch_update(
    data_store: DataStore,
    store_id: bytes32,
    use_optimized: bool,
    tmp_path: Path,
    num_batches: int,
) -> None:
    total_operations = 1000 if use_optimized else 100
    num_ops_per_batch = total_operations // num_batches
    saved_batches: List[List[Dict[str, Any]]] = []
    saved_kv: List[List[TerminalNode]] = []
    db_uri = generate_in_memory_db_uri()
    async with DataStore.managed(database=db_uri, uri=True) as single_op_data_store:
        await single_op_data_store.create_tree(store_id, status=Status.COMMITTED)
        random = Random()
        random.seed(100, version=2)

        batch: List[Dict[str, Any]] = []
        keys_values: Dict[bytes, bytes] = {}
        for operation in range(num_batches * num_ops_per_batch):
            [op_type] = random.choices(
                ["insert", "upsert-insert", "upsert-update", "delete"],
                [0.4, 0.2, 0.2, 0.2],
                k=1,
            )
            if op_type == "insert" or op_type == "upsert-insert" or len(keys_values) == 0:
                if len(keys_values) == 0:
                    op_type = "insert"
                key = operation.to_bytes(4, byteorder="big")
                value = (2 * operation).to_bytes(4, byteorder="big")
                if op_type == "insert":
                    await single_op_data_store.autoinsert(
                        key=key,
                        value=value,
                        store_id=store_id,
                        use_optimized=use_optimized,
                        status=Status.COMMITTED,
                    )
                else:
                    await single_op_data_store.upsert(
                        key=key,
                        new_value=value,
                        store_id=store_id,
                        use_optimized=use_optimized,
                        status=Status.COMMITTED,
                    )
                action = "insert" if op_type == "insert" else "upsert"
                batch.append({"action": action, "key": key, "value": value})
                keys_values[key] = value
            elif op_type == "delete":
                key = random.choice(list(keys_values.keys()))
                del keys_values[key]
                await single_op_data_store.delete(
                    key=key,
                    store_id=store_id,
                    use_optimized=use_optimized,
                    status=Status.COMMITTED,
                )
                batch.append({"action": "delete", "key": key})
            else:
                assert op_type == "upsert-update"
                key = random.choice(list(keys_values.keys()))
                old_value = keys_values[key]
                new_value_int = int.from_bytes(old_value, byteorder="big") + 1
                new_value = new_value_int.to_bytes(4, byteorder="big")
                await single_op_data_store.upsert(
                    key=key,
                    new_value=new_value,
                    store_id=store_id,
                    use_optimized=use_optimized,
                    status=Status.COMMITTED,
                )
                keys_values[key] = new_value
                batch.append({"action": "upsert", "key": key, "value": new_value})
            if (operation + 1) % num_ops_per_batch == 0:
                saved_batches.append(batch)
                batch = []
                current_kv = await single_op_data_store.get_keys_values(store_id=store_id)
                assert {kv.key: kv.value for kv in current_kv} == keys_values
                saved_kv.append(current_kv)

    for batch_number, batch in enumerate(saved_batches):
        assert len(batch) == num_ops_per_batch
        await data_store.insert_batch(store_id, batch, status=Status.COMMITTED)
        root = await data_store.get_tree_root(store_id)
        assert root.generation == batch_number + 1
        assert root.node_hash is not None
        current_kv = await data_store.get_keys_values(store_id=store_id)
        # Get the same keys/values, but possibly stored in other order.
        assert {node.key: node.value for node in current_kv} == {
            node.key: node.value for node in saved_kv[batch_number]
        }
        queue: List[bytes32] = [root.node_hash]
        ancestors: Dict[bytes32, bytes32] = {}
        while len(queue) > 0:
            node_hash = queue.pop(0)
            expected_ancestors = []
            ancestor = node_hash
            while ancestor in ancestors:
                ancestor = ancestors[ancestor]
                expected_ancestors.append(ancestor)
            result_ancestors = await data_store.get_ancestors_optimized(node_hash, store_id)
            assert [node.hash for node in result_ancestors] == expected_ancestors
            node = await data_store.get_node(node_hash)
            if isinstance(node, InternalNode):
                queue.append(node.left_hash)
                queue.append(node.right_hash)
                ancestors[node.left_hash] = node_hash
                ancestors[node.right_hash] = node_hash

    all_kv = await data_store.get_keys_values(store_id)
    assert {node.key: node.value for node in all_kv} == keys_values


@pytest.mark.anyio
@pytest.mark.parametrize(
    "use_optimized",
    [True, False],
)
async def test_upsert_ignores_existing_arguments(
    data_store: DataStore,
    store_id: bytes32,
    use_optimized: bool,
) -> None:
    key = b"key"
    value = b"value1"

    await data_store.autoinsert(
        key=key,
        value=value,
        store_id=store_id,
        use_optimized=use_optimized,
        status=Status.COMMITTED,
    )
    node = await data_store.get_node_by_key(key, store_id)
    assert node.value == value

    new_value = b"value2"
    await data_store.upsert(
        key=key,
        new_value=new_value,
        store_id=store_id,
        use_optimized=use_optimized,
        status=Status.COMMITTED,
    )
    node = await data_store.get_node_by_key(key, store_id)
    assert node.value == new_value

    await data_store.upsert(
        key=key,
        new_value=new_value,
        store_id=store_id,
        use_optimized=use_optimized,
        status=Status.COMMITTED,
    )
    node = await data_store.get_node_by_key(key, store_id)
    assert node.value == new_value

    key2 = b"key2"
    await data_store.upsert(
        key=key2,
        new_value=value,
        store_id=store_id,
        use_optimized=use_optimized,
        status=Status.COMMITTED,
    )
    node = await data_store.get_node_by_key(key2, store_id)
    assert node.value == value


@pytest.mark.parametrize(argnames="side", argvalues=list(Side))
@pytest.mark.anyio
async def test_insert_batch_reference_and_side(
    data_store: DataStore,
    store_id: bytes32,
    side: Side,
) -> None:
    insert_result = await data_store.autoinsert(
        key=b"key1",
        value=b"value1",
        store_id=store_id,
        status=Status.COMMITTED,
    )

    new_root_hash = await data_store.insert_batch(
        store_id=store_id,
        changelist=[
            {
                "action": "insert",
                "key": b"key2",
                "value": b"value2",
                "reference_node_hash": insert_result.node_hash,
                "side": side,
            },
        ],
    )
    assert new_root_hash is not None, "batch insert failed or failed to update root"

    parent = await data_store.get_node(new_root_hash)
    assert isinstance(parent, InternalNode)
    if side == Side.LEFT:
        child = await data_store.get_node(parent.left_hash)
        assert parent.left_hash == child.hash
    elif side == Side.RIGHT:
        child = await data_store.get_node(parent.right_hash)
        assert parent.right_hash == child.hash
    else:  # pragma: no cover
        raise Exception("invalid side for test")


@pytest.mark.anyio
async def test_ancestor_table_unique_inserts(data_store: DataStore, store_id: bytes32) -> None:
    await add_0123_example(data_store=data_store, store_id=store_id)
    hash_1 = bytes32.from_hexstr("0763561814685fbf92f6ca71fbb1cb11821951450d996375c239979bd63e9535")
    hash_2 = bytes32.from_hexstr("924be8ff27e84cba17f5bc918097f8410fab9824713a4668a21c8e060a8cab40")
    await data_store._insert_ancestor_table(hash_1, hash_2, store_id, 2)
    await data_store._insert_ancestor_table(hash_1, hash_2, store_id, 2)
    with pytest.raises(Exception, match="^Requested insertion of ancestor"):
        await data_store._insert_ancestor_table(hash_1, hash_1, store_id, 2)
    await data_store._insert_ancestor_table(hash_1, hash_2, store_id, 2)


@pytest.mark.anyio
async def test_get_pairs(
    data_store: DataStore,
    store_id: bytes32,
    create_example: Callable[[DataStore, bytes32], Awaitable[Example]],
) -> None:
    example = await create_example(data_store, store_id)

    pairs = await data_store.get_keys_values(store_id=store_id)

    assert [node.hash for node in pairs] == example.terminal_nodes


@pytest.mark.anyio
async def test_get_pairs_when_empty(data_store: DataStore, store_id: bytes32) -> None:
    pairs = await data_store.get_keys_values(store_id=store_id)

    assert pairs == []


@pytest.mark.parametrize(
    argnames=["first_value", "second_value"],
    argvalues=[[b"\x06", b"\x06"], [b"\x06", b"\x07"]],
    ids=["same values", "different values"],
)
@pytest.mark.anyio()
async def test_inserting_duplicate_key_fails(
    data_store: DataStore,
    store_id: bytes32,
    first_value: bytes,
    second_value: bytes,
) -> None:
    key = b"\x05"

    insert_result = await data_store.insert(
        key=key,
        value=first_value,
        store_id=store_id,
        reference_node_hash=None,
        side=None,
    )

    # TODO: more specific exception
    with pytest.raises(Exception):
        await data_store.insert(
            key=key,
            value=second_value,
            store_id=store_id,
            reference_node_hash=insert_result.node_hash,
            side=Side.RIGHT,
        )

    # TODO: more specific exception
    with pytest.raises(Exception):
        await data_store.insert(
            key=key,
            value=second_value,
            store_id=store_id,
            reference_node_hash=insert_result.node_hash,
            side=Side.RIGHT,
        )


@pytest.mark.anyio()
async def test_inserting_invalid_length_hash_raises_original_exception(
    data_store: DataStore,
) -> None:
    with pytest.raises(aiosqlite.IntegrityError):
        # casting since we are testing an invalid case
        await data_store._insert_node(
            node_hash=cast(bytes32, b"\x05"),
            node_type=NodeType.TERMINAL,
            left_hash=None,
            right_hash=None,
            key=b"\x06",
            value=b"\x07",
        )


@pytest.mark.anyio()
async def test_inserting_invalid_length_ancestor_hash_raises_original_exception(
    data_store: DataStore,
    store_id: bytes32,
) -> None:
    with pytest.raises(aiosqlite.IntegrityError):
        # casting since we are testing an invalid case
        await data_store._insert_ancestor_table(
            left_hash=bytes32(b"\x01" * 32),
            right_hash=bytes32(b"\x02" * 32),
            store_id=store_id,
            generation=0,
        )


@pytest.mark.anyio()
async def test_autoinsert_balances_from_scratch(data_store: DataStore, store_id: bytes32) -> None:
    random = Random()
    random.seed(100, version=2)
    hashes = []

    for i in range(2000):
        key = (i + 100).to_bytes(4, byteorder="big")
        value = (i + 200).to_bytes(4, byteorder="big")
        insert_result = await data_store.autoinsert(key, value, store_id, status=Status.COMMITTED)
        hashes.append(insert_result.node_hash)

    heights = {node_hash: len(await data_store.get_ancestors_optimized(node_hash, store_id)) for node_hash in hashes}
    too_tall = {hash: height for hash, height in heights.items() if height > 14}
    assert too_tall == {}
    assert 11 <= statistics.mean(heights.values()) <= 12


@pytest.mark.anyio()
async def test_autoinsert_balances_gaps(data_store: DataStore, store_id: bytes32) -> None:
    random = Random()
    random.seed(101, version=2)
    hashes = []

    for i in range(2000):
        key = (i + 100).to_bytes(4, byteorder="big")
        value = (i + 200).to_bytes(4, byteorder="big")
        if i == 0 or i > 10:
            insert_result = await data_store.autoinsert(key, value, store_id, status=Status.COMMITTED)
        else:
            reference_node_hash = await data_store.get_terminal_node_for_seed(store_id, bytes32([0] * 32))
            insert_result = await data_store.insert(
                key=key,
                value=value,
                store_id=store_id,
                reference_node_hash=reference_node_hash,
                side=Side.LEFT,
                status=Status.COMMITTED,
            )
            ancestors = await data_store.get_ancestors_optimized(insert_result.node_hash, store_id)
            assert len(ancestors) == i
        hashes.append(insert_result.node_hash)

    heights = {node_hash: len(await data_store.get_ancestors_optimized(node_hash, store_id)) for node_hash in hashes}
    too_tall = {hash: height for hash, height in heights.items() if height > 14}
    assert too_tall == {}
    assert 11 <= statistics.mean(heights.values()) <= 12


@pytest.mark.anyio()
async def test_delete_from_left_both_terminal(data_store: DataStore, store_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, store_id=store_id)

    expected = InternalNode.from_child_nodes(
        left=InternalNode.from_child_nodes(
            left=InternalNode.from_child_nodes(
                left=TerminalNode.from_key_value(key=b"\x00", value=b"\x10\x00"),
                right=TerminalNode.from_key_value(key=b"\x01", value=b"\x11\x01"),
            ),
            right=InternalNode.from_child_nodes(
                left=TerminalNode.from_key_value(key=b"\x02", value=b"\x12\x02"),
                right=TerminalNode.from_key_value(key=b"\x03", value=b"\x13\x03"),
            ),
        ),
        right=InternalNode.from_child_nodes(
            left=TerminalNode.from_key_value(key=b"\x05", value=b"\x15\x05"),
            right=InternalNode.from_child_nodes(
                left=TerminalNode.from_key_value(key=b"\x06", value=b"\x16\x06"),
                right=TerminalNode.from_key_value(key=b"\x07", value=b"\x17\x07"),
            ),
        ),
    )

    await data_store.delete(key=b"\x04", store_id=store_id, status=Status.COMMITTED)
    result = await data_store.get_tree_as_nodes(store_id=store_id)

    assert result == expected


@pytest.mark.anyio()
async def test_delete_from_left_other_not_terminal(data_store: DataStore, store_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, store_id=store_id)

    expected = InternalNode.from_child_nodes(
        left=InternalNode.from_child_nodes(
            left=InternalNode.from_child_nodes(
                left=TerminalNode.from_key_value(key=b"\x00", value=b"\x10\x00"),
                right=TerminalNode.from_key_value(key=b"\x01", value=b"\x11\x01"),
            ),
            right=InternalNode.from_child_nodes(
                left=TerminalNode.from_key_value(key=b"\x02", value=b"\x12\x02"),
                right=TerminalNode.from_key_value(key=b"\x03", value=b"\x13\x03"),
            ),
        ),
        right=InternalNode.from_child_nodes(
            left=TerminalNode.from_key_value(key=b"\x06", value=b"\x16\x06"),
            right=TerminalNode.from_key_value(key=b"\x07", value=b"\x17\x07"),
        ),
    )

    await data_store.delete(key=b"\x04", store_id=store_id, status=Status.COMMITTED)
    await data_store.delete(key=b"\x05", store_id=store_id, status=Status.COMMITTED)
    result = await data_store.get_tree_as_nodes(store_id=store_id)

    assert result == expected


@pytest.mark.anyio()
async def test_delete_from_right_both_terminal(data_store: DataStore, store_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, store_id=store_id)

    expected = InternalNode.from_child_nodes(
        left=InternalNode.from_child_nodes(
            left=InternalNode.from_child_nodes(
                left=TerminalNode.from_key_value(key=b"\x00", value=b"\x10\x00"),
                right=TerminalNode.from_key_value(key=b"\x01", value=b"\x11\x01"),
            ),
            right=TerminalNode.from_key_value(key=b"\x02", value=b"\x12\x02"),
        ),
        right=InternalNode.from_child_nodes(
            left=InternalNode.from_child_nodes(
                left=TerminalNode.from_key_value(key=b"\x04", value=b"\x14\x04"),
                right=TerminalNode.from_key_value(key=b"\x05", value=b"\x15\x05"),
            ),
            right=InternalNode.from_child_nodes(
                left=TerminalNode.from_key_value(key=b"\x06", value=b"\x16\x06"),
                right=TerminalNode.from_key_value(key=b"\x07", value=b"\x17\x07"),
            ),
        ),
    )

    await data_store.delete(key=b"\x03", store_id=store_id, status=Status.COMMITTED)
    result = await data_store.get_tree_as_nodes(store_id=store_id)

    assert result == expected


@pytest.mark.anyio()
async def test_delete_from_right_other_not_terminal(data_store: DataStore, store_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, store_id=store_id)

    expected = InternalNode.from_child_nodes(
        left=InternalNode.from_child_nodes(
            left=TerminalNode.from_key_value(key=b"\x00", value=b"\x10\x00"),
            right=TerminalNode.from_key_value(key=b"\x01", value=b"\x11\x01"),
        ),
        right=InternalNode.from_child_nodes(
            left=InternalNode.from_child_nodes(
                left=TerminalNode.from_key_value(key=b"\x04", value=b"\x14\x04"),
                right=TerminalNode.from_key_value(key=b"\x05", value=b"\x15\x05"),
            ),
            right=InternalNode.from_child_nodes(
                left=TerminalNode.from_key_value(key=b"\x06", value=b"\x16\x06"),
                right=TerminalNode.from_key_value(key=b"\x07", value=b"\x17\x07"),
            ),
        ),
    )

    await data_store.delete(key=b"\x03", store_id=store_id, status=Status.COMMITTED)
    await data_store.delete(key=b"\x02", store_id=store_id, status=Status.COMMITTED)
    result = await data_store.get_tree_as_nodes(store_id=store_id)

    assert result == expected


@pytest.mark.anyio
async def test_proof_of_inclusion_by_hash(data_store: DataStore, store_id: bytes32) -> None:
    """A proof of inclusion contains the expected sibling side, sibling hash, combined
    hash, key, value, and root hash values.
    """
    await add_01234567_example(data_store=data_store, store_id=store_id)
    root = await data_store.get_tree_root(store_id=store_id)
    assert root.node_hash is not None
    node = await data_store.get_node_by_key(key=b"\x04", store_id=store_id)

    proof = await data_store.get_proof_of_inclusion_by_hash(node_hash=node.hash, store_id=store_id)

    print(node)
    await _debug_dump(db=data_store.db_wrapper)

    expected_layers = [
        ProofOfInclusionLayer(
            other_hash_side=Side.RIGHT,
            other_hash=bytes32.fromhex("fb66fe539b3eb2020dfbfadfd601fa318521292b41f04c2057c16fca6b947ca1"),
            combined_hash=bytes32.fromhex("36cb1fc56017944213055da8cb0178fb0938c32df3ec4472f5edf0dff85ba4a3"),
        ),
        ProofOfInclusionLayer(
            other_hash_side=Side.RIGHT,
            other_hash=bytes32.fromhex("6d3af8d93db948e8b6aa4386958e137c6be8bab726db86789594b3588b35adcd"),
            combined_hash=bytes32.fromhex("5f67a0ab1976e090b834bf70e5ce2a0f0a9cd474e19a905348c44ae12274d30b"),
        ),
        ProofOfInclusionLayer(
            other_hash_side=Side.LEFT,
            other_hash=bytes32.fromhex("c852ecd8fb61549a0a42f9eb9dde65e6c94a01934dbd9c1d35ab94e2a0ae58e2"),
            combined_hash=bytes32.fromhex("7a5193a4e31a0a72f6623dfeb2876022ab74a48abb5966088a1c6f5451cc5d81"),
        ),
    ]

    assert proof == ProofOfInclusion(node_hash=node.hash, layers=expected_layers)


@pytest.mark.anyio
async def test_proof_of_inclusion_by_hash_no_ancestors(data_store: DataStore, store_id: bytes32) -> None:
    """Check proper proof of inclusion creation when the node being proved is the root."""
    await data_store.autoinsert(key=b"\x04", value=b"\x03", store_id=store_id, status=Status.COMMITTED)
    root = await data_store.get_tree_root(store_id=store_id)
    assert root.node_hash is not None
    node = await data_store.get_node_by_key(key=b"\x04", store_id=store_id)

    proof = await data_store.get_proof_of_inclusion_by_hash(node_hash=node.hash, store_id=store_id)

    assert proof == ProofOfInclusion(node_hash=node.hash, layers=[])


@pytest.mark.anyio
async def test_proof_of_inclusion_by_hash_program(data_store: DataStore, store_id: bytes32) -> None:
    """The proof of inclusion program has the expected Python equivalence."""

    await add_01234567_example(data_store=data_store, store_id=store_id)
    node = await data_store.get_node_by_key(key=b"\x04", store_id=store_id)

    proof = await data_store.get_proof_of_inclusion_by_hash(node_hash=node.hash, store_id=store_id)

    assert proof.as_program() == [
        b"\x04",
        [
            bytes32.fromhex("fb66fe539b3eb2020dfbfadfd601fa318521292b41f04c2057c16fca6b947ca1"),
            bytes32.fromhex("6d3af8d93db948e8b6aa4386958e137c6be8bab726db86789594b3588b35adcd"),
            bytes32.fromhex("c852ecd8fb61549a0a42f9eb9dde65e6c94a01934dbd9c1d35ab94e2a0ae58e2"),
        ],
    ]


@pytest.mark.anyio
async def test_proof_of_inclusion_by_hash_equals_by_key(data_store: DataStore, store_id: bytes32) -> None:
    """The proof of inclusion is equal between hash and key requests."""

    await add_01234567_example(data_store=data_store, store_id=store_id)
    node = await data_store.get_node_by_key(key=b"\x04", store_id=store_id)

    proof_by_hash = await data_store.get_proof_of_inclusion_by_hash(node_hash=node.hash, store_id=store_id)
    proof_by_key = await data_store.get_proof_of_inclusion_by_key(key=b"\x04", store_id=store_id)

    assert proof_by_hash == proof_by_key


@pytest.mark.anyio
async def test_proof_of_inclusion_by_hash_bytes(data_store: DataStore, store_id: bytes32) -> None:
    """The proof of inclusion provided by the data store is able to be converted to a
    program and subsequently to bytes.
    """
    await add_01234567_example(data_store=data_store, store_id=store_id)
    node = await data_store.get_node_by_key(key=b"\x04", store_id=store_id)

    proof = await data_store.get_proof_of_inclusion_by_hash(node_hash=node.hash, store_id=store_id)

    expected = (
        b"\xff\x04\xff\xff\xa0\xfbf\xfeS\x9b>\xb2\x02\r\xfb\xfa\xdf\xd6\x01\xfa1\x85!)"
        b"+A\xf0L W\xc1o\xcak\x94|\xa1\xff\xa0m:\xf8\xd9=\xb9H\xe8\xb6\xaaC\x86\x95"
        b"\x8e\x13|k\xe8\xba\xb7&\xdb\x86x\x95\x94\xb3X\x8b5\xad\xcd\xff\xa0\xc8R\xec"
        b"\xd8\xfbaT\x9a\nB\xf9\xeb\x9d\xdee\xe6\xc9J\x01\x93M\xbd\x9c\x1d5\xab\x94"
        b"\xe2\xa0\xaeX\xe2\x80\x80"
    )

    assert bytes(proof.as_program()) == expected


# @pytest.mark.anyio
# async def test_create_first_pair(data_store: DataStore, store_id: bytes) -> None:
#     key = SExp.to([1, 2])
#     value = SExp.to(b'abc')
#
#     root_hash = await data_store.create_root(store_id=store_id)
#
#
#     await data_store.create_pair(key=key, value=value)


def test_all_checks_collected() -> None:
    expected = {value for name, value in vars(DataStore).items() if name.startswith("_check_") and callable(value)}

    assert set(DataStore._checks) == expected


a_bytes_32 = bytes32(range(32))
another_bytes_32 = bytes(reversed(a_bytes_32))

valid_program_hex = Program.to((b"abc", 2)).as_bin().hex()
invalid_program_hex = b"\xab\xcd".hex()


@pytest.mark.anyio
async def test_check_roots_are_incrementing_missing_zero(raw_data_store: DataStore) -> None:
    store_id = hexstr_to_bytes("c954ab71ffaf5b0f129b04b35fdc7c84541f4375167e730e2646bfcfdb7cf2cd")

    async with raw_data_store.db_wrapper.writer() as writer:
        for generation in range(1, 5):
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                {
                    "tree_id": store_id,
                    "generation": generation,
                    "node_hash": None,
                    "status": Status.COMMITTED.value,
                },
            )

    with pytest.raises(
        TreeGenerationIncrementingError,
        match=r"\n +c954ab71ffaf5b0f129b04b35fdc7c84541f4375167e730e2646bfcfdb7cf2cd$",
    ):
        await raw_data_store._check_roots_are_incrementing()


@pytest.mark.anyio
async def test_check_roots_are_incrementing_gap(raw_data_store: DataStore) -> None:
    store_id = hexstr_to_bytes("c954ab71ffaf5b0f129b04b35fdc7c84541f4375167e730e2646bfcfdb7cf2cd")

    async with raw_data_store.db_wrapper.writer() as writer:
        for generation in [*range(5), *range(6, 10)]:
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                {
                    "tree_id": store_id,
                    "generation": generation,
                    "node_hash": None,
                    "status": Status.COMMITTED.value,
                },
            )

    with pytest.raises(
        TreeGenerationIncrementingError,
        match=r"\n +c954ab71ffaf5b0f129b04b35fdc7c84541f4375167e730e2646bfcfdb7cf2cd$",
    ):
        await raw_data_store._check_roots_are_incrementing()


@pytest.mark.anyio
async def test_check_hashes_internal(raw_data_store: DataStore) -> None:
    async with raw_data_store.db_wrapper.writer() as writer:
        await writer.execute(
            "INSERT INTO node(hash, node_type, left, right) VALUES(:hash, :node_type, :left, :right)",
            {
                "hash": a_bytes_32,
                "node_type": NodeType.INTERNAL,
                "left": a_bytes_32,
                "right": a_bytes_32,
            },
        )

    with pytest.raises(
        NodeHashError,
        match=r"\n +000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f$",
    ):
        await raw_data_store._check_hashes()


@pytest.mark.anyio
async def test_check_hashes_terminal(raw_data_store: DataStore) -> None:
    async with raw_data_store.db_wrapper.writer() as writer:
        await writer.execute(
            "INSERT INTO node(hash, node_type, key, value) VALUES(:hash, :node_type, :key, :value)",
            {
                "hash": a_bytes_32,
                "node_type": NodeType.TERMINAL,
                "key": Program.to((1, 2)).as_bin(),
                "value": Program.to((1, 2)).as_bin(),
            },
        )

    with pytest.raises(
        NodeHashError,
        match=r"\n +000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f$",
    ):
        await raw_data_store._check_hashes()


@pytest.mark.anyio
async def test_root_state(data_store: DataStore, store_id: bytes32) -> None:
    key = b"\x01\x02"
    value = b"abc"
    await data_store.insert(
        key=key, value=value, store_id=store_id, reference_node_hash=None, side=None, status=Status.PENDING
    )
    is_empty = await data_store.table_is_empty(store_id=store_id)
    assert is_empty


@pytest.mark.anyio
async def test_change_root_state(data_store: DataStore, store_id: bytes32) -> None:
    key = b"\x01\x02"
    value = b"abc"
    await data_store.insert(
        key=key,
        value=value,
        store_id=store_id,
        reference_node_hash=None,
        side=None,
    )
    root = await data_store.get_pending_root(store_id)
    assert root is not None
    assert root.status == Status.PENDING
    is_empty = await data_store.table_is_empty(store_id=store_id)
    assert is_empty

    await data_store.change_root_status(root, Status.PENDING_BATCH)
    root = await data_store.get_pending_root(store_id)
    assert root is not None
    assert root.status == Status.PENDING_BATCH
    is_empty = await data_store.table_is_empty(store_id=store_id)
    assert is_empty

    await data_store.change_root_status(root, Status.COMMITTED)
    root = await data_store.get_tree_root(store_id)
    is_empty = await data_store.table_is_empty(store_id=store_id)
    assert not is_empty
    assert root.node_hash is not None
    root = await data_store.get_pending_root(store_id)
    assert root is None


@pytest.mark.anyio
async def test_kv_diff(data_store: DataStore, store_id: bytes32) -> None:
    random = Random()
    random.seed(100, version=2)
    insertions = 0
    expected_diff: Set[DiffData] = set()
    root_start = None
    for i in range(500):
        key = (i + 100).to_bytes(4, byteorder="big")
        value = (i + 200).to_bytes(4, byteorder="big")
        seed = leaf_hash(key=key, value=value)
        node_hash = await data_store.get_terminal_node_for_seed(store_id, seed)
        if random.randint(0, 4) > 0 or insertions < 10:
            insertions += 1
            side = None if node_hash is None else data_store.get_side_for_seed(seed)

            await data_store.insert(
                key=key,
                value=value,
                store_id=store_id,
                reference_node_hash=node_hash,
                side=side,
                status=Status.COMMITTED,
            )
            if i > 200:
                expected_diff.add(DiffData(OperationType.INSERT, key, value))
        else:
            assert node_hash is not None
            node = await data_store.get_node(node_hash)
            assert isinstance(node, TerminalNode)
            await data_store.delete(key=node.key, store_id=store_id, status=Status.COMMITTED)
            if i > 200:
                if DiffData(OperationType.INSERT, node.key, node.value) in expected_diff:
                    expected_diff.remove(DiffData(OperationType.INSERT, node.key, node.value))
                else:
                    expected_diff.add(DiffData(OperationType.DELETE, node.key, node.value))
        if i == 200:
            root_start = await data_store.get_tree_root(store_id)

    root_end = await data_store.get_tree_root(store_id)
    assert root_start is not None
    assert root_start.node_hash is not None
    assert root_end.node_hash is not None
    diffs = await data_store.get_kv_diff(store_id, root_start.node_hash, root_end.node_hash)
    assert diffs == expected_diff


@pytest.mark.anyio
async def test_kv_diff_2(data_store: DataStore, store_id: bytes32) -> None:
    insert_result = await data_store.insert(
        key=b"000",
        value=b"000",
        store_id=store_id,
        reference_node_hash=None,
        side=None,
    )
    empty_hash = bytes32([0] * 32)
    invalid_hash = bytes32([0] * 31 + [1])
    diff_1 = await data_store.get_kv_diff(store_id, empty_hash, insert_result.node_hash)
    assert diff_1 == {DiffData(OperationType.INSERT, b"000", b"000")}
    diff_2 = await data_store.get_kv_diff(store_id, insert_result.node_hash, empty_hash)
    assert diff_2 == {DiffData(OperationType.DELETE, b"000", b"000")}
    with pytest.raises(Exception, match=f"Unable to diff: Can't find keys and values for {invalid_hash.hex()}"):
        await data_store.get_kv_diff(store_id, invalid_hash, insert_result.node_hash)
    with pytest.raises(Exception, match=f"Unable to diff: Can't find keys and values for {invalid_hash.hex()}"):
        await data_store.get_kv_diff(store_id, insert_result.node_hash, invalid_hash)


@pytest.mark.anyio
async def test_kv_diff_3(data_store: DataStore, store_id: bytes32) -> None:
    insert_result = await data_store.autoinsert(
        key=b"000",
        value=b"000",
        store_id=store_id,
        status=Status.COMMITTED,
    )
    await data_store.delete(store_id=store_id, key=b"000", status=Status.COMMITTED)
    insert_result_2 = await data_store.autoinsert(
        key=b"000",
        value=b"001",
        store_id=store_id,
        status=Status.COMMITTED,
    )
    diff_1 = await data_store.get_kv_diff(store_id, insert_result.node_hash, insert_result_2.node_hash)
    assert diff_1 == {DiffData(OperationType.DELETE, b"000", b"000"), DiffData(OperationType.INSERT, b"000", b"001")}
    insert_result_3 = await data_store.upsert(
        key=b"000",
        new_value=b"002",
        store_id=store_id,
        status=Status.COMMITTED,
    )
    diff_2 = await data_store.get_kv_diff(store_id, insert_result_2.node_hash, insert_result_3.node_hash)
    assert diff_2 == {DiffData(OperationType.DELETE, b"000", b"001"), DiffData(OperationType.INSERT, b"000", b"002")}


@pytest.mark.anyio
async def test_rollback_to_generation(data_store: DataStore, store_id: bytes32) -> None:
    await add_0123_example(data_store, store_id)
    expected_hashes = []
    roots = await data_store.get_roots_between(store_id, 1, 5)
    for generation, root in enumerate(roots):
        expected_hashes.append((generation + 1, root.node_hash))
    for generation, expected_hash in reversed(expected_hashes):
        await data_store.rollback_to_generation(store_id, generation)
        root = await data_store.get_tree_root(store_id)
        assert root.node_hash == expected_hash


@pytest.mark.anyio
async def test_subscribe_unsubscribe(data_store: DataStore, store_id: bytes32) -> None:
    await data_store.subscribe(Subscription(store_id, [ServerInfo("http://127:0:0:1/8000", 1, 1)]))
    subscriptions = await data_store.get_subscriptions()
    urls = [server_info.url for subscription in subscriptions for server_info in subscription.servers_info]
    assert urls == ["http://127:0:0:1/8000"]

    await data_store.subscribe(Subscription(store_id, [ServerInfo("http://127:0:0:1/8001", 2, 2)]))
    subscriptions = await data_store.get_subscriptions()
    urls = [server_info.url for subscription in subscriptions for server_info in subscription.servers_info]
    assert urls == ["http://127:0:0:1/8000", "http://127:0:0:1/8001"]

    await data_store.subscribe(
        Subscription(
            store_id, [ServerInfo("http://127:0:0:1/8000", 100, 100), ServerInfo("http://127:0:0:1/8001", 200, 200)]
        )
    )
    subscriptions = await data_store.get_subscriptions()
    assert subscriptions == [
        Subscription(store_id, [ServerInfo("http://127:0:0:1/8000", 1, 1), ServerInfo("http://127:0:0:1/8001", 2, 2)]),
    ]

    await data_store.unsubscribe(store_id)
    assert await data_store.get_subscriptions() == []
    store_id2 = bytes32([0] * 32)

    await data_store.subscribe(
        Subscription(
            store_id, [ServerInfo("http://127:0:0:1/8000", 100, 100), ServerInfo("http://127:0:0:1/8001", 200, 200)]
        )
    )
    await data_store.subscribe(
        Subscription(
            store_id2, [ServerInfo("http://127:0:0:1/8000", 300, 300), ServerInfo("http://127:0:0:1/8001", 400, 400)]
        )
    )
    subscriptions = await data_store.get_subscriptions()
    assert subscriptions == [
        Subscription(
            store_id, [ServerInfo("http://127:0:0:1/8000", 100, 100), ServerInfo("http://127:0:0:1/8001", 200, 200)]
        ),
        Subscription(
            store_id2, [ServerInfo("http://127:0:0:1/8000", 300, 300), ServerInfo("http://127:0:0:1/8001", 400, 400)]
        ),
    ]


@pytest.mark.anyio
async def test_server_selection(data_store: DataStore, store_id: bytes32) -> None:
    start_timestamp = 1000
    await data_store.subscribe(
        Subscription(store_id, [ServerInfo(f"http://127.0.0.1/{port}", 0, 0) for port in range(8000, 8010)])
    )

    free_servers = {f"http://127.0.0.1/{port}" for port in range(8000, 8010)}
    tried_servers = 0
    random = Random()
    random.seed(100, version=2)
    while len(free_servers) > 0:
        servers_info = await data_store.get_available_servers_for_store(store_id=store_id, timestamp=start_timestamp)
        random.shuffle(servers_info)
        assert servers_info != []
        server_info = servers_info[0]
        assert server_info.ignore_till == 0
        await data_store.received_incorrect_file(store_id=store_id, server_info=server_info, timestamp=start_timestamp)
        assert server_info.url in free_servers
        tried_servers += 1
        free_servers.remove(server_info.url)

    assert tried_servers == 10
    servers_info = await data_store.get_available_servers_for_store(store_id=store_id, timestamp=start_timestamp)
    assert servers_info == []

    current_timestamp = 2000 + 7 * 24 * 3600
    selected_servers = set()
    for _ in range(100):
        servers_info = await data_store.get_available_servers_for_store(store_id=store_id, timestamp=current_timestamp)
        random.shuffle(servers_info)
        assert servers_info != []
        selected_servers.add(servers_info[0].url)
    assert selected_servers == {f"http://127.0.0.1/{port}" for port in range(8000, 8010)}

    for _ in range(100):
        servers_info = await data_store.get_available_servers_for_store(store_id=store_id, timestamp=current_timestamp)
        random.shuffle(servers_info)
        assert servers_info != []
        if servers_info[0].url != "http://127.0.0.1/8000":
            await data_store.received_incorrect_file(
                store_id=store_id, server_info=servers_info[0], timestamp=current_timestamp
            )

    servers_info = await data_store.get_available_servers_for_store(store_id=store_id, timestamp=current_timestamp)
    random.shuffle(servers_info)
    assert len(servers_info) == 1
    assert servers_info[0].url == "http://127.0.0.1/8000"
    await data_store.received_correct_file(store_id=store_id, server_info=servers_info[0])

    ban_times = [5 * 60] * 3 + [15 * 60] * 3 + [30 * 60] * 2 + [60 * 60] * 10
    for ban_time in ban_times:
        servers_info = await data_store.get_available_servers_for_store(store_id=store_id, timestamp=current_timestamp)
        assert len(servers_info) == 1
        await data_store.server_misses_file(store_id=store_id, server_info=servers_info[0], timestamp=current_timestamp)
        current_timestamp += ban_time
        servers_info = await data_store.get_available_servers_for_store(store_id=store_id, timestamp=current_timestamp)
        assert servers_info == []
        current_timestamp += 1


@pytest.mark.parametrize(
    "error",
    [True, False],
)
@pytest.mark.anyio
async def test_server_http_ban(
    data_store: DataStore,
    store_id: bytes32,
    error: bool,
    monkeypatch: Any,
    tmp_path: Path,
    seeded_random: random.Random,
) -> None:
    sinfo = ServerInfo("http://127.0.0.1/8003", 0, 0)
    await data_store.subscribe(Subscription(store_id, [sinfo]))

    async def mock_http_download(
        target_filename_path: Path,
        filename: str,
        proxy_url: str,
        server_info: ServerInfo,
        timeout: aiohttp.ClientTimeout,
        log: logging.Logger,
    ) -> None:
        if error:
            raise aiohttp.ClientConnectionError()

    start_timestamp = int(time.time())
    with monkeypatch.context() as m:
        m.setattr("chia.data_layer.download_data.http_download", mock_http_download)
        success = await insert_from_delta_file(
            data_store=data_store,
            store_id=store_id,
            existing_generation=3,
            root_hashes=[bytes32.random(seeded_random)],
            server_info=sinfo,
            client_foldername=tmp_path,
            timeout=aiohttp.ClientTimeout(total=15, sock_connect=5),
            log=log,
            proxy_url="",
            downloader=None,
        )

    assert success is False

    subscriptions = await data_store.get_subscriptions()
    sinfo = subscriptions[0].servers_info[0]
    assert sinfo.num_consecutive_failures == 1
    assert sinfo.ignore_till >= start_timestamp + 5 * 60  # ban for 5 minutes
    start_timestamp = sinfo.ignore_till

    with monkeypatch.context() as m:
        m.setattr("chia.data_layer.download_data.http_download", mock_http_download)
        success = await insert_from_delta_file(
            data_store=data_store,
            store_id=store_id,
            existing_generation=3,
            root_hashes=[bytes32.random(seeded_random)],
            server_info=sinfo,
            client_foldername=tmp_path,
            timeout=aiohttp.ClientTimeout(total=15, sock_connect=5),
            log=log,
            proxy_url="",
            downloader=None,
        )

    subscriptions = await data_store.get_subscriptions()
    sinfo = subscriptions[0].servers_info[0]
    assert sinfo.num_consecutive_failures == 2
    assert sinfo.ignore_till == start_timestamp  # we don't increase on second failure


@pytest.mark.parametrize(
    "test_delta",
    [True, False],
)
@boolean_datacases(name="group_files_by_store", false="group by singleton", true="don't group by singleton")
@pytest.mark.anyio
async def test_data_server_files(
    data_store: DataStore,
    store_id: bytes32,
    test_delta: bool,
    group_files_by_store: bool,
    tmp_path: Path,
) -> None:
    roots: List[Root] = []
    num_batches = 10
    num_ops_per_batch = 100

    db_uri = generate_in_memory_db_uri()
    async with DataStore.managed(database=db_uri, uri=True) as data_store_server:
        await data_store_server.create_tree(store_id, status=Status.COMMITTED)
        random = Random()
        random.seed(100, version=2)

        keys: List[bytes] = []
        counter = 0

        for batch in range(num_batches):
            changelist: List[Dict[str, Any]] = []
            for operation in range(num_ops_per_batch):
                if random.randint(0, 4) > 0 or len(keys) == 0:
                    key = counter.to_bytes(4, byteorder="big")
                    value = (2 * counter).to_bytes(4, byteorder="big")
                    keys.append(key)
                    changelist.append({"action": "insert", "key": key, "value": value})
                else:
                    key = random.choice(keys)
                    keys.remove(key)
                    changelist.append({"action": "delete", "key": key})
                counter += 1
            await data_store_server.insert_batch(store_id, changelist, status=Status.COMMITTED)
            root = await data_store_server.get_tree_root(store_id)
            await write_files_for_root(
                data_store_server, store_id, root, tmp_path, 0, group_by_store=group_files_by_store
            )
            roots.append(root)

    generation = 1
    assert len(roots) == num_batches
    for root in roots:
        assert root.node_hash is not None
        if not test_delta:
            filename = get_full_tree_filename_path(tmp_path, store_id, root.node_hash, generation, group_files_by_store)
            assert filename.exists()
        else:
            filename = get_delta_filename_path(tmp_path, store_id, root.node_hash, generation, group_files_by_store)
            assert filename.exists()
        await insert_into_data_store_from_file(data_store, store_id, root.node_hash, tmp_path.joinpath(filename))
        current_root = await data_store.get_tree_root(store_id=store_id)
        assert current_root.node_hash == root.node_hash
        generation += 1


@pytest.mark.anyio
@pytest.mark.parametrize("pending_status", [Status.PENDING, Status.PENDING_BATCH])
async def test_pending_roots(data_store: DataStore, store_id: bytes32, pending_status: Status) -> None:
    key = b"\x01\x02"
    value = b"abc"

    await data_store.insert(
        key=key,
        value=value,
        store_id=store_id,
        reference_node_hash=None,
        side=None,
        status=Status.COMMITTED,
    )

    key = b"\x01\x03"
    value = b"abc"

    await data_store.autoinsert(
        key=key,
        value=value,
        store_id=store_id,
        status=pending_status,
    )
    pending_root = await data_store.get_pending_root(store_id=store_id)
    assert pending_root is not None
    assert pending_root.generation == 2 and pending_root.status == pending_status

    await data_store.clear_pending_roots(store_id=store_id)
    pending_root = await data_store.get_pending_root(store_id=store_id)
    assert pending_root is None


@pytest.mark.anyio
@pytest.mark.parametrize("pending_status", [Status.PENDING, Status.PENDING_BATCH])
async def test_clear_pending_roots_returns_root(
    data_store: DataStore, store_id: bytes32, pending_status: Status
) -> None:
    key = b"\x01\x02"
    value = b"abc"

    await data_store.insert(
        key=key,
        value=value,
        store_id=store_id,
        reference_node_hash=None,
        side=None,
        status=pending_status,
    )

    pending_root = await data_store.get_pending_root(store_id=store_id)
    cleared_root = await data_store.clear_pending_roots(store_id=store_id)
    assert cleared_root == pending_root


@dataclass
class BatchInsertBenchmarkCase:
    pre: int
    count: int
    limit: float
    marks: Marks = ()

    @property
    def id(self) -> str:
        return f"pre={self.pre},count={self.count}"


@dataclass
class BatchesInsertBenchmarkCase:
    count: int
    batch_count: int
    limit: float
    marks: Marks = ()

    @property
    def id(self) -> str:
        return f"count={self.count},batch_count={self.batch_count}"


@datacases(
    BatchInsertBenchmarkCase(
        pre=0,
        count=100,
        limit=2.2,
    ),
    BatchInsertBenchmarkCase(
        pre=1_000,
        count=100,
        limit=4,
    ),
    BatchInsertBenchmarkCase(
        pre=0,
        count=1_000,
        limit=30,
    ),
    BatchInsertBenchmarkCase(
        pre=1_000,
        count=1_000,
        limit=36,
    ),
    BatchInsertBenchmarkCase(
        pre=10_000,
        count=25_000,
        limit=52,
    ),
)
@pytest.mark.anyio
async def test_benchmark_batch_insert_speed(
    data_store: DataStore,
    store_id: bytes32,
    benchmark_runner: BenchmarkRunner,
    case: BatchInsertBenchmarkCase,
) -> None:
    r = random.Random()
    r.seed("shadowlands", version=2)

    changelist = [
        {
            "action": "insert",
            "key": x.to_bytes(32, byteorder="big", signed=False),
            "value": bytes(r.getrandbits(8) for _ in range(1200)),
        }
        for x in range(case.pre + case.count)
    ]

    pre = changelist[: case.pre]
    batch = changelist[case.pre : case.pre + case.count]

    if case.pre > 0:
        await data_store.insert_batch(
            store_id=store_id,
            changelist=pre,
            status=Status.COMMITTED,
        )

    with benchmark_runner.assert_runtime(seconds=case.limit):
        await data_store.insert_batch(
            store_id=store_id,
            changelist=batch,
        )


@datacases(
    BatchesInsertBenchmarkCase(
        count=50,
        batch_count=200,
        limit=195,
    ),
)
@pytest.mark.anyio
async def test_benchmark_batch_insert_speed_multiple_batches(
    data_store: DataStore,
    store_id: bytes32,
    benchmark_runner: BenchmarkRunner,
    case: BatchesInsertBenchmarkCase,
) -> None:
    r = random.Random()
    r.seed("shadowlands", version=2)

    with benchmark_runner.assert_runtime(seconds=case.limit):
        for batch in range(case.batch_count):
            changelist = [
                {
                    "action": "insert",
                    "key": x.to_bytes(32, byteorder="big", signed=False),
                    "value": bytes(r.getrandbits(8) for _ in range(10000)),
                }
                for x in range(batch * case.count, (batch + 1) * case.count)
            ]
            await data_store.insert_batch(
                store_id=store_id,
                changelist=changelist,
                status=Status.COMMITTED,
            )


@pytest.mark.anyio
async def test_delete_store_data(raw_data_store: DataStore) -> None:
    store_id = bytes32(b"\0" * 32)
    store_id_2 = bytes32(b"\0" * 31 + b"\1")
    await raw_data_store.create_tree(store_id=store_id, status=Status.COMMITTED)
    await raw_data_store.create_tree(store_id=store_id_2, status=Status.COMMITTED)
    total_keys = 4
    keys = [key.to_bytes(4, byteorder="big") for key in range(total_keys)]
    batch1 = [
        {"action": "insert", "key": keys[0], "value": keys[0]},
        {"action": "insert", "key": keys[1], "value": keys[1]},
    ]
    batch2 = batch1.copy()
    batch1.append({"action": "insert", "key": keys[2], "value": keys[2]})
    batch2.append({"action": "insert", "key": keys[3], "value": keys[3]})
    assert batch1 != batch2
    await raw_data_store.insert_batch(store_id, batch1, status=Status.COMMITTED)
    await raw_data_store.insert_batch(store_id_2, batch2, status=Status.COMMITTED)
    keys_values_before = await raw_data_store.get_keys_values(store_id_2)
    async with raw_data_store.db_wrapper.reader() as reader:
        result = await reader.execute("SELECT * FROM node")
        nodes = await result.fetchall()
        kv_nodes_before = {}
        for node in nodes:
            if node["key"] is not None:
                kv_nodes_before[node["key"]] = node["value"]
    assert [kv_nodes_before[key] for key in keys] == keys
    await raw_data_store.delete_store_data(store_id)
    # Deleting from `node` table doesn't alter other stores.
    keys_values_after = await raw_data_store.get_keys_values(store_id_2)
    assert keys_values_before == keys_values_after
    async with raw_data_store.db_wrapper.reader() as reader:
        result = await reader.execute("SELECT * FROM node")
        nodes = await result.fetchall()
        kv_nodes_after = {}
        for node in nodes:
            if node["key"] is not None:
                kv_nodes_after[node["key"]] = node["value"]
    for i in range(total_keys):
        if i != 2:
            assert kv_nodes_after[keys[i]] == keys[i]
        else:
            # `keys[2]` was only present in the first store.
            assert keys[i] not in kv_nodes_after
    assert not await raw_data_store.store_id_exists(store_id)
    await raw_data_store.delete_store_data(store_id_2)
    async with raw_data_store.db_wrapper.reader() as reader:
        async with reader.execute("SELECT COUNT(*) FROM node") as cursor:
            row_count = await cursor.fetchone()
            assert row_count is not None
            assert row_count[0] == 0
    assert not await raw_data_store.store_id_exists(store_id_2)


@pytest.mark.anyio
async def test_delete_store_data_multiple_stores(raw_data_store: DataStore) -> None:
    # Make sure inserting and deleting the same data works
    for repetition in range(2):
        num_stores = 50
        total_keys = 150
        keys_deleted_per_store = 3
        store_ids = [bytes32(i.to_bytes(32, byteorder="big")) for i in range(num_stores)]
        for store_id in store_ids:
            await raw_data_store.create_tree(store_id=store_id, status=Status.COMMITTED)
        original_keys = [key.to_bytes(4, byteorder="big") for key in range(total_keys)]
        batches = []
        for i in range(num_stores):
            batch = [
                {"action": "insert", "key": key, "value": key} for key in original_keys[i * keys_deleted_per_store :]
            ]
            batches.append(batch)

        for store_id, batch in zip(store_ids, batches):
            await raw_data_store.insert_batch(store_id, batch, status=Status.COMMITTED)

        for tree_index in range(num_stores):
            async with raw_data_store.db_wrapper.reader() as reader:
                result = await reader.execute("SELECT * FROM node")
                nodes = await result.fetchall()

            keys = {node["key"] for node in nodes if node["key"] is not None}
            assert len(keys) == total_keys - tree_index * keys_deleted_per_store
            keys_after_index = set(original_keys[tree_index * keys_deleted_per_store :])
            keys_before_index = set(original_keys[: tree_index * keys_deleted_per_store])
            assert keys_after_index.issubset(keys)
            assert keys.isdisjoint(keys_before_index)
            await raw_data_store.delete_store_data(store_ids[tree_index])

        async with raw_data_store.db_wrapper.reader() as reader:
            async with reader.execute("SELECT COUNT(*) FROM node") as cursor:
                row_count = await cursor.fetchone()
                assert row_count is not None
                assert row_count[0] == 0


@pytest.mark.parametrize("common_keys_count", [1, 250, 499])
@pytest.mark.anyio
async def test_delete_store_data_with_common_values(raw_data_store: DataStore, common_keys_count: int) -> None:
    store_id_1 = bytes32(b"\x00" * 31 + b"\x01")
    store_id_2 = bytes32(b"\x00" * 31 + b"\x02")

    await raw_data_store.create_tree(store_id=store_id_1, status=Status.COMMITTED)
    await raw_data_store.create_tree(store_id=store_id_2, status=Status.COMMITTED)

    key_offset = 1000
    total_keys_per_store = 500
    assert common_keys_count < key_offset
    common_keys = {key.to_bytes(4, byteorder="big") for key in range(common_keys_count)}
    unique_keys_1 = {
        (key + key_offset).to_bytes(4, byteorder="big") for key in range(total_keys_per_store - common_keys_count)
    }
    unique_keys_2 = {
        (key + (2 * key_offset)).to_bytes(4, byteorder="big") for key in range(total_keys_per_store - common_keys_count)
    }

    batch1 = [{"action": "insert", "key": key, "value": key} for key in common_keys.union(unique_keys_1)]
    batch2 = [{"action": "insert", "key": key, "value": key} for key in common_keys.union(unique_keys_2)]

    await raw_data_store.insert_batch(store_id_1, batch1, status=Status.COMMITTED)
    await raw_data_store.insert_batch(store_id_2, batch2, status=Status.COMMITTED)

    await raw_data_store.delete_store_data(store_id_1)
    async with raw_data_store.db_wrapper.reader() as reader:
        result = await reader.execute("SELECT * FROM node")
        nodes = await result.fetchall()

    keys = {node["key"] for node in nodes if node["key"] is not None}
    # Since one store got all its keys deleted, we're left only with the keys of the other store.
    assert len(keys) == total_keys_per_store
    assert keys.intersection(unique_keys_1) == set()
    assert keys.symmetric_difference(common_keys.union(unique_keys_2)) == set()


@pytest.mark.anyio
@pytest.mark.parametrize("pending_status", [Status.PENDING, Status.PENDING_BATCH])
async def test_delete_store_data_protects_pending_roots(raw_data_store: DataStore, pending_status: Status) -> None:
    num_stores = 5
    total_keys = 15
    store_ids = [bytes32(i.to_bytes(32, byteorder="big")) for i in range(num_stores)]
    for store_id in store_ids:
        await raw_data_store.create_tree(store_id=store_id, status=Status.COMMITTED)
    original_keys = [key.to_bytes(4, byteorder="big") for key in range(total_keys)]
    batches = []
    keys_per_pending_root = 2

    for i in range(num_stores - 1):
        start_index = i * keys_per_pending_root
        end_index = (i + 1) * keys_per_pending_root
        batch = [{"action": "insert", "key": key, "value": key} for key in original_keys[start_index:end_index]]
        batches.append(batch)
    for store_id, batch in zip(store_ids, batches):
        await raw_data_store.insert_batch(store_id, batch, status=pending_status)

    store_id = store_ids[-1]
    batch = [{"action": "insert", "key": key, "value": key} for key in original_keys]
    await raw_data_store.insert_batch(store_id, batch, status=Status.COMMITTED)

    async with raw_data_store.db_wrapper.reader() as reader:
        result = await reader.execute("SELECT * FROM node")
        nodes = await result.fetchall()

    keys = {node["key"] for node in nodes if node["key"] is not None}
    assert keys == set(original_keys)

    await raw_data_store.delete_store_data(store_id)
    async with raw_data_store.db_wrapper.reader() as reader:
        result = await reader.execute("SELECT * FROM node")
        nodes = await result.fetchall()

    keys = {node["key"] for node in nodes if node["key"] is not None}
    assert keys == set(original_keys[: (num_stores - 1) * keys_per_pending_root])

    for index in range(num_stores - 1):
        store_id = store_ids[index]
        root = await raw_data_store.get_pending_root(store_id)
        assert root is not None
        await raw_data_store.change_root_status(root, Status.COMMITTED)
        kv = await raw_data_store.get_keys_values(store_id=store_id)
        start_index = index * keys_per_pending_root
        end_index = (index + 1) * keys_per_pending_root
        assert {pair.key for pair in kv} == set(original_keys[start_index:end_index])


@pytest.mark.anyio
@boolean_datacases(name="group_files_by_store", true="group by singleton", false="don't group by singleton")
async def test_insert_from_delta_file(
    data_store: DataStore,
    store_id: bytes32,
    monkeypatch: Any,
    tmp_path: Path,
    seeded_random: random.Random,
    group_files_by_store: bool,
) -> None:
    await data_store.create_tree(store_id=store_id, status=Status.COMMITTED)
    num_files = 5
    for generation in range(num_files):
        key = generation.to_bytes(4, byteorder="big")
        value = generation.to_bytes(4, byteorder="big")
        await data_store.autoinsert(
            key=key,
            value=value,
            store_id=store_id,
            status=Status.COMMITTED,
        )

    root = await data_store.get_tree_root(store_id=store_id)
    assert root.generation == num_files + 1
    root_hashes = []

    tmp_path_1 = tmp_path.joinpath("1")
    tmp_path_2 = tmp_path.joinpath("2")

    for generation in range(1, num_files + 2):
        root = await data_store.get_tree_root(store_id=store_id, generation=generation)
        await write_files_for_root(data_store, store_id, root, tmp_path_1, 0, False, group_files_by_store)
        root_hashes.append(bytes32([0] * 32) if root.node_hash is None else root.node_hash)
    store_path = tmp_path_1.joinpath(f"{store_id}") if group_files_by_store else tmp_path_1
    with os.scandir(store_path) as entries:
        filenames = {entry.name for entry in entries}
        assert len(filenames) == 2 * (num_files + 1)
    for filename in filenames:
        if "full" in filename:
            store_path.joinpath(filename).unlink()
    with os.scandir(store_path) as entries:
        filenames = {entry.name for entry in entries}
        assert len(filenames) == num_files + 1
    kv_before = await data_store.get_keys_values(store_id=store_id)
    await data_store.rollback_to_generation(store_id, 0)
    root = await data_store.get_tree_root(store_id=store_id)
    assert root.generation == 0
    os.rename(store_path, tmp_path_2)

    async def mock_http_download(
        target_filename_path: Path,
        filename: str,
        proxy_url: str,
        server_info: ServerInfo,
        timeout: int,
        log: logging.Logger,
    ) -> None:
        pass

    async def mock_http_download_2(
        target_filename_path: Path,
        filename: str,
        proxy_url: str,
        server_info: ServerInfo,
        timeout: int,
        log: logging.Logger,
    ) -> None:
        try:
            os.rmdir(store_path)
        except OSError:
            pass
        os.rename(tmp_path_2, store_path)

    sinfo = ServerInfo("http://127.0.0.1/8003", 0, 0)
    with monkeypatch.context() as m:
        m.setattr("chia.data_layer.download_data.http_download", mock_http_download)
        success = await insert_from_delta_file(
            data_store=data_store,
            store_id=store_id,
            existing_generation=0,
            root_hashes=root_hashes,
            server_info=sinfo,
            client_foldername=tmp_path_1,
            timeout=aiohttp.ClientTimeout(total=15, sock_connect=5),
            log=log,
            proxy_url="",
            downloader=None,
            group_files_by_store=group_files_by_store,
        )
        assert not success

    root = await data_store.get_tree_root(store_id=store_id)
    assert root.generation == 0

    sinfo = ServerInfo("http://127.0.0.1/8003", 0, 0)
    with monkeypatch.context() as m:
        m.setattr("chia.data_layer.download_data.http_download", mock_http_download_2)
        success = await insert_from_delta_file(
            data_store=data_store,
            store_id=store_id,
            existing_generation=0,
            root_hashes=root_hashes,
            server_info=sinfo,
            client_foldername=tmp_path_1,
            timeout=aiohttp.ClientTimeout(total=15, sock_connect=5),
            log=log,
            proxy_url="",
            downloader=None,
            group_files_by_store=group_files_by_store,
        )
        assert success

    root = await data_store.get_tree_root(store_id=store_id)
    assert root.generation == num_files + 1
    with os.scandir(store_path) as entries:
        filenames = {entry.name for entry in entries}
        assert len(filenames) == 2 * (num_files + 1)
    kv = await data_store.get_keys_values(store_id=store_id)
    assert kv == kv_before


@pytest.mark.anyio
async def test_get_node_by_key_with_overlapping_keys(raw_data_store: DataStore) -> None:
    num_stores = 5
    num_keys = 20
    values_offset = 10000
    repetitions = 25
    random = Random()
    random.seed(100, version=2)

    store_ids = [bytes32(i.to_bytes(32, byteorder="big")) for i in range(num_stores)]
    for store_id in store_ids:
        await raw_data_store.create_tree(store_id=store_id, status=Status.COMMITTED)
    keys = [key.to_bytes(4, byteorder="big") for key in range(num_keys)]
    for repetition in range(repetitions):
        for index, store_id in enumerate(store_ids):
            values = [
                (value + values_offset * repetition).to_bytes(4, byteorder="big")
                for value in range(index * num_keys, (index + 1) * num_keys)
            ]
            batch = []
            for key, value in zip(keys, values):
                batch.append({"action": "upsert", "key": key, "value": value})
            await raw_data_store.insert_batch(store_id, batch, status=Status.COMMITTED)

        for index, store_id in enumerate(store_ids):
            values = [
                (value + values_offset * repetition).to_bytes(4, byteorder="big")
                for value in range(index * num_keys, (index + 1) * num_keys)
            ]
            for key, value in zip(keys, values):
                node = await raw_data_store.get_node_by_key(store_id=store_id, key=key)
                assert node.value == value
                if random.randint(0, 4) == 0:
                    batch = [{"action": "delete", "key": key}]
                    await raw_data_store.insert_batch(store_id, batch, status=Status.COMMITTED)
                    with pytest.raises(KeyNotFoundError, match=f"Key not found: {key.hex()}"):
                        await raw_data_store.get_node_by_key(store_id=store_id, key=key)


@pytest.mark.anyio
@boolean_datacases(name="group_files_by_store", true="group by singleton", false="don't group by singleton")
async def test_insert_from_delta_file_correct_file_exists(
    data_store: DataStore, store_id: bytes32, tmp_path: Path, group_files_by_store: bool
) -> None:
    await data_store.create_tree(store_id=store_id, status=Status.COMMITTED)
    num_files = 5
    for generation in range(num_files):
        key = generation.to_bytes(4, byteorder="big")
        value = generation.to_bytes(4, byteorder="big")
        await data_store.autoinsert(
            key=key,
            value=value,
            store_id=store_id,
            status=Status.COMMITTED,
        )

    root = await data_store.get_tree_root(store_id=store_id)
    assert root.generation == num_files + 1
    root_hashes = []
    for generation in range(1, num_files + 2):
        root = await data_store.get_tree_root(store_id=store_id, generation=generation)
        await write_files_for_root(data_store, store_id, root, tmp_path, 0, group_by_store=group_files_by_store)
        root_hashes.append(bytes32([0] * 32) if root.node_hash is None else root.node_hash)
    store_path = tmp_path.joinpath(f"{store_id}") if group_files_by_store else tmp_path
    with os.scandir(store_path) as entries:
        filenames = {entry.name for entry in entries}
        assert len(filenames) == 2 * (num_files + 1)
    for filename in filenames:
        if "full" in filename:
            store_path.joinpath(filename).unlink()
    with os.scandir(store_path) as entries:
        filenames = {entry.name for entry in entries}
        assert len(filenames) == num_files + 1
    kv_before = await data_store.get_keys_values(store_id=store_id)
    await data_store.rollback_to_generation(store_id, 0)
    root = await data_store.get_tree_root(store_id=store_id)
    assert root.generation == 0

    sinfo = ServerInfo("http://127.0.0.1/8003", 0, 0)
    success = await insert_from_delta_file(
        data_store=data_store,
        store_id=store_id,
        existing_generation=0,
        root_hashes=root_hashes,
        server_info=sinfo,
        client_foldername=tmp_path,
        timeout=aiohttp.ClientTimeout(total=15, sock_connect=5),
        log=log,
        proxy_url="",
        downloader=None,
        group_files_by_store=group_files_by_store,
    )
    assert success

    root = await data_store.get_tree_root(store_id=store_id)
    assert root.generation == num_files + 1
    with os.scandir(store_path) as entries:
        filenames = {entry.name for entry in entries}
        assert len(filenames) == 2 * (num_files + 1)
    kv = await data_store.get_keys_values(store_id=store_id)
    assert kv == kv_before


@pytest.mark.anyio
@boolean_datacases(name="group_files_by_store", true="group by singleton", false="don't group by singleton")
async def test_insert_from_delta_file_incorrect_file_exists(
    data_store: DataStore, store_id: bytes32, tmp_path: Path, group_files_by_store: bool
) -> None:
    await data_store.create_tree(store_id=store_id, status=Status.COMMITTED)
    root = await data_store.get_tree_root(store_id=store_id)
    assert root.generation == 1

    key = b"a"
    value = b"a"
    await data_store.autoinsert(
        key=key,
        value=value,
        store_id=store_id,
        status=Status.COMMITTED,
    )

    root = await data_store.get_tree_root(store_id=store_id)
    assert root.generation == 2
    await write_files_for_root(data_store, store_id, root, tmp_path, 0, group_by_store=group_files_by_store)

    incorrect_root_hash = bytes32([0] * 31 + [1])
    store_path = tmp_path.joinpath(f"{store_id}") if group_files_by_store else tmp_path
    with os.scandir(store_path) as entries:
        filenames = [entry.name for entry in entries]
        assert len(filenames) == 2
        os.rename(
            store_path.joinpath(filenames[0]),
            get_delta_filename_path(tmp_path, store_id, incorrect_root_hash, 2, group_files_by_store),
        )
        os.rename(
            store_path.joinpath(filenames[1]),
            get_full_tree_filename_path(tmp_path, store_id, incorrect_root_hash, 2, group_files_by_store),
        )

    await data_store.rollback_to_generation(store_id, 1)
    sinfo = ServerInfo("http://127.0.0.1/8003", 0, 0)
    success = await insert_from_delta_file(
        data_store=data_store,
        store_id=store_id,
        existing_generation=1,
        root_hashes=[incorrect_root_hash],
        server_info=sinfo,
        client_foldername=tmp_path,
        timeout=aiohttp.ClientTimeout(total=15, sock_connect=5),
        log=log,
        proxy_url="",
        downloader=None,
        group_files_by_store=group_files_by_store,
    )
    assert not success

    root = await data_store.get_tree_root(store_id=store_id)
    assert root.generation == 1
    with os.scandir(store_path) as entries:
        filenames = [entry.name for entry in entries]
        assert len(filenames) == 0


@pytest.mark.anyio
async def test_insert_key_already_present(data_store: DataStore, store_id: bytes32) -> None:
    key = b"foo"
    value = b"bar"
    await data_store.insert(
        key=key, value=value, store_id=store_id, reference_node_hash=None, side=None, status=Status.COMMITTED
    )
    with pytest.raises(Exception, match=f"Key already present: {key.hex()}"):
        await data_store.insert(key=key, value=value, store_id=store_id, reference_node_hash=None, side=None)


@pytest.mark.anyio
@boolean_datacases(name="use_batch_autoinsert", false="not optimized batch insert", true="optimized batch insert")
async def test_batch_insert_key_already_present(
    data_store: DataStore,
    store_id: bytes32,
    use_batch_autoinsert: bool,
) -> None:
    key = b"foo"
    value = b"bar"
    changelist = [{"action": "insert", "key": key, "value": value}]
    await data_store.insert_batch(store_id, changelist, Status.COMMITTED, use_batch_autoinsert)
    with pytest.raises(Exception, match=f"Key already present: {key.hex()}"):
        await data_store.insert_batch(store_id, changelist, Status.COMMITTED, use_batch_autoinsert)


@pytest.mark.anyio
@boolean_datacases(name="use_upsert", false="update with delete and insert", true="update with upsert")
async def test_update_keys(data_store: DataStore, store_id: bytes32, use_upsert: bool) -> None:
    num_keys = 10
    missing_keys = 50
    num_values = 10
    new_keys = 10
    for value in range(num_values):
        changelist: List[Dict[str, Any]] = []
        bytes_value = value.to_bytes(4, byteorder="big")
        if use_upsert:
            for key in range(num_keys):
                bytes_key = key.to_bytes(4, byteorder="big")
                changelist.append({"action": "upsert", "key": bytes_key, "value": bytes_value})
        else:
            for key in range(num_keys + missing_keys):
                bytes_key = key.to_bytes(4, byteorder="big")
                changelist.append({"action": "delete", "key": bytes_key})
            for key in range(num_keys):
                bytes_key = key.to_bytes(4, byteorder="big")
                changelist.append({"action": "insert", "key": bytes_key, "value": bytes_value})

        await data_store.insert_batch(
            store_id=store_id,
            changelist=changelist,
            status=Status.COMMITTED,
        )
        for key in range(num_keys):
            bytes_key = key.to_bytes(4, byteorder="big")
            node = await data_store.get_node_by_key(bytes_key, store_id)
            assert node.value == bytes_value
        for key in range(num_keys, num_keys + missing_keys):
            bytes_key = key.to_bytes(4, byteorder="big")
            with pytest.raises(KeyNotFoundError, match=f"Key not found: {bytes_key.hex()}"):
                await data_store.get_node_by_key(bytes_key, store_id)
        num_keys += new_keys


@pytest.mark.anyio
async def test_migration_unknown_version(data_store: DataStore) -> None:
    async with data_store.db_wrapper.writer() as writer:
        await writer.execute(
            "INSERT INTO schema(version_id) VALUES(:version_id)",
            {
                "version_id": "unknown version",
            },
        )
    with pytest.raises(Exception, match="Unknown version"):
        await data_store.migrate_db()


async def _check_ancestors(
    data_store: DataStore, store_id: bytes32, root_hash: bytes32
) -> Dict[bytes32, Optional[bytes32]]:
    ancestors: Dict[bytes32, Optional[bytes32]] = {}
    root_node: Node = await data_store.get_node(root_hash)
    queue: List[Node] = [root_node]

    while queue:
        node = queue.pop(0)
        if isinstance(node, InternalNode):
            left_node = await data_store.get_node(node.left_hash)
            right_node = await data_store.get_node(node.right_hash)
            ancestors[left_node.hash] = node.hash
            ancestors[right_node.hash] = node.hash
            queue.append(left_node)
            queue.append(right_node)

    ancestors[root_hash] = None
    for node_hash, ancestor_hash in ancestors.items():
        ancestor_node = await data_store._get_one_ancestor(node_hash, store_id)
        if ancestor_hash is None:
            assert ancestor_node is None
        else:
            assert ancestor_node is not None
            assert ancestor_node.hash == ancestor_hash

    return ancestors


@pytest.mark.anyio
async def test_build_ancestor_table(data_store: DataStore, store_id: bytes32) -> None:
    num_values = 1000
    changelist: List[Dict[str, Any]] = []
    for value in range(num_values):
        value_bytes = value.to_bytes(4, byteorder="big")
        changelist.append({"action": "upsert", "key": value_bytes, "value": value_bytes})
    await data_store.insert_batch(
        store_id=store_id,
        changelist=changelist,
        status=Status.PENDING,
    )

    pending_root = await data_store.get_pending_root(store_id=store_id)
    assert pending_root is not None
    assert pending_root.node_hash is not None
    await data_store.change_root_status(pending_root, Status.COMMITTED)
    await data_store.build_ancestor_table_for_latest_root(store_id=store_id)

    assert pending_root.node_hash is not None
    await _check_ancestors(data_store, store_id, pending_root.node_hash)


@pytest.mark.anyio
async def test_sparse_ancestor_table(data_store: DataStore, store_id: bytes32) -> None:
    num_values = 100
    for value in range(num_values):
        value_bytes = value.to_bytes(4, byteorder="big")
        await data_store.autoinsert(
            key=value_bytes,
            value=value_bytes,
            store_id=store_id,
            status=Status.COMMITTED,
        )
        root = await data_store.get_tree_root(store_id=store_id)
        assert root.node_hash is not None
        ancestors = await _check_ancestors(data_store, store_id, root.node_hash)

    # Check the ancestor table is sparse
    root_generation = root.generation
    current_generation_count = 0
    previous_generation_count = 0
    for node_hash, ancestor_hash in ancestors.items():
        async with data_store.db_wrapper.reader() as reader:
            if ancestor_hash is not None:
                cursor = await reader.execute(
                    "SELECT MAX(generation) AS generation FROM ancestors WHERE hash == :hash AND ancestor == :ancestor",
                    {"hash": node_hash, "ancestor": ancestor_hash},
                )
            else:
                cursor = await reader.execute(
                    "SELECT MAX(generation) AS generation FROM ancestors WHERE hash == :hash AND ancestor IS NULL",
                    {"hash": node_hash},
                )
            row = await cursor.fetchone()
            assert row is not None
            generation = row["generation"]
            assert generation <= root_generation
            if generation == root_generation:
                current_generation_count += 1
            else:
                previous_generation_count += 1

    assert current_generation_count == 15
    assert previous_generation_count == 184


async def get_all_nodes(data_store: DataStore, store_id: bytes32) -> List[Node]:
    root = await data_store.get_tree_root(store_id)
    assert root.node_hash is not None
    root_node = await data_store.get_node(root.node_hash)
    nodes: List[Node] = []
    queue: List[Node] = [root_node]

    while len(queue) > 0:
        node = queue.pop(0)
        nodes.append(node)
        if isinstance(node, InternalNode):
            left_node = await data_store.get_node(node.left_hash)
            right_node = await data_store.get_node(node.right_hash)
            queue.append(left_node)
            queue.append(right_node)

    return nodes


@pytest.mark.anyio
async def test_get_nodes(data_store: DataStore, store_id: bytes32) -> None:
    num_values = 50
    changelist: List[Dict[str, Any]] = []

    for value in range(num_values):
        value_bytes = value.to_bytes(4, byteorder="big")
        changelist.append({"action": "upsert", "key": value_bytes, "value": value_bytes})
    await data_store.insert_batch(
        store_id=store_id,
        changelist=changelist,
        status=Status.COMMITTED,
    )

    expected_nodes = await get_all_nodes(data_store, store_id)
    nodes = await data_store.get_nodes([node.hash for node in expected_nodes])
    assert nodes == expected_nodes

    node_hash = bytes32([0] * 32)
    node_hash_2 = bytes32([0] * 31 + [1])
    with pytest.raises(Exception, match=f"^Nodes not found for hashes: {node_hash.hex()}, {node_hash_2.hex()}"):
        await data_store.get_nodes([node_hash, node_hash_2] + [node.hash for node in expected_nodes])


@pytest.mark.anyio
@pytest.mark.parametrize("pre", [0, 2048])
@pytest.mark.parametrize("batch_size", [25, 100, 500])
async def test_get_leaf_at_minimum_height(
    data_store: DataStore,
    store_id: bytes32,
    pre: int,
    batch_size: int,
) -> None:
    num_values = 1000
    value_offset = 1000000
    all_min_leafs: Set[TerminalNode] = set()

    if pre > 0:
        # This builds a complete binary tree, in order to test more than one batch in the queue before finding the leaf
        changelist: List[Dict[str, Any]] = []

        for value in range(pre):
            value_bytes = (value * value).to_bytes(8, byteorder="big")
            changelist.append({"action": "upsert", "key": value_bytes, "value": value_bytes})
        await data_store.insert_batch(
            store_id=store_id,
            changelist=changelist,
            status=Status.COMMITTED,
        )

    for value in range(num_values):
        value_bytes = value.to_bytes(4, byteorder="big")
        # Use autoinsert instead of `insert_batch` to get a more randomly shaped tree
        await data_store.autoinsert(
            key=value_bytes,
            value=value_bytes,
            store_id=store_id,
            status=Status.COMMITTED,
        )

        if (value + 1) % batch_size == 0:
            hash_to_parent: Dict[bytes32, InternalNode] = {}
            root = await data_store.get_tree_root(store_id)
            assert root.node_hash is not None
            min_leaf = await data_store.get_leaf_at_minimum_height(root.node_hash, hash_to_parent)
            all_nodes = await get_all_nodes(data_store, store_id)
            heights: Dict[bytes32, int] = {}
            heights[root.node_hash] = 0
            min_leaf_height = None

            for node in all_nodes:
                if isinstance(node, InternalNode):
                    heights[node.left_hash] = heights[node.hash] + 1
                    heights[node.right_hash] = heights[node.hash] + 1
                else:
                    if min_leaf_height is not None:
                        min_leaf_height = min(min_leaf_height, heights[node.hash])
                    else:
                        min_leaf_height = heights[node.hash]

            assert min_leaf_height is not None
            if pre > 0:
                assert min_leaf_height >= 11
            for node in all_nodes:
                if isinstance(node, TerminalNode):
                    assert node == min_leaf
                    assert heights[min_leaf.hash] == min_leaf_height
                    break
                if node.left_hash in hash_to_parent:
                    assert hash_to_parent[node.left_hash] == node
                if node.right_hash in hash_to_parent:
                    assert hash_to_parent[node.right_hash] == node

            # Push down the min height leaf, so on the next iteration we get a different leaf
            pushdown_height = 20
            for repeat in range(pushdown_height):
                value_bytes = (value + (repeat + 1) * value_offset).to_bytes(4, byteorder="big")
                await data_store.insert(
                    key=value_bytes,
                    value=value_bytes,
                    store_id=store_id,
                    reference_node_hash=min_leaf.hash,
                    side=Side.RIGHT,
                    status=Status.COMMITTED,
                )
            assert min_leaf not in all_min_leafs
            all_min_leafs.add(min_leaf)
