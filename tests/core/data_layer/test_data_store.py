import functools
import itertools
import logging
from dataclasses import dataclass
from typing import AsyncIterable, Callable, Dict, List, Optional, Tuple

import aiosqlite
import pytest

from chia.data_layer.data_layer_errors import (
    InternalKeyValueError,
    InternalLeftRightNotBytes32Error,
    NodeHashError,
    TerminalInvalidKeyOrValueProgramError,
    TerminalLeftRightError,
    TreeGenerationIncrementingError,
)
from chia.data_layer.data_layer_types import NodeType, Side
from chia.data_layer.data_layer_util import _debug_dump
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.tree_hash import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.db_wrapper import DBWrapper

# from tests.setup_nodes import bt, test_constants

log = logging.getLogger(__name__)


def kv(k: bytes, v: List[bytes]) -> Tuple[bytes, bytes]:
    return Program.to(k).as_bin(), Program.to(v).as_bin()


@pytest.fixture(name="db_connection", scope="function")
async def db_connection_fixture() -> AsyncIterable[aiosqlite.Connection]:
    async with aiosqlite.connect(":memory:") as connection:
        # make sure this is on for tests even if we disable it at run time
        await connection.execute("PRAGMA foreign_keys = ON")
        yield connection


@pytest.fixture(name="db_wrapper", scope="function")
def db_wrapper_fixture(db_connection: aiosqlite.Connection) -> DBWrapper:
    return DBWrapper(db_connection)


@pytest.fixture(name="tree_id", scope="function")
def tree_id_fixture() -> bytes32:
    base = b"a tree id"
    pad = b"." * (32 - len(base))
    return bytes32(pad + base)


@pytest.fixture(name="raw_data_store", scope="function")
async def raw_data_store_fixture(db_wrapper: DBWrapper) -> DataStore:
    return await DataStore.create(db_wrapper=db_wrapper)


@pytest.fixture(name="data_store", scope="function")
async def data_store_fixture(raw_data_store: DataStore, tree_id: bytes32) -> AsyncIterable[DataStore]:
    await raw_data_store.create_tree(tree_id=tree_id)

    await raw_data_store.check()
    yield raw_data_store
    await raw_data_store.check()


# @pytest.fixture(name="root", scope="function")
# async def root_fixture(data_store: DataStore, tree_id: bytes32) -> Root:
#     return await data_store.get_tree_root(tree_id=tree_id)


table_columns: Dict[str, List[str]] = {
    "node": ["hash", "node_type", "left", "right", "key", "value"],
    "root": ["tree_id", "generation", "node_hash"],
}


# TODO: Someday add tests for malformed DB data to make sure we handle it gracefully
#       and with good error messages.


@pytest.mark.parametrize(argnames=["table_name", "expected_columns"], argvalues=table_columns.items())
@pytest.mark.asyncio
async def test_create_creates_tables_and_columns(
    db_wrapper: DBWrapper, table_name: str, expected_columns: List[str]
) -> None:
    # Never string-interpolate sql queries...  Except maybe in tests when it does not
    # allow you to parametrize the query.
    query = f"pragma table_info({table_name});"

    cursor = await db_wrapper.db.execute(query)
    columns = await cursor.fetchall()
    assert columns == []

    await DataStore.create(db_wrapper=db_wrapper)
    cursor = await db_wrapper.db.execute(query)
    columns = await cursor.fetchall()
    assert [column[1] for column in columns] == expected_columns


@pytest.mark.asyncio
async def test_create_tree_accepts_bytes32(raw_data_store: DataStore) -> None:
    tree_id = bytes32(b"\0" * 32)

    await raw_data_store.create_tree(tree_id=tree_id)


@pytest.mark.xfail(strict=True)
@pytest.mark.parametrize(argnames=["length"], argvalues=[[length] for length in [*range(0, 32), *range(33, 48)]])
@pytest.mark.asyncio
async def test_create_tree_fails_for_not_bytes32(raw_data_store: DataStore, length: int) -> None:
    bad_tree_id = b"\0" * length

    # TODO: require a more specific exception
    with pytest.raises(Exception):
        await raw_data_store.create_tree(tree_id=bad_tree_id)


