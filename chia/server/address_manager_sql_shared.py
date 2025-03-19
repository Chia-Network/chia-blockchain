from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

import aiosqlite


async def get_all_peers(connection: aiosqlite.Connection) -> Iterable[aiosqlite.Row]:
    cursor = await connection.execute("SELECT * FROM peers")
    return await cursor.fetchall()


async def add_peer(
    node_id: int, info: str, is_tried: bool, ref_count: int, bucket: Optional[int], connection: aiosqlite.Connection
) -> None:
    await connection.execute(
        """
        INSERT INTO peers (node_id, info, is_tried, ref_count, bucket)
        VALUES (?, ?, ?, ?, ?)
        """,
        (node_id, info, is_tried, ref_count, bucket),
    )
    await connection.commit()


async def update_peer(
    node_id: int, info: str, is_tried: bool, ref_count: int, bucket: Optional[int], connection: aiosqlite.Connection
) -> None:
    await connection.execute(
        """
        UPDATE peers
        SET info = ?,
        is_tried = ?,
        ref_count = ?
        bucket = ?,
        WHERE node_id = ?
        """,
        (info, is_tried, ref_count, bucket, node_id),
    )
    await connection.commit()


async def update_peer_info(node_id: int, info: str, connection: aiosqlite.Connection) -> None:
    await connection.execute("UPDATE peers SET info = ? WHERE node_id = ?", (info, node_id))
    await connection.commit()


async def remove_peer(node_id: int, connection: aiosqlite.Connection) -> None:
    await connection.execute("DELETE FROM peers WHERE node_id = ?", (node_id,))
    await connection.commit()


async def clear_peers(connection: aiosqlite.Connection) -> None:
    await connection.execute("DELETE FROM peers")
    await connection.commit()
