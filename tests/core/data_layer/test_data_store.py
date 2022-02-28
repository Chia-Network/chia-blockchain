import itertools
import logging
from typing import Awaitable, Callable, Dict, List, Optional, Tuple, Set
from random import Random
import pytest

from chia.data_layer.data_layer_errors import (
    InternalKeyValueError,
    InternalLeftRightNotBytes32Error,
    NodeHashError,
    TerminalLeftRightError,
    TreeGenerationIncrementingError,
)
from chia.data_layer.data_layer_types import (
    NodeType,
    ProofOfInclusion,
    ProofOfInclusionLayer,
    Side,
    Status,
    InternalNode,
    TerminalNode,
    InsertionData,
    DeletionData,
    OperationType,
    DiffData,
    DownloadMode,
)
from chia.data_layer.data_layer_util import _debug_dump
from chia.data_layer.data_store import DataStore
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.tree_hash import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.db_wrapper import DBWrapper
from chia.data_layer.data_layer_types import Subscription
from chia.util.ints import uint16
from tests.core.data_layer.util import (
    add_0123_example,
    add_01234567_example,
    Example,
)


log = logging.getLogger(__name__)


pytestmark = pytest.mark.data_layer


table_columns: Dict[str, List[str]] = {
    "node": ["hash", "node_type", "left", "right", "key", "value"],
    "root": ["tree_id", "generation", "node_hash", "status", "submissions"],
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
        await raw_data_store.create_tree(tree_id=bad_tree_id)  # type: ignore[arg-type]


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
    key = b"\x01\x02"
    value = b"abc"

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
    key = b"\x01\x02"
    value = b"abc"

    node_hash = await data_store.insert(key=key, value=value, tree_id=tree_id, reference_node_hash=None, side=None)
    assert node_hash == Program.to((key, value)).get_tree_hash()


@pytest.mark.asyncio
async def test_insert_increments_generation(data_store: DataStore, tree_id: bytes32) -> None:
    keys = [b"a", b"b", b"c", b"d"]  # efghijklmnopqrstuvwxyz")
    value = b"\x01\x02\x03"

    generations = []
    expected = []

    node_hash = None
    for key, expected_generation in zip(keys, itertools.count(start=1)):
        node_hash = await data_store.insert(
            key=key,
            value=value,
            tree_id=tree_id,
            reference_node_hash=node_hash,
            side=None if node_hash is None else Side.LEFT,
        )
        generation = await data_store.get_tree_generation(tree_id=tree_id)
        generations.append(generation)
        expected.append(expected_generation)

    assert generations == expected


@pytest.mark.asyncio
async def test_insert_internal_node_does_nothing_if_matching(data_store: DataStore, tree_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    kv_node = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)
    ancestors = await data_store.get_ancestors(node_hash=kv_node.hash, tree_id=tree_id)
    parent = ancestors[0]

    async with data_store.db_wrapper.locked_transaction():
        cursor = await data_store.db.execute("SELECT * FROM node")
        before = await cursor.fetchall()

    async with data_store.db_wrapper.locked_transaction():
        await data_store._insert_internal_node(left_hash=parent.left_hash, right_hash=parent.right_hash)

    async with data_store.db_wrapper.locked_transaction():
        cursor = await data_store.db.execute("SELECT * FROM node")
        after = await cursor.fetchall()

    assert after == before


@pytest.mark.asyncio
async def test_insert_terminal_node_does_nothing_if_matching(data_store: DataStore, tree_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    kv_node = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    async with data_store.db_wrapper.locked_transaction():
        cursor = await data_store.db.execute("SELECT * FROM node")
        before = await cursor.fetchall()

    async with data_store.db_wrapper.locked_transaction():
        await data_store._insert_terminal_node(key=kv_node.key, value=kv_node.value)

    async with data_store.db_wrapper.locked_transaction():
        cursor = await data_store.db.execute("SELECT * FROM node")
        after = await cursor.fetchall()

    assert after == before


@pytest.mark.asyncio
async def test_build_a_tree(
    data_store: DataStore,
    tree_id: bytes32,
    create_example: Callable[[DataStore, bytes32], Example],
) -> None:
    example = await create_example(data_store=data_store, tree_id=tree_id)  # type: ignore

    await _debug_dump(db=data_store.db, description="final")
    actual = await data_store.get_tree_as_program(tree_id=tree_id)
    # print("actual  ", actual.as_python())
    # print("expected", example.expected.as_python())
    assert actual == example.expected


@pytest.mark.asyncio
async def test_get_node_by_key(data_store: DataStore, tree_id: bytes32) -> None:
    example = await add_0123_example(data_store=data_store, tree_id=tree_id)

    key_node_hash = example.terminal_nodes[2]

    # TODO: make a nicer relationship between the hash and the key

    actual = await data_store.get_node_by_key(key=b"\x02", tree_id=tree_id)
    assert actual.hash == key_node_hash


@pytest.mark.asyncio
async def test_get_ancestors(data_store: DataStore, tree_id: bytes32) -> None:
    example = await add_0123_example(data_store=data_store, tree_id=tree_id)

    reference_node_hash = example.terminal_nodes[2]

    ancestors = await data_store.get_ancestors(node_hash=reference_node_hash, tree_id=tree_id)
    hashes = [node.hash.hex() for node in ancestors]

    # TODO: reverify these are correct
    assert hashes == [
        "3ab212e30b0e746d81a993e39f2cb4ba843412d44b402c1117a500d6451309e3",
        "c852ecd8fb61549a0a42f9eb9dde65e6c94a01934dbd9c1d35ab94e2a0ae58e2",
    ]

    ancestors_2 = await data_store.get_ancestors_optimized(node_hash=reference_node_hash, tree_id=tree_id)
    assert ancestors == ancestors_2


@pytest.mark.asyncio
async def test_get_ancestors_optimized(data_store: DataStore, tree_id: bytes32) -> None:
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
            hint_keys_values = await data_store.get_keys_values_dict(tree_id)
            if not deleted_all:
                while node_count > 0:
                    node_count -= 1
                    seed = bytes32(b"0" * 32)
                    node_hash = await data_store.get_terminal_node_for_seed(tree_id, seed)
                    assert node_hash is not None
                    node = await data_store.get_node(node_hash)
                    assert isinstance(node, TerminalNode)
                    await data_store.delete(key=node.key, tree_id=tree_id, hint_keys_values=hint_keys_values)
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
        node_hash = await data_store.get_terminal_node_for_seed(tree_id, seed)
        if is_insert:
            node_count += 1
            side = None if node_hash is None else data_store.get_side_for_seed(seed)

            node_hash = await data_store.insert(
                key=key,
                value=value,
                tree_id=tree_id,
                reference_node_hash=node_hash,
                side=side,
                use_optimized=False,
            )
            if node_hash is not None:
                generation = await data_store.get_tree_generation(tree_id=tree_id)
                current_ancestors = await data_store.get_ancestors(node_hash=node_hash, tree_id=tree_id)
                ancestors.append((generation, node_hash, current_ancestors))
        else:
            node_count -= 1
            assert node_hash is not None
            node = await data_store.get_node(node_hash)
            assert isinstance(node, TerminalNode)
            await data_store.delete(key=node.key, tree_id=tree_id, use_optimized=False)

    for generation, node_hash, expected_ancestors in ancestors:
        current_ancestors = await data_store.get_ancestors_optimized(
            node_hash=node_hash, tree_id=tree_id, generation=generation
        )
        assert current_ancestors == expected_ancestors


@pytest.mark.asyncio
async def test_ancestor_table_unique_inserts(data_store: DataStore, tree_id: bytes32) -> None:
    await add_0123_example(data_store=data_store, tree_id=tree_id)
    hash_1 = bytes32.from_hexstr("0763561814685fbf92f6ca71fbb1cb11821951450d996375c239979bd63e9535")
    hash_2 = bytes32.from_hexstr("924be8ff27e84cba17f5bc918097f8410fab9824713a4668a21c8e060a8cab40")
    await data_store._insert_ancestor_table(hash_1, hash_2, tree_id, 2)
    with pytest.raises(Exception):
        await data_store._insert_ancestor_table(hash_1, hash_1, tree_id, 2)
    await data_store._insert_ancestor_table(hash_1, hash_2, tree_id, 2)


@pytest.mark.asyncio
async def test_get_pairs(
    data_store: DataStore,
    tree_id: bytes32,
    create_example: Callable[[DataStore, bytes32], Awaitable[Example]],
) -> None:
    example = await create_example(data_store, tree_id)

    pairs = await data_store.get_keys_values(tree_id=tree_id)

    assert [node.hash for node in pairs] == example.terminal_nodes


@pytest.mark.asyncio
async def test_get_pairs_when_empty(data_store: DataStore, tree_id: bytes32) -> None:
    pairs = await data_store.get_keys_values(tree_id=tree_id)

    assert pairs == []


@pytest.mark.parametrize(
    argnames=["first_value", "second_value"],
    argvalues=[[b"\x06", b"\x06"], [b"\x06", b"\x07"]],
    ids=["same values", "different values"],
)
@pytest.mark.asyncio()
async def test_inserting_duplicate_key_fails(
    data_store: DataStore,
    tree_id: bytes32,
    first_value: bytes,
    second_value: bytes,
) -> None:
    key = b"\x05"

    first_hash = await data_store.insert(
        key=key,
        value=first_value,
        tree_id=tree_id,
        reference_node_hash=None,
        side=None,
    )

    # TODO: more specific exception
    with pytest.raises(Exception):
        await data_store.insert(
            key=key,
            value=second_value,
            tree_id=tree_id,
            reference_node_hash=first_hash,
            side=Side.RIGHT,
        )

    hint_keys_values = await data_store.get_keys_values_dict(tree_id=tree_id)
    # TODO: more specific exception
    with pytest.raises(Exception):
        await data_store.insert(
            key=key,
            value=second_value,
            tree_id=tree_id,
            reference_node_hash=first_hash,
            side=Side.RIGHT,
            hint_keys_values=hint_keys_values,
        )


@pytest.mark.xfail()
@pytest.mark.asyncio()
async def test_autoinsert_balances_from_scratch(data_store: DataStore, tree_id: bytes32) -> None:
    expected = Program.to(
        (
            (
                (
                    (b"\x00", b"\x10\x00"),
                    (b"\x01", b"\x11\x01"),
                ),
                (
                    (b"\x02", b"\x12\x02"),
                    (b"\x03", b"\x13\x03"),
                ),
            ),
            (
                (
                    (b"\x04", b"\x14\x04"),
                    (b"\x05", b"\x15\x05"),
                ),
                (
                    (b"\x06", b"\x16\x06"),
                    (b"\x07", b"\x17\x07"),
                ),
            ),
        ),
    )

    for n in [0, 4, 2, 6, 1, 3, 5, 7]:
        await data_store.autoinsert(
            key=bytes([n]),
            value=bytes([0x10 + n, n]),
            tree_id=tree_id,
        )

    result = await data_store.get_tree_as_program(tree_id=tree_id)

    assert result == expected


@pytest.mark.xfail()
@pytest.mark.asyncio()
async def test_autoinsert_balances_gaps(data_store: DataStore, tree_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    expected = Program.to(
        (
            (
                (
                    (b"\x00", b"\x10\x00"),
                    (b"\x01", b"\x11\x01"),
                ),
                (
                    (b"\x02", b"\x12\x02"),
                    (b"\x03", b"\x13\x03"),
                ),
            ),
            (
                (
                    (b"\x04", b"\x14\x04"),
                    (b"\x05", b"\x15\x05"),
                ),
                (
                    (b"\x06", b"\x16\x06"),
                    (b"\x07", b"\x17\x07"),
                ),
            ),
        ),
    )

    ns = [1, 5]

    for n in ns:
        await data_store.delete(key=Program.to(bytes([n])), tree_id=tree_id)

    for n in ns:
        await data_store.autoinsert(
            key=bytes([n]),
            value=bytes([0x10 + n, n]),
            tree_id=tree_id,
        )

    result = await data_store.get_tree_as_program(tree_id=tree_id)

    assert result == expected


@pytest.mark.parametrize(
    "use_hint",
    [True, False],
)
@pytest.mark.asyncio()
async def test_delete_from_left_both_terminal(data_store: DataStore, tree_id: bytes32, use_hint: bool) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    hint_keys_values = None
    if use_hint:
        hint_keys_values = await data_store.get_keys_values_dict(tree_id=tree_id)

    expected = Program.to(
        (
            (
                (
                    (b"\x00", b"\x10\x00"),
                    (b"\x01", b"\x11\x01"),
                ),
                (
                    (b"\x02", b"\x12\x02"),
                    (b"\x03", b"\x13\x03"),
                ),
            ),
            (
                (b"\x05", b"\x15\x05"),
                (
                    (b"\x06", b"\x16\x06"),
                    (b"\x07", b"\x17\x07"),
                ),
            ),
        ),
    )

    await data_store.delete(key=Program.to(b"\x04"), tree_id=tree_id, hint_keys_values=hint_keys_values)
    result = await data_store.get_tree_as_program(tree_id=tree_id)

    assert result == expected


@pytest.mark.parametrize(
    "use_hint",
    [True, False],
)
@pytest.mark.asyncio()
async def test_delete_from_left_other_not_terminal(data_store: DataStore, tree_id: bytes32, use_hint: bool) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    hint_keys_values = None
    if use_hint:
        hint_keys_values = await data_store.get_keys_values_dict(tree_id=tree_id)

    expected = Program.to(
        (
            (
                (
                    (b"\x00", b"\x10\x00"),
                    (b"\x01", b"\x11\x01"),
                ),
                (
                    (b"\x02", b"\x12\x02"),
                    (b"\x03", b"\x13\x03"),
                ),
            ),
            (
                (b"\x06", b"\x16\x06"),
                (b"\x07", b"\x17\x07"),
            ),
        ),
    )

    await data_store.delete(key=Program.to(b"\x04"), tree_id=tree_id, hint_keys_values=hint_keys_values)
    await data_store.delete(key=Program.to(b"\x05"), tree_id=tree_id, hint_keys_values=hint_keys_values)
    result = await data_store.get_tree_as_program(tree_id=tree_id)

    assert result == expected


@pytest.mark.parametrize(
    "use_hint",
    [True, False],
)
@pytest.mark.asyncio()
async def test_delete_from_right_both_terminal(data_store: DataStore, tree_id: bytes32, use_hint: bool) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    hint_keys_values = None
    if use_hint:
        hint_keys_values = await data_store.get_keys_values_dict(tree_id=tree_id)

    expected = Program.to(
        (
            (
                (
                    (b"\x00", b"\x10\x00"),
                    (b"\x01", b"\x11\x01"),
                ),
                (b"\x02", b"\x12\x02"),
            ),
            (
                (
                    (b"\x04", b"\x14\x04"),
                    (b"\x05", b"\x15\x05"),
                ),
                (
                    (b"\x06", b"\x16\x06"),
                    (b"\x07", b"\x17\x07"),
                ),
            ),
        ),
    )

    await data_store.delete(key=Program.to(b"\x03"), tree_id=tree_id, hint_keys_values=hint_keys_values)
    result = await data_store.get_tree_as_program(tree_id=tree_id)

    assert result == expected


@pytest.mark.parametrize(
    "use_hint",
    [True, False],
)
@pytest.mark.asyncio()
async def test_delete_from_right_other_not_terminal(data_store: DataStore, tree_id: bytes32, use_hint: bool) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)

    hint_keys_values = None
    if use_hint:
        hint_keys_values = await data_store.get_keys_values_dict(tree_id=tree_id)

    expected = Program.to(
        (
            (
                (b"\x00", b"\x10\x00"),
                (b"\x01", b"\x11\x01"),
            ),
            (
                (
                    (b"\x04", b"\x14\x04"),
                    (b"\x05", b"\x15\x05"),
                ),
                (
                    (b"\x06", b"\x16\x06"),
                    (b"\x07", b"\x17\x07"),
                ),
            ),
        ),
    )

    await data_store.delete(key=Program.to(b"\x03"), tree_id=tree_id, hint_keys_values=hint_keys_values)
    await data_store.delete(key=Program.to(b"\x02"), tree_id=tree_id, hint_keys_values=hint_keys_values)
    result = await data_store.get_tree_as_program(tree_id=tree_id)

    assert result == expected


@pytest.mark.asyncio
async def test_proof_of_inclusion_by_hash(data_store: DataStore, tree_id: bytes32) -> None:
    """A proof of inclusion contains the expected sibling side, sibling hash, combined
    hash, key, value, and root hash values.
    """
    await add_01234567_example(data_store=data_store, tree_id=tree_id)
    root = await data_store.get_tree_root(tree_id=tree_id)
    assert root.node_hash is not None
    node = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    proof = await data_store.get_proof_of_inclusion_by_hash(node_hash=node.hash, tree_id=tree_id)

    print(node)
    await _debug_dump(db=data_store.db)

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

    assert proof == ProofOfInclusion(node_hash=node.hash, root_hash=root.node_hash, layers=expected_layers)


@pytest.mark.asyncio
async def test_proof_of_inclusion_by_hash_no_ancestors(data_store: DataStore, tree_id: bytes32) -> None:
    """Check proper proof of inclusion creation when the node being proved is the root."""
    await data_store.autoinsert(key=b"\x04", value=b"\x03", tree_id=tree_id)
    root = await data_store.get_tree_root(tree_id=tree_id)
    assert root.node_hash is not None
    node = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    proof = await data_store.get_proof_of_inclusion_by_hash(node_hash=node.hash, tree_id=tree_id)

    assert proof == ProofOfInclusion(node_hash=node.hash, root_hash=root.node_hash, layers=[])


@pytest.mark.asyncio
async def test_proof_of_inclusion_by_hash_program(data_store: DataStore, tree_id: bytes32) -> None:
    """The proof of inclusion program has the expected Python equivalence."""

    await add_01234567_example(data_store=data_store, tree_id=tree_id)
    node = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    proof = await data_store.get_proof_of_inclusion_by_hash(node_hash=node.hash, tree_id=tree_id)

    assert proof.as_program() == [
        b"\x04",
        [
            bytes32.fromhex("fb66fe539b3eb2020dfbfadfd601fa318521292b41f04c2057c16fca6b947ca1"),
            bytes32.fromhex("6d3af8d93db948e8b6aa4386958e137c6be8bab726db86789594b3588b35adcd"),
            bytes32.fromhex("c852ecd8fb61549a0a42f9eb9dde65e6c94a01934dbd9c1d35ab94e2a0ae58e2"),
        ],
    ]


@pytest.mark.asyncio
async def test_proof_of_inclusion_by_hash_equals_by_key(data_store: DataStore, tree_id: bytes32) -> None:
    """The proof of inclusion is equal between hash and key requests."""

    await add_01234567_example(data_store=data_store, tree_id=tree_id)
    node = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    proof_by_hash = await data_store.get_proof_of_inclusion_by_hash(node_hash=node.hash, tree_id=tree_id)
    proof_by_key = await data_store.get_proof_of_inclusion_by_key(key=b"\x04", tree_id=tree_id)

    assert proof_by_hash == proof_by_key


@pytest.mark.asyncio
async def test_proof_of_inclusion_by_hash_bytes(data_store: DataStore, tree_id: bytes32) -> None:
    """The proof of inclusion provided by the data store is able to be converted to a
    program and subsequently to bytes.
    """
    await add_01234567_example(data_store=data_store, tree_id=tree_id)
    node = await data_store.get_node_by_key(key=b"\x04", tree_id=tree_id)

    proof = await data_store.get_proof_of_inclusion_by_hash(node_hash=node.hash, tree_id=tree_id)

    expected = (
        b"\xff\x04\xff\xff\xa0\xfbf\xfeS\x9b>\xb2\x02\r\xfb\xfa\xdf\xd6\x01\xfa1\x85!)"
        b"+A\xf0L W\xc1o\xcak\x94|\xa1\xff\xa0m:\xf8\xd9=\xb9H\xe8\xb6\xaaC\x86\x95"
        b"\x8e\x13|k\xe8\xba\xb7&\xdb\x86x\x95\x94\xb3X\x8b5\xad\xcd\xff\xa0\xc8R\xec"
        b"\xd8\xfbaT\x9a\nB\xf9\xeb\x9d\xdee\xe6\xc9J\x01\x93M\xbd\x9c\x1d5\xab\x94"
        b"\xe2\xa0\xaeX\xe2\x80\x80"
    )

    assert bytes(proof.as_program()) == expected


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


@pytest.mark.asyncio
async def test_check_roots_are_incrementing_missing_zero(raw_data_store: DataStore) -> None:
    tree_id = hexstr_to_bytes("c954ab71ffaf5b0f129b04b35fdc7c84541f4375167e730e2646bfcfdb7cf2cd")

    async with raw_data_store.db_wrapper.locked_transaction():
        for generation in range(1, 5):
            await raw_data_store.db.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                {
                    "tree_id": tree_id.hex(),
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


@pytest.mark.asyncio
async def test_check_roots_are_incrementing_gap(raw_data_store: DataStore) -> None:
    tree_id = hexstr_to_bytes("c954ab71ffaf5b0f129b04b35fdc7c84541f4375167e730e2646bfcfdb7cf2cd")

    async with raw_data_store.db_wrapper.locked_transaction():
        for generation in [*range(5), *range(6, 10)]:
            await raw_data_store.db.execute(
                """
                INSERT INTO root(tree_id, generation, node_hash, status)
                VALUES(:tree_id, :generation, :node_hash, :status)
                """,
                {
                    "tree_id": tree_id.hex(),
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


@pytest.mark.asyncio
async def test_root_state(data_store: DataStore, tree_id: bytes32) -> None:
    key = b"\x01\x02"
    value = b"abc"
    await data_store.insert(key=key, value=value, tree_id=tree_id, reference_node_hash=None, side=None)
    is_empty = await data_store.table_is_empty(tree_id=tree_id)
    root = await data_store.get_tree_root(tree_id)
    assert root.status.value == Status.PENDING.value
    assert not is_empty


@pytest.mark.asyncio
async def test_change_root_state(data_store: DataStore, tree_id: bytes32) -> None:
    key = b"\x01\x02"
    value = b"abc"
    await data_store.insert(key=key, value=value, tree_id=tree_id, reference_node_hash=None, side=None)
    is_empty = await data_store.table_is_empty(tree_id=tree_id)
    root = await data_store.get_tree_root(tree_id)
    assert root.status.value == Status.PENDING.value
    await data_store.change_root_status(root, Status.COMMITTED)
    root = await data_store.get_tree_root(tree_id)
    assert root.status.value == Status.COMMITTED.value
    assert not is_empty


@pytest.mark.asyncio
async def test_left_to_right_ordering(data_store: DataStore, tree_id: bytes32) -> None:
    await add_01234567_example(data_store=data_store, tree_id=tree_id)
    root = await data_store.get_tree_root(tree_id)
    assert root.node_hash is not None
    all_nodes = await data_store.get_left_to_right_ordering(root.node_hash, tree_id, False, num_nodes=1000)
    expected_nodes = [
        bytes32.from_hexstr("7a5193a4e31a0a72f6623dfeb2876022ab74a48abb5966088a1c6f5451cc5d81"),
        bytes32.from_hexstr("c852ecd8fb61549a0a42f9eb9dde65e6c94a01934dbd9c1d35ab94e2a0ae58e2"),
        bytes32.from_hexstr("9831a17b4c16ee6167ce4748ccd98ce1ccd0cf43f4dce8298390fd46c2d2e3b0"),
        bytes32.from_hexstr("cb9ab4524540e37fd79377891ff46c143dc97c2eb57f4c106c07e9c321100874"),
        bytes32.from_hexstr("0763561814685fbf92f6ca71fbb1cb11821951450d996375c239979bd63e9535"),
        bytes32.from_hexstr("3ab212e30b0e746d81a993e39f2cb4ba843412d44b402c1117a500d6451309e3"),
        bytes32.from_hexstr("924be8ff27e84cba17f5bc918097f8410fab9824713a4668a21c8e060a8cab40"),
        bytes32.from_hexstr("d068b836d74781f7025dade5b300fcb0474a71d9ac27b8c7dfb7f85750a841a5"),
        bytes32.from_hexstr("5f67a0ab1976e090b834bf70e5ce2a0f0a9cd474e19a905348c44ae12274d30b"),
        bytes32.from_hexstr("36cb1fc56017944213055da8cb0178fb0938c32df3ec4472f5edf0dff85ba4a3"),
        bytes32.from_hexstr("19a28f80fe7bc17a2ef67836d40bee765fb20e58d5001517e0f1070de895c50b"),
        bytes32.from_hexstr("fb66fe539b3eb2020dfbfadfd601fa318521292b41f04c2057c16fca6b947ca1"),
        bytes32.from_hexstr("6d3af8d93db948e8b6aa4386958e137c6be8bab726db86789594b3588b35adcd"),
        bytes32.from_hexstr("1d2534d20e63e9f730fc4b919857fb0f9529eaaab65c8baf3c443aa1c327b510"),
        bytes32.from_hexstr("50e2f97295de32c7b0eaea32bf1969ceab2e4645b17882e8f1080d143aa262ab"),
    ]
    assert [node.hash for node in all_nodes] == expected_nodes
    nodes_2 = await data_store.get_left_to_right_ordering(
        bytes32.from_hexstr("cb9ab4524540e37fd79377891ff46c143dc97c2eb57f4c106c07e9c321100874"),
        tree_id,
        False,
        num_nodes=100,
    )
    assert [node.hash for node in nodes_2] == expected_nodes[3:]
    nodes_3 = await data_store.get_left_to_right_ordering(
        bytes32.from_hexstr("924be8ff27e84cba17f5bc918097f8410fab9824713a4668a21c8e060a8cab40"),
        tree_id,
        False,
        num_nodes=4,
    )
    assert [node.hash for node in nodes_3] == expected_nodes[6:10]
    nodes_4 = await data_store.get_left_to_right_ordering(
        bytes32.from_hexstr("cb9ab4524540e37fd79377891ff46c143dc97c2eb57f4c106c07e9c321100874"),
        tree_id,
        True,
        num_nodes=100,
    )
    assert nodes_4 == nodes_2[:1]


@pytest.mark.asyncio
async def test_get_operation_1(data_store: DataStore, tree_id: bytes32) -> None:
    key = b"\x01\x02"
    value = b"abc"

    await data_store.insert(key=key, value=value, tree_id=tree_id, reference_node_hash=None, side=None)
    root = await data_store.get_tree_root(tree_id)
    status = Status.COMMITTED
    operation = await data_store.get_single_operation(None, root.node_hash, status)
    assert isinstance(operation, InsertionData)
    assert operation.key == b"\x01\x02"
    assert operation.value == b"abc"

    await data_store.delete(key=key, tree_id=tree_id)
    root_2 = await data_store.get_tree_root(tree_id)
    operation_2 = await data_store.get_single_operation(root.node_hash, root_2.node_hash, status)
    assert isinstance(operation_2, DeletionData)
    assert operation_2.key == b"\x01\x02"


@pytest.mark.asyncio
async def test_get_operation_2(data_store: DataStore, tree_id: bytes32) -> None:
    key = b"\x01\x02"
    value = b"abc"

    example = await add_01234567_example(data_store=data_store, tree_id=tree_id)
    terminal_hash = example.terminal_nodes[0]
    root = await data_store.get_tree_root(tree_id)
    status = Status.COMMITTED
    await data_store.insert(key=key, value=value, tree_id=tree_id, reference_node_hash=terminal_hash, side=Side.LEFT)

    root_2 = await data_store.get_tree_root(tree_id)
    operation = await data_store.get_single_operation(root.node_hash, root_2.node_hash, status)
    assert isinstance(operation, InsertionData)
    assert operation.key == b"\x01\x02"
    assert operation.value == b"abc"

    await data_store.delete(key=key, tree_id=tree_id)
    root_3 = await data_store.get_tree_root(tree_id)
    operation_2 = await data_store.get_single_operation(root_2.node_hash, root_3.node_hash, status)
    assert isinstance(operation_2, DeletionData)
    assert operation_2.key == b"\x01\x02"


@pytest.mark.asyncio
async def test_get_operation_3(data_store: DataStore, tree_id: bytes32) -> None:
    await add_0123_example(data_store, tree_id)
    root = await data_store.get_tree_root(tree_id)
    status = Status.COMMITTED

    await data_store.delete(key=b"\x00", tree_id=tree_id)
    root_2 = await data_store.get_tree_root(tree_id)
    operation = await data_store.get_single_operation(root.node_hash, root_2.node_hash, status)
    assert isinstance(operation, DeletionData)
    assert operation.key == b"\x00"

    # Test the special case where both left and right hashes are different within a diff.
    # This should happen only if deleted subtree has only 1 node and its connected to the root.
    await data_store.delete(key=b"\x01", tree_id=tree_id)
    root_3 = await data_store.get_tree_root(tree_id)
    operation_2 = await data_store.get_single_operation(root_2.node_hash, root_3.node_hash, status)
    assert isinstance(operation_2, DeletionData)
    assert operation_2.key == b"\x01"


@pytest.mark.asyncio
async def test_kv_diff(data_store: DataStore, tree_id: bytes32) -> None:
    random = Random()
    random.seed(100, version=2)
    insertions = 0
    expected_diff: Set[DiffData] = set()
    for i in range(500):
        key = (i + 100).to_bytes(4, byteorder="big")
        value = (i + 200).to_bytes(4, byteorder="big")
        seed = Program.to((key, value)).get_tree_hash()
        node_hash = await data_store.get_terminal_node_for_seed(tree_id, seed)
        if random.randint(0, 4) > 0 or insertions < 10:
            insertions += 1
            side = None if node_hash is None else data_store.get_side_for_seed(seed)

            _ = await data_store.insert(
                key=key,
                value=value,
                tree_id=tree_id,
                reference_node_hash=node_hash,
                side=side,
            )
            if i > 200:
                expected_diff.add(DiffData(OperationType.INSERT, key, value))
        else:
            assert node_hash is not None
            node = await data_store.get_node(node_hash)
            assert isinstance(node, TerminalNode)
            await data_store.delete(key=node.key, tree_id=tree_id)
            if i > 200:
                if DiffData(OperationType.INSERT, node.key, node.value) in expected_diff:
                    expected_diff.remove(DiffData(OperationType.INSERT, node.key, node.value))
                else:
                    expected_diff.add(DiffData(OperationType.DELETE, node.key, node.value))
        if i == 200:
            root_start = await data_store.get_tree_root(tree_id)

    root_end = await data_store.get_tree_root(tree_id)
    assert root_start.node_hash is not None
    assert root_end.node_hash is not None
    diffs = await data_store.get_kv_diff(tree_id, root_start.node_hash, root_end.node_hash)
    assert diffs == expected_diff


@pytest.mark.asyncio
async def test_kv_diff_2(data_store: DataStore, tree_id: bytes32) -> None:
    node_hash = await data_store.insert(
        key=b"000",
        value=b"000",
        tree_id=tree_id,
        reference_node_hash=None,
        side=None,
    )
    empty_hash = bytes32([0] * 32)
    invalid_hash = bytes32([0] * 31 + [1])
    diff_1 = await data_store.get_kv_diff(tree_id, empty_hash, node_hash)
    assert diff_1 == set([DiffData(OperationType.INSERT, b"000", b"000")])
    diff_2 = await data_store.get_kv_diff(tree_id, node_hash, empty_hash)
    assert diff_2 == set([DiffData(OperationType.DELETE, b"000", b"000")])
    diff_3 = await data_store.get_kv_diff(tree_id, invalid_hash, node_hash)
    assert diff_3 == set()


@pytest.mark.asyncio
async def test_rollback_to_generation(data_store: DataStore, tree_id: bytes32) -> None:
    await add_0123_example(data_store, tree_id)
    expected_hashes = []
    roots = await data_store.get_roots_between(tree_id, 1, 5)
    for generation, root in enumerate(roots):
        expected_hashes.append((generation + 1, root.node_hash))
    for generation, expected_hash in reversed(expected_hashes):
        await data_store.rollback_to_generation(tree_id, generation)
        root = await data_store.get_tree_root(tree_id)
        assert root.node_hash == expected_hash


@pytest.mark.asyncio
async def test_subscribe_unsubscribe(data_store: DataStore, tree_id: bytes32) -> None:
    await data_store.subscribe(Subscription(tree_id, DownloadMode.HISTORY, "127.0.0.1", uint16(8000)))
    assert await data_store.get_subscriptions() == [
        Subscription(tree_id, DownloadMode.HISTORY, "127.0.0.1", uint16(8000))
    ]
    await data_store.update_existing_subscription(Subscription(tree_id, DownloadMode.HISTORY, "0.0.0.0", uint16(8000)))
    assert await data_store.get_subscriptions() == [
        Subscription(tree_id, DownloadMode.HISTORY, "0.0.0.0", uint16(8000))
    ]
    await data_store.update_existing_subscription(Subscription(tree_id, DownloadMode.HISTORY, "0.0.0.0", uint16(8001)))
    assert await data_store.get_subscriptions() == [
        Subscription(tree_id, DownloadMode.HISTORY, "0.0.0.0", uint16(8001))
    ]
    await data_store.unsubscribe(tree_id)
    assert await data_store.get_subscriptions() == []
