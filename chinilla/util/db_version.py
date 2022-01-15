import aiosqlite


async def lookup_db_version(db: aiosqlite.Connection) -> int:
    try:
        cursor = await db.execute("SELECT * from database_version")
        row = await cursor.fetchone()
        if row is not None and row[0] == 2:
            return 2
        else:
            return 1
    except aiosqlite.OperationalError:
        # expects OperationalError('no such table: database_version')
        return 1
