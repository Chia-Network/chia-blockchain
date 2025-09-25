from __future__ import annotations

import sqlite3

import pytest
from chia_rs.sized_bytes import bytes32

from chia._tests.core.data_layer.util import add_01234567_example
from chia.data_layer.data_layer_util import Status
from chia.data_layer.data_store import DataStore

pytestmark = pytest.mark.data_layer


@pytest.mark.parametrize(argnames="length", argvalues=sorted(set(range(50)) - {32}))
@pytest.mark.anyio
async def test_root_store_id_must_be_32(data_store: DataStore, store_id: bytes32, length: int) -> None:
    example = await add_01234567_example(data_store=data_store, store_id=store_id)
    bad_store_id = bytes([0] * length)
    values = {
        "tree_id": bad_store_id,
        "generation": 0,
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


@pytest.mark.anyio
async def test_root_store_id_must_not_be_null(data_store: DataStore, store_id: bytes32) -> None:
    example = await add_01234567_example(data_store=data_store, store_id=store_id)
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
@pytest.mark.anyio
async def test_root_generation_must_not_be_less_than_zero(
    data_store: DataStore, store_id: bytes32, generation: int
) -> None:
    example = await add_01234567_example(data_store=data_store, store_id=store_id)
    values = {
        "tree_id": bytes32.zeros,
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


@pytest.mark.anyio
async def test_root_generation_must_not_be_null(data_store: DataStore, store_id: bytes32) -> None:
    example = await add_01234567_example(data_store=data_store, store_id=store_id)
    values = {
        "tree_id": bytes32.zeros,
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


@pytest.mark.parametrize(argnames="bad_status", argvalues=sorted(set(range(-20, 20)) - {*Status}))
@pytest.mark.anyio
async def test_root_status_must_be_valid(data_store: DataStore, store_id: bytes32, bad_status: int) -> None:
    example = await add_01234567_example(data_store=data_store, store_id=store_id)
    values = {
        "tree_id": bytes32.zeros,
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


@pytest.mark.anyio
async def test_root_status_must_not_be_null(data_store: DataStore, store_id: bytes32) -> None:
    example = await add_01234567_example(data_store=data_store, store_id=store_id)
    values = {"tree_id": bytes32.zeros, "generation": 0, "node_hash": example.terminal_nodes[0], "status": None}

    async with data_store.db_wrapper.writer() as writer:
        with pytest.raises(sqlite3.IntegrityError, match=r"^NOT NULL constraint failed: root.status$"):
            await writer.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                values,
            )


@pytest.mark.anyio
async def test_root_store_id_generation_must_be_unique(data_store: DataStore, store_id: bytes32) -> None:
    example = await add_01234567_example(data_store=data_store, store_id=store_id)
    values = {"tree_id": store_id, "generation": 0, "node_hash": example.terminal_nodes[0], "status": Status.COMMITTED}

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
@pytest.mark.anyio
async def test_subscriptions_store_id_must_be_32(
    data_store: DataStore,
    store_id: bytes32,
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