@pytest.mark.asyncio
async def test_get_trees(raw_data_store: DataStore) -> None:
    expected_tree_ids = set()

    for n in range(10):
        tree_id = bytes32((b"\0" * 31 + bytes([n])))
        await raw_data_store.create_tree(tree_id=tree_id)
        expected_tree_ids.add(tree_id)

    tree_ids = await raw_data_store.get_tree_ids()

    assert tree_ids == expected_tree_ids


@pytest.mark.asyncio
async def test_table_is_empty(data_store: DataStore, tree_id: bytes32) -> None:
    is_empty = await data_store.table_is_empty(tree_id=tree_id)
    assert is_empty


@pytest.mark.asyncio
async def test_table_is_not_empty(data_store: DataStore, tree_id: bytes32) -> None:
    key = Program.to([1, 2])
    value = Program.to("abc")

    await data_store.insert(key=key, value=value, tree_id=tree_id, reference_node_hash=None, side=None)

    is_empty = await data_store.table_is_empty(tree_id=tree_id)
    assert not is_empty


# @pytest.mark.asyncio
# async def test_create_root_provides_bytes32(raw_data_store: DataStore, tree_id: bytes32) -> None:
#     await raw_data_store.create_tree(tree_id=tree_id)
#     # TODO: catchup with the node_hash=
#     root_hash = await raw_data_store.create_root(tree_id=tree_id, node_hash=23)
#
#     assert isinstance(root_hash, bytes32)


@pytest.mark.asyncio
async def test_insert_over_empty(data_store: DataStore, tree_id: bytes32) -> None:
    key = Program.to([1, 2])
    value = Program.to("abc")

    node_hash = await data_store.insert(key=key, value=value, tree_id=tree_id, reference_node_hash=None, side=None)
    assert node_hash == Program.to((key, value)).get_tree_hash()


@pytest.mark.asyncio
async def test_insert_increments_generation(data_store: DataStore, tree_id: bytes32) -> None:
    keys = list("abcd")  # efghijklmnopqrstuvwxyz")
    value = Program.to([1, 2, 3])

    generations = []
    expected = []

    node_hash = None
    for key, expected_generation in zip(keys, itertools.count(start=1)):
        node_hash = await data_store.insert(
            key=Program.to(key),
            value=value,
            tree_id=tree_id,
            reference_node_hash=node_hash,
            side=None if node_hash is None else Side.LEFT,
        )
        generation = await data_store.get_tree_generation(tree_id=tree_id)
        generations.append(generation)
        expected.append(expected_generation)

    assert generations == expected


async def general_insert(
    data_store: DataStore,
    tree_id: bytes32,
    key: bytes,
    value: List[bytes],
    reference_node_hash: bytes32,
    side: Optional[Side],
) -> bytes32:
    return await data_store.insert(
        key=Program.to(key),
        value=Program.to(value),
        tree_id=tree_id,
        reference_node_hash=reference_node_hash,
        side=side,
    )


@dataclass(frozen=True)
class Example:
    expected: Program
    terminal_nodes: List[bytes32]


async def add_0123_example(data_store: DataStore, tree_id: bytes32) -> Example:
    expected = Program.to(
        (
            (
                kv(b"\x00", [b"\x10", b"\x00"]),
                kv(b"\x01", [b"\x11", b"\x01"]),
            ),
            (
                kv(b"\x02", [b"\x12", b"\x02"]),
                kv(b"\x03", [b"\x13", b"\x03"]),
            ),
        ),
    )

    insert = functools.partial(general_insert, data_store=data_store, tree_id=tree_id)

    c_hash = await insert(key=b"\x02", value=[b"\x12", b"\x02"], reference_node_hash=None, side=None)
    b_hash = await insert(key=b"\x01", value=[b"\x11", b"\x01"], reference_node_hash=c_hash, side=Side.LEFT)
    d_hash = await insert(key=b"\x03", value=[b"\x13", b"\x03"], reference_node_hash=c_hash, side=Side.RIGHT)
    a_hash = await insert(key=b"\x00", value=[b"\x10", b"\x00"], reference_node_hash=b_hash, side=Side.LEFT)

    return Example(expected=expected, terminal_nodes=[a_hash, b_hash, c_hash, d_hash])


