import sqlite3
from typing import Any, Dict

import pytest

from chia.data_layer.data_layer_types import NodeType, Side
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.tree_hash import bytes32

from tests.core.data_layer.util import add_01234567_example, create_valid_node_values


pytestmark = pytest.mark.data_layer


@pytest.mark.asyncio
async def test_schema_checks_node_update_fails(data_store: DataStore, tree_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)
    node = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    async with data_store.db_wrapper.locked_transaction():
        with pytest.raises(sqlite3.IntegrityError, match=r"^updates not allowed to the node table$"):
            await data_store.db.execute(
                "UPDATE node SET value = :value WHERE hash == :hash",
                {
                    "hash": node.hash,
                    "value": node.value,
                },
            )


@pytest.mark.parametrize(argnames="length", argvalues=sorted(set(range(50)) - {32}))
@pytest.mark.asyncio
async def test_schema_checks_node_hash_must_be_32(
    data_store: DataStore,
    tree_id: bytes32,
    length: int,
    valid_node_values: Dict[str, Any],
) -> None:
    valid_node_values["hash"] = bytes([0] * length)

    async with data_store.db_wrapper.locked_transaction():
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed: node\b"):
            await data_store.db.execute(
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

    async with data_store.db_wrapper.locked_transaction():
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed: node\b"):
            await data_store.db.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                valid_node_values,
            )


@pytest.mark.parametrize(argnames="side", argvalues=Side)
@pytest.mark.asyncio
async def test_internal_child_not_null(
    data_store: DataStore,
    tree_id: bytes32,
    side: Side,
) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)
    node_a = await data_store.get_node_by_key(key=b"\x02", tree_id=tree_id)
    node_b = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    values = create_valid_node_values(node_type=NodeType.INTERNAL, left_hash=node_a.hash, right_hash=node_b.hash)

    if side == Side.LEFT:
        values["left"] = None
    elif side == Side.RIGHT:
        values["right"] = None

    async with data_store.db_wrapper.locked_transaction():
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed: node\b"):
            await data_store.db.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                values,
            )


@pytest.mark.parametrize(argnames="bad_child_hash", argvalues=[b"\x01" * 32, b"\0" * 31, b""])
@pytest.mark.parametrize(argnames="side", argvalues=Side)
@pytest.mark.asyncio
async def test_internal_must_be_valid_reference(
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

    async with data_store.db_wrapper.locked_transaction():
        with pytest.raises(sqlite3.IntegrityError, match=r"^FOREIGN KEY constraint failed$"):
            await data_store.db.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                values,
            )


@pytest.mark.parametrize(argnames="key_or_value", argvalues=["key", "value"])
@pytest.mark.asyncio
async def test_terminal_key_value_not_null(
    data_store: DataStore,
    tree_id: bytes32,
    key_or_value: str,
) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    values = create_valid_node_values(node_type=NodeType.TERMINAL)
    values[key_or_value] = None

    async with data_store.db_wrapper.locked_transaction():
        with pytest.raises(sqlite3.IntegrityError, match=r"^CHECK constraint failed: node\b"):
            await data_store.db.execute(
                """
                INSERT INTO node(hash, node_type, left, right, key, value)
                VALUES(:hash, :node_type, :left, :right, :key, :value)
                """,
                values,
            )
