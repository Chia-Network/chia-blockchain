from __future__ import annotations

from collections.abc import Iterable

import aiosqlite


async def get_all_peers(connection: aiosqlite.Connection) -> Iterable[aiosqlite.Row]:
    cursor = await connection.execute("SELECT * FROM peers")
    return await cursor.fetchall()


async def add_peer(node_id: int, info: str, connection: aiosqlite.Connection) -> None:
    await connection.execute(
        """
        INSERT INTO peers (node_id, info)
        VALUES (?, ?)
        """,
        (node_id, info),
    )
    await connection.commit()


async def set_new_table(entries: list[tuple[int, int]], connection: aiosqlite.Connection) -> None:
    for node_id, bucket in entries:
        await connection.execute(
            "INSERT OR REPLACE INTO peer_new_table VALUES(?, ?)",
            (node_id, bucket),
        )
    await connection.commit()


async def get_new_table(connection: aiosqlite.Connection) -> list[tuple[int, int]]:
    cursor = await connection.execute("SELECT node_id, bucket from peer_new_table")
    entries = await cursor.fetchall()
    await cursor.close()
    return [(node_id, bucket) for node_id, bucket in entries]


async def update_peer_info(node_id: int, info: str, connection: aiosqlite.Connection) -> None:
    await connection.execute("UPDATE peers SET info = ? WHERE node_id = ?", (info, node_id))
    await connection.commit()


async def remove_peer(node_id: int, connection: aiosqlite.Connection) -> None:
    await connection.execute("DELETE FROM peers WHERE node_id = ?", (node_id,))
    await connection.commit()


async def clear_peers(connection: aiosqlite.Connection) -> None:
    await connection.execute("DELETE FROM peers")
    await connection.commit()
