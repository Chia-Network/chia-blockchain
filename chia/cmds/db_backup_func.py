from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from chia.util.config import load_config
from chia.util.path import path_from_root


def db_backup_func(
    root_path: Path,
    backup_db_file: Optional[Path] = None,
    *,
    no_indexes: bool,
) -> None:
    config: Dict[str, Any] = load_config(root_path, "config.yaml")["full_node"]
    selected_network: str = config["selected_network"]
    db_pattern: str = config["database_path"]
    db_path_replaced: str = db_pattern.replace("CHALLENGE", selected_network)
    source_db = path_from_root(root_path, db_path_replaced)
    if backup_db_file is None:
        db_path_replaced_backup = db_path_replaced.replace("blockchain_", "vacuumed_blockchain_")
        backup_db_file = path_from_root(root_path, db_path_replaced_backup)

    backup_db(source_db, backup_db_file, no_indexes=no_indexes)

    print(f"\n\nDatabase backup finished : {backup_db_file}\n")


def backup_db(source_db: Path, backup_db: Path, *, no_indexes: bool) -> None:
    import sqlite3
    from contextlib import closing

    # VACUUM INTO is only available starting with SQLite version 3.27.0
    if not no_indexes and sqlite3.sqlite_version_info < (3, 27, 0):
        raise RuntimeError(
            f"SQLite {sqlite3.sqlite_version} not supported. Version needed is 3.27.0"
            f"\n\tuse '--no_indexes' option to create a backup without indexes instead."
            f"\n\tIn case of a restore, the missing indexes will be recreated during full node startup."
        )

    if not backup_db.parent.exists():
        print(f"backup destination path doesn't exist. {backup_db.parent}")
        raise RuntimeError(f"can't find {backup_db}")

    print(f"reading from blockchain database: {source_db}")
    print(f"writing to backup file: {backup_db}")
    with closing(sqlite3.connect(source_db)) as in_db:
        try:
            if no_indexes:
                in_db.execute("ATTACH DATABASE ? AS backup", (str(backup_db),))
                in_db.execute("pragma backup.journal_mode=OFF")
                in_db.execute("pragma backup.synchronous=OFF")
                # Use writable_schema=1 to allow create table using internal sqlite names like sqlite_stat1
                in_db.execute("pragma backup.writable_schema=1")
                cursor = in_db.cursor()
                for row in cursor.execute(
                    "select replace(sql,'CREATE TABLE ', 'CREATE TABLE backup.') from sqlite_master "
                    "where upper(type)='TABLE'"
                ):
                    in_db.execute(row[0])

                in_db.execute("BEGIN TRANSACTION")
                for row in cursor.execute(
                    "select 'INSERT INTO backup.'||name||' SELECT * FROM main.'||name from sqlite_master "
                    "where upper(type)='TABLE'"
                ):
                    in_db.execute(row[0])
                in_db.execute("COMMIT")
                in_db.execute("DETACH DATABASE backup")
            else:
                in_db.execute("VACUUM INTO ?", [str(backup_db)])
        except sqlite3.OperationalError as e:
            raise RuntimeError(
                f"backup failed with error: '{e}'"
                f"\n\tYour backup file {backup_db} is probably left over in an insconsistent state."
            )