async def add_01234567_example(data_store: DataStore, tree_id: bytes32) -> Example:
    expected = Program.to(
        (
            (
                (
                    kv(b"\x00", [b"\x10", b"\x00"]),
                    kv(b"\x01", [b"\x11", b"\x01"]),
                ),
                (
                    kv(b"\x02", [b"\x12", b"\x02"]),
                    kv(b"\x03", [b"\x13", b"\x03"]),
                ),
            ),
            (
                (
                    kv(b"\x04", [b"\x14", b"\x04"]),
                    kv(b"\x05", [b"\x15", b"\x05"]),
                ),
                (
                    kv(b"\x06", [b"\x16", b"\x06"]),
                    kv(b"\x07", [b"\x17", b"\x07"]),
                ),
            ),
        ),
    )

    insert = functools.partial(general_insert, data_store=data_store, tree_id=tree_id)

    g_hash = await insert(key=b"\x06", value=[b"\x16", b"\x06"], reference_node_hash=None, side=None)

    c_hash = await insert(key=b"\x02", value=[b"\x12", b"\x02"], reference_node_hash=g_hash, side=Side.LEFT)
    b_hash = await insert(key=b"\x01", value=[b"\x11", b"\x01"], reference_node_hash=c_hash, side=Side.LEFT)
    d_hash = await insert(key=b"\x03", value=[b"\x13", b"\x03"], reference_node_hash=c_hash, side=Side.RIGHT)
    a_hash = await insert(key=b"\x00", value=[b"\x10", b"\x00"], reference_node_hash=b_hash, side=Side.LEFT)

    f_hash = await insert(key=b"\x05", value=[b"\x15", b"\x05"], reference_node_hash=g_hash, side=Side.LEFT)
    h_hash = await insert(key=b"\x07", value=[b"\x17", b"\x07"], reference_node_hash=g_hash, side=Side.RIGHT)
    e_hash = await insert(key=b"\x04", value=[b"\x14", b"\x04"], reference_node_hash=f_hash, side=Side.LEFT)

    return Example(expected=expected, terminal_nodes=[a_hash, b_hash, c_hash, d_hash, e_hash, f_hash, g_hash, h_hash])


@pytest.mark.parametrize(argnames=["adder"], argvalues=[[add_0123_example], [add_01234567_example]])
@pytest.mark.asyncio
async def test_build_a_tree(
    data_store: DataStore,
    tree_id: bytes32,
    adder: Callable[[DataStore, bytes32], Example],
) -> None:
    example = await adder(data_store=data_store, tree_id=tree_id)  # type: ignore

    await _debug_dump(db=data_store.db, description="final")
    actual = await data_store.get_tree_as_program(tree_id=tree_id)
    print("actual  ", actual.as_python())
    print("expected", example.expected.as_python())
    assert actual == example.expected


@pytest.mark.asyncio
async def test_get_node_by_key(data_store: DataStore, tree_id: bytes32) -> None:
    example = await add_0123_example(data_store=data_store, tree_id=tree_id)

    key_node_hash = example.terminal_nodes[2]

    # TODO: make a nicer relationship between the hash and the key

    actual = await data_store.get_node_by_key(key=Program.to(b"\x02"), tree_id=tree_id)
    assert actual.hash == key_node_hash


@pytest.mark.asyncio
async def test_get_node_by_key_bytes(data_store: DataStore, tree_id: bytes32) -> None:
    example = await add_0123_example(data_store=data_store, tree_id=tree_id)

    key_node_hash = example.terminal_nodes[2]

    # TODO: make a nicer relationship between the hash and the key

    actual = await data_store.get_node_by_key_bytes(key=Program.to(b"\x02").as_bin(), tree_id=tree_id)
    assert actual.hash == key_node_hash


