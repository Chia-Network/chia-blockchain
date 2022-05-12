# TODO: remove or formalize this
import aiosqlite as aiosqlite

from chia.data_layer.data_layer_types import Node, node_type_to_class


async def _debug_dump(read_connection: aiosqlite.Connection, description: str = "") -> None:
    cursor = await read_connection.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print("-" * 50, description, flush=True)
    for [name] in await cursor.fetchall():
        cursor = await read_connection.execute(f"SELECT * FROM {name}")
        print(f"\n -- {name} ------", flush=True)
        async for row in cursor:
            print(f"        {dict(row)}")


def row_to_node(row: aiosqlite.Row) -> Node:
    cls = node_type_to_class[row["node_type"]]
    return cls.from_row(row=row)
