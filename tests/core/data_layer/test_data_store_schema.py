from __future__ import annotations

import sqlite3
from typing import Any, Dict

import pytest

from chia.data_layer.data_layer_util import NodeType, Side, Status
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.tree_hash import bytes32
from tests.core.data_layer.util import add_01234567_example, create_valid_node_values

pytestmark = pytest.mark.data_layer


@pytest.mark.asyncio
async def test_node_update_fails(data_store: DataStore, tree_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)
    node = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^updates not allowed to the node table$"):
            await writer.execute(
                "UPDATE node SET value = :value WHERE hash == :hash",
                {
                    "hash": node.hash,
                    "value": node.value,
                },
            )


@pytest.mark.parametrize(argnames="length", argvalues=sorted(set(range(50)) - {32}))
@pytest.mark.asyncio
async def test_node_hash_must_be_32(
    data_store: DataStore,
    tree_id: bytes32,
    length: int,
    valid_node_values: Dict[str, Any],
) -> None:
    valid_node_values["hash"] = bytes([0] * length)

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed:"):
            await writer.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                valid_node_values,
            )


@pytest.mark.asyncio
async def test_node_hash_must_not_be_null(
    data_store: DataStore,
    tree_id: bytes32,
    valid_node_values: Dict[str, Any],
) -> None:
    valid_node_values["hash"] = None

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^NOT NULL constraint failed: node.hash$"):
            await writer.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                valid_node_values,
            )


@pytest.mark.asyncio
async def test_node_type_must_be_valid(
    data_store: DataStore,
    node_type: NodeType,
    bad_node_type: int,
    valid_node_values: Dict[str, Any],
) -> None:
    valid_node_values["node_type"] = bad_node_type

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed:"):
            await writer.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                valid_node_values,
            )


@pytest.mark.parametrize(argnames="side", argvalues=Side)
@pytest.mark.asyncio
async def test_node_internal_child_not_null(data_store: DataStore, tree_id: bytes32, side: Side) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)
    node_a = await data_store.get_node_by_key(key=b"\x02", tree_id=tree_id)
    node_b = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    values = create_valid_node_values(node_type=NodeType.INTERNAL, left_hash=node_a.hash, right_hash=node_b.hash)

    if side == Side.LEFT:
        values["left"] = None
    elif side == Side.RIGHT:
        values["right"] = None

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed:"):
            await writer.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                values,
            )


@pytest.mark.parametrize(argnames="bad_child_hash", argvalues=[b"\x01" * 32, b"\0" * 31, b""])
@pytest.mark.parametrize(argnames="side", argvalues=Side)
@pytest.mark.asyncio
async def test_node_internal_must_be_valid_reference(
    data_store: DataStore,
    tree_id: bytes32,
    bad_child_hash: bytes,
    side: Side,
) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)
    node_a = await data_store.get_node_by_key(key=b"\x02", tree_id=tree_id)
    node_b = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    values = create_valid_node_values(node_type=NodeType.INTERNAL, left_hash=node_a.hash, right_hash=node_b.hash)

    if side == Side.LEFT:
        values["left"] = bad_child_hash
    elif side == Side.RIGHT:
        values["right"] = bad_child_hash
    else:
        assert False

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^FOREIGN KEY constraint failed$"):
            await writer.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                values,
            )


@pytest.mark.parametrize(argnames="key_or_value", argvalues=["key", "value"])
@pytest.mark.asyncio
async def test_node_terminal_key_value_not_null(data_store: DataStore, tree_id: bytes32, key_or_value: str) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    values = create_valid_node_values(node_type=NodeType.TERMINAL)
    values[key_or_value] = None

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed:"):
            await writer.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                values,
            )


@pytest.mark.parametrize(argnames="length", argvalues=sorted(set(range(50)) - {32}))
@pytest.mark.asyncio
async def test_root_tree_id_must_be_32(data_store: DataStore, tree_id: bytes32, length: int) -> None:
    example = await add_01234567_example(data_store=data_store, tree_id=tree_id)
    bad_tree_id = bytes([0] * length)
    values = {"tree_id": bad_tree_id, "generation": 0, "node_hash": example.terminal_nodes[0], "status": Status.PENDING}

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed:"):
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                values,
            )


@pytest.mark.asyncio
async def test_root_tree_id_must_not_be_null(data_store: DataStore, tree_id: bytes32) -> None:
    example = await add_01234567_example(data_store=data_store, tree_id=tree_id)
    values = {"tree_id": None, "generation": 0, "node_hash": example.terminal_nodes[0], "status": Status.PENDING}

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^NOT NULL constraint failed: root.tree_id$"):
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                values,
            )