@pytest.mark.asyncio
async def test_get_ancestors(data_store: DataStore, tree_id: bytes32) -> None:
    example = await add_0123_example(data_store=data_store, tree_id=tree_id)

    reference_node_hash = example.terminal_nodes[2]

    ancestors = await data_store.get_ancestors(node_hash=reference_node_hash, tree_id=tree_id)
    hashes = [node.hash.hex() for node in ancestors]

    # TODO: reverify these are correct
    assert hashes == [
        "eba9a0627b6c1956e33abd233a216e1bb977a5af6e76045b4f2e9de79e6b526e",
        "5fa24f8b8cedf2e1603a7827ad1187e79e1e98e990ed57a4e339dba45f0862cf",
    ]


@pytest.mark.asyncio
async def test_get_pairs(data_store: DataStore, tree_id: bytes32) -> None:
    example = await add_0123_example(data_store=data_store, tree_id=tree_id)

    pairs = await data_store.get_pairs(tree_id=tree_id)

    assert {node.hash for node in pairs} == set(example.terminal_nodes)


@pytest.mark.asyncio
async def test_get_pairs_when_empty(data_store: DataStore, tree_id: bytes32) -> None:
    pairs = await data_store.get_pairs(tree_id=tree_id)

    assert pairs == []


@pytest.mark.asyncio()
async def test_inserting_duplicate_key_fails(data_store: DataStore, tree_id: bytes32) -> None:
    key = Program.to(5)

    first_hash = await data_store.insert(
        key=key,
        value=Program.to(6),
        tree_id=tree_id,
        reference_node_hash=None,
        side=None,
    )

    # TODO: more specific exception
    with pytest.raises(Exception):
        await data_store.insert(
            key=key,
            value=Program.to(7),
            tree_id=tree_id,
            reference_node_hash=first_hash,
            side=Side.RIGHT,
        )


