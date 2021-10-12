# TODO: remove or formalize this
import aiosqlite as aiosqlite

from chia.data_layer.data_layer_types import node_type_to_class, Node

async def _debug_dump(db: aiosqlite.Connection, description: str = "") -> None:
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print("-" * 50, description, flush=True)
    for [name] in await cursor.fetchall():
        cursor = await db.execute(f"SELECT * FROM {name}")
        print(f"\n -- {name} ------", flush=True)
        async for row in cursor:
            print(f"        {dict(row)}")


def row_to_node(row: aiosqlite.Row) -> Node:
    cls = node_type_to_class[row["node_type"]]
    return cls.from_row(row=row)
