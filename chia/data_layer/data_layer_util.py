# TODO: remove or formalize this
import aiosqlite as aiosqlite

from chia.data_layer.data_layer_types import Node, node_type_to_class
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32


def internal_hash(left_hash: bytes32, right_hash: bytes32) -> bytes32:
    # ignoring hint error here for:
    # https://github.com/Chia-Network/clvm/pull/102
    # https://github.com/Chia-Network/clvm/pull/106
    return Program.to((left_hash, right_hash)).get_tree_hash(left_hash, right_hash)  # type: ignore[no-any-return]


def leaf_hash(key: bytes, value: bytes) -> bytes32:
    # ignoring hint error here for:
    # https://github.com/Chia-Network/clvm/pull/102
    # https://github.com/Chia-Network/clvm/pull/106
    return Program.to((key, value)).get_tree_hash()  # type: ignore[no-any-return]


async def _debug_dump(db: aiosqlite.Connection, description: str = "") -> None:
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print("-" * 50, description, flush=True)
    for [name] in await cursor.fetchall():
        cursor = await db.execute(f"SELECT * FROM {name}")
        print(f"\n -- {name} ------", flush=True)
        async for row in cursor:
            print(f"        {dict(row)}")


# It is unclear how to properly satisfy the generic Row normally, let alone for
# dict-like rows.  https://github.com/python/typeshed/issues/8027
def row_to_node(row: aiosqlite.Row) -> Node:  # type: ignore[type-arg]
    cls = node_type_to_class[row["node_type"]]
    return cls.from_row(row=row)