@pytest.mark.asyncio()
async def test_delete_from_left_both_terminal(data_store: DataStore, tree_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    expected = Program.to(
        (
            (
                (
                    kv(b"\x00", [b"\x10", b"\x00"]),
                    kv(b"\x01", [b"\x11", b"\x01"]),
                ),
                (
                    kv(b"\x02", [b"\x12", b"\x02"]),
                    kv(b"\x03", [b"\x13", b"\x03"]),
                ),
            ),
            (
                kv(b"\x05", [b"\x15", b"\x05"]),
                (
                    kv(b"\x06", [b"\x16", b"\x06"]),
                    kv(b"\x07", [b"\x17", b"\x07"]),
                ),
            ),
        ),
    )

    await data_store.delete(key=Program.to(b"\x04"), tree_id=tree_id)
    result = await data_store.get_tree_as_program(tree_id=tree_id)

    assert result == expected


@pytest.mark.asyncio()
async def test_delete_from_left_other_not_terminal(data_store: DataStore, tree_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    expected = Program.to(
        (
            (
                (
                    kv(b"\x00", [b"\x10", b"\x00"]),
                    kv(b"\x01", [b"\x11", b"\x01"]),
                ),
                (
                    kv(b"\x02", [b"\x12", b"\x02"]),
                    kv(b"\x03", [b"\x13", b"\x03"]),
                ),
            ),
            (
                kv(b"\x06", [b"\x16", b"\x06"]),
                kv(b"\x07", [b"\x17", b"\x07"]),
            ),
        ),
    )

    await data_store.delete(key=Program.to(b"\x04"), tree_id=tree_id)
    await data_store.delete(key=Program.to(b"\x05"), tree_id=tree_id)
    result = await data_store.get_tree_as_program(tree_id=tree_id)

    assert result == expected


@pytest.mark.asyncio()
async def test_delete_from_right_both_terminal(data_store: DataStore, tree_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    expected = Program.to(
        (
            (
                (
                    kv(b"\x00", [b"\x10", b"\x00"]),
                    kv(b"\x01", [b"\x11", b"\x01"]),
                ),
                kv(b"\x02", [b"\x12", b"\x02"]),
            ),
            (
                (
                    kv(b"\x04", [b"\x14", b"\x04"]),
                    kv(b"\x05", [b"\x15", b"\x05"]),
                ),
                (
                    kv(b"\x06", [b"\x16", b"\x06"]),
                    kv(b"\x07", [b"\x17", b"\x07"]),
                ),
            ),
        ),
    )

    await data_store.delete(key=Program.to(b"\x03"), tree_id=tree_id)
    result = await data_store.get_tree_as_program(tree_id=tree_id)

    assert result == expected


@pytest.mark.asyncio()
async def test_delete_from_right_other_not_terminal(data_store: DataStore, tree_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    expected = Program.to(
        (
            (
                kv(b"\x00", [b"\x10", b"\x00"]),
                kv(b"\x01", [b"\x11", b"\x01"]),
            ),
            (
                (
                    kv(b"\x04", [b"\x14", b"\x04"]),
                    kv(b"\x05", [b"\x15", b"\x05"]),
                ),
                (
                    kv(b"\x06", [b"\x16", b"\x06"]),
                    kv(b"\x07", [b"\x17", b"\x07"]),
                ),
            ),
        ),
    )

    await data_store.delete(key=Program.to(b"\x03"), tree_id=tree_id)
    await data_store.delete(key=Program.to(b"\x02"), tree_id=tree_id)
    result = await data_store.get_tree_as_program(tree_id=tree_id)

    assert result == expected


# @pytest.mark.asyncio
# async def test_create_first_pair(data_store: DataStore, tree_id: bytes) -> None:
#     key = SExp.to([1, 2])
#     value = SExp.to(b'abc')
#
#     root_hash = await data_store.create_root(tree_id=tree_id)
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


@pytest.mark.parametrize(
    argnames="key_value",
    argvalues=[
        {"key": another_bytes_32.hex(), "value": None},
        {"key": None, "value": another_bytes_32.hex()},
    ],
    ids=["key", "value"],
)
@pytest.mark.asyncio
async def test_check_internal_key_value_are_null(
    raw_data_store: DataStore,
    key_value: Dict[str, Optional[str]],
) -> None:
    async with raw_data_store.db_wrapper.locked_transaction():
        await raw_data_store.db.execute(
            "INSERT INTO node(hash, node_type, key, value) VALUES(:hash, :node_type, :key, :value)",
            {"hash": a_bytes_32.hex(), "node_type": NodeType.INTERNAL, **key_value},
        )

    with pytest.raises(
        InternalKeyValueError,
        match=r"\n +000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f$",
    ):
        await raw_data_store._check_internal_key_value_are_null()


@pytest.mark.parametrize(
    argnames="left_right",
    argvalues=[
        {"left": a_bytes_32.hex(), "right": b"abc".hex()},
        {"left": b"abc".hex(), "right": a_bytes_32.hex()},
    ],
    ids=["left", "right"],
)
@pytest.mark.asyncio
async def test_check_internal_left_right_are_bytes32(raw_data_store: DataStore, left_right: Dict[str, str]) -> None:
    async with raw_data_store.db_wrapper.locked_transaction():
        # needed to satisfy foreign key constraints
        await raw_data_store.db.execute(
            "INSERT INTO node(hash, node_type) VALUES(:hash, :node_type)",
            {"hash": b"abc".hex(), "node_type": NodeType.TERMINAL},
        )

        await raw_data_store.db.execute(
            "INSERT INTO node(hash, node_type, left, right) VALUES(:hash, :node_type, :left, :right)",
            {"hash": a_bytes_32.hex(), "node_type": NodeType.INTERNAL, **left_right},
        )

    with pytest.raises(
        InternalLeftRightNotBytes32Error,
        match=r"\n +000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f$",
    ):
        await raw_data_store._check_internal_left_right_are_bytes32()


@pytest.mark.parametrize(
    argnames="left_right",
    argvalues=[
        {"left": a_bytes_32.hex(), "right": None},
        {"left": None, "right": a_bytes_32.hex()},
    ],
    ids=["left", "right"],
)
@pytest.mark.asyncio
async def test_check_terminal_left_right_are_null(raw_data_store: DataStore, left_right: Dict[str, str]) -> None:
    async with raw_data_store.db_wrapper.locked_transaction():
        await raw_data_store.db.execute(
            "INSERT INTO node(hash, node_type, left, right) VALUES(:hash, :node_type, :left, :right)",
            {"hash": a_bytes_32.hex(), "node_type": NodeType.TERMINAL, **left_right},
        )

    with pytest.raises(
        TerminalLeftRightError,
        match=r"\n +000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f$",
    ):
        await raw_data_store._check_terminal_left_right_are_null()


@pytest.mark.parametrize(
    argnames="key_value",
    argvalues=[
        {"key": valid_program_hex, "value": invalid_program_hex},
        {"key": invalid_program_hex, "value": valid_program_hex},
    ],
    ids=["key", "value"],
)
@pytest.mark.asyncio
async def test_check_terminal_key_value_are_serialized_programs(
    raw_data_store: DataStore,
    key_value: Dict[str, str],
) -> None:
    async with raw_data_store.db_wrapper.locked_transaction():
        await raw_data_store.db.execute(
            "INSERT INTO node(hash, node_type, key, value) VALUES(:hash, :node_type, :key, :value)",
            {"hash": a_bytes_32.hex(), "node_type": NodeType.TERMINAL, **key_value},
        )

    with pytest.raises(
        TerminalInvalidKeyOrValueProgramError,
        match=r"\n +000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f$",
    ):
        await raw_data_store._check_terminal_key_value_are_serialized_programs()


@pytest.mark.asyncio
async def test_check_roots_are_incrementing_missing_zero(raw_data_store: DataStore) -> None:
    tree_id = hexstr_to_bytes("c954ab71ffaf5b0f129b04b35fdc7c84541f4375167e730e2646bfcfdb7cf2cd")

    async with raw_data_store.db_wrapper.locked_transaction():
        for generation in range(1, 5):
            await raw_data_store.db.execute(
                "INSERT INTO root(tree_id, generation, node_hash) VALUES(:tree_id, :generation, :node_hash)",
                {"tree_id": tree_id.hex(), "generation": generation, "node_hash": None},
            )

    with pytest.raises(
        TreeGenerationIncrementingError,
        match=r"\n +c954ab71ffaf5b0f129b04b35fdc7c84541f4375167e730e2646bfcfdb7cf2cd$",
    ):
        await raw_data_store._check_roots_are_incrementing()


@pytest.mark.asyncio
async def test_check_roots_are_incrementing_gap(raw_data_store: DataStore) -> None:
    tree_id = hexstr_to_bytes("c954ab71ffaf5b0f129b04b35fdc7c84541f4375167e730e2646bfcfdb7cf2cd")

    async with raw_data_store.db_wrapper.locked_transaction():
        for generation in [*range(5), *range(6, 10)]:
            await raw_data_store.db.execute(
                "INSERT INTO root(tree_id, generation, node_hash) VALUES(:tree_id, :generation, :node_hash)",
                {"tree_id": tree_id.hex(), "generation": generation, "node_hash": None},
            )

    with pytest.raises(
        TreeGenerationIncrementingError,
        match=r"\n +c954ab71ffaf5b0f129b04b35fdc7c84541f4375167e730e2646bfcfdb7cf2cd$",
    ):
        await raw_data_store._check_roots_are_incrementing()


@pytest.mark.asyncio
async def test_check_hashes_internal(raw_data_store: DataStore) -> None:
    async with raw_data_store.db_wrapper.locked_transaction():
        await raw_data_store.db.execute(
            "INSERT INTO node(hash, node_type, left, right) VALUES(:hash, :node_type, :left, :right)",
            {
                "hash": a_bytes_32.hex(),
                "node_type": NodeType.INTERNAL,
                "left": a_bytes_32.hex(),
                "right": a_bytes_32.hex(),
            },
        )

    with pytest.raises(
        NodeHashError,
        match=r"\n +000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f$",
    ):
        await raw_data_store._check_hashes()


@pytest.mark.asyncio
async def test_check_hashes_terminal(raw_data_store: DataStore) -> None:
    async with raw_data_store.db_wrapper.locked_transaction():
        await raw_data_store.db.execute(
            "INSERT INTO node(hash, node_type, key, value) VALUES(:hash, :node_type, :key, :value)",
            {
                "hash": a_bytes_32.hex(),
                "node_type": NodeType.TERMINAL,
                "key": Program.to((1, 2)).as_bin().hex(),
                "value": Program.to((1, 2)).as_bin().hex(),
            },
        )

    with pytest.raises(
        NodeHashError,
        match=r"\n +000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f$",
    ):
        await raw_data_store._check_hashes()