@pytest.mark.parametrize(argnames="generation", argvalues=[-200, -2, -1])
@pytest.mark.asyncio
async def test_root_generation_must_not_be_less_than_zero(
    data_store: DataStore, tree_id: bytes32, generation: int
) -> None:
    example = await add_01234567_example(data_store=data_store, tree_id=tree_id)
    values = {
        "tree_id": bytes32([0] * 32),
        "generation": generation,
        "node_hash": example.terminal_nodes[0],
        "status": Status.PENDING,
    }

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed:"):
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                values,
            )


@pytest.mark.asyncio
async def test_root_generation_must_not_be_null(data_store: DataStore, tree_id: bytes32) -> None:
    example = await add_01234567_example(data_store=data_store, tree_id=tree_id)
    values = {
        "tree_id": bytes32([0] * 32),
        "generation": None,
        "node_hash": example.terminal_nodes[0],
        "status": Status.PENDING,
    }

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^NOT NULL constraint failed: root.generation$"):
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                values,
            )


@pytest.mark.asyncio
async def test_root_node_hash_must_reference(data_store: DataStore) -> None:
    values = {"tree_id": bytes32([0] * 32), "generation": 0, "node_hash": bytes32([0] * 32), "status": Status.PENDING}

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^FOREIGN KEY constraint failed$"):
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                values,
            )


@pytest.mark.parametrize(argnames="bad_status", argvalues=sorted(set(range(-20, 20)) - {*Status}))
@pytest.mark.asyncio
async def test_root_status_must_be_valid(data_store: DataStore, tree_id: bytes32, bad_status: int) -> None:
    example = await add_01234567_example(data_store=data_store, tree_id=tree_id)
    values = {
        "tree_id": bytes32([0] * 32),
        "generation": 0,
        "node_hash": example.terminal_nodes[0],
        "status": bad_status,
    }

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed:"):
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                values,
            )


@pytest.mark.asyncio
async def test_root_status_must_not_be_null(data_store: DataStore, tree_id: bytes32) -> None:
    example = await add_01234567_example(data_store=data_store, tree_id=tree_id)
    values = {"tree_id": bytes32([0] * 32), "generation": 0, "node_hash": example.terminal_nodes[0], "status": None}

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^NOT NULL constraint failed: root.status$"):
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                values,
            )


@pytest.mark.asyncio
async def test_root_tree_id_generation_must_be_unique(data_store: DataStore, tree_id: bytes32) -> None:
    example = await add_01234567_example(data_store=data_store, tree_id=tree_id)
    values = {"tree_id": tree_id, "generation": 0, "node_hash": example.terminal_nodes[0], "status": Status.COMMITTED}

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^UNIQUE constraint failed: root.tree_id, root.generation$"):
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                values,
            )


@pytest.mark.parametrize(argnames="length", argvalues=sorted(set(range(50)) - {32}))
@pytest.mark.asyncio
async def test_ancestors_ancestor_must_be_32(
    data_store: DataStore,
    tree_id: bytes32,
    length: int,
) -> None:
    async with data_store.db_wrapper.writer() as writer:
        node_hash = await data_store._insert_terminal_node(key=b"\x00", value=b"\x01")
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed:"):
            await writer.execute(
                """
                INSERT INTO ancestors(hash, ancestor, tree_id, generation)
                VALUES(:hash, :ancestor, :tree_id, :generation)
                """,
                {"hash": node_hash, "ancestor": bytes([0] * length), "tree_id": bytes32([0] * 32), "generation": 0},
            )


@pytest.mark.parametrize(argnames="length", argvalues=sorted(set(range(50)) - {32}))
@pytest.mark.asyncio
async def test_ancestors_tree_id_must_be_32(
    data_store: DataStore,
    tree_id: bytes32,
    length: int,
) -> None:
    async with data_store.db_wrapper.writer() as writer:
        node_hash = await data_store._insert_terminal_node(key=b"\x00", value=b"\x01")
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed:"):
            await writer.execute(
                """
                INSERT INTO ancestors(hash, ancestor, tree_id, generation)
                VALUES(:hash, :ancestor, :tree_id, :generation)
                """,
                {"hash": node_hash, "ancestor": bytes32([0] * 32), "tree_id": bytes([0] * length), "generation": 0},
            )


@pytest.mark.parametrize(argnames="length", argvalues=sorted(set(range(50)) - {32}))
@pytest.mark.asyncio
async def test_subscriptions_tree_id_must_be_32(
    data_store: DataStore,
    tree_id: bytes32,
    length: int,
) -> None:
    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed:"):
            await writer.execute(
                """
                INSERT INTO subscriptions(tree_id, url, ignore_till, num_consecutive_failures, from_wallet)
                VALUES(:tree_id, :url, :ignore_till, :num_consecutive_failures, :from_wallet)
                """,
                {
                    "tree_id": bytes([0] * length),
                    "url": "",
                    "ignore_till": 0,
                    "num_consecutive_failures": 0,
                    "from_wallet": False,
                },
            )
