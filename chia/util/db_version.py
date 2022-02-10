from databases import Database


async def lookup_db_version(db: Database) -> int:
    try:
        row = await db.fetch_one("SELECT * from database_version")
        if row is not None and row[0] == 2:
            return 2
        else:
            return 1
    except Exception:
        # expects OperationalError('no such table: database_version')
        return 1
