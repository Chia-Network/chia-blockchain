from __future__ import annotations

import contextlib
import logging
import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, TextIO

from chia.consensus.block_height_map import BlockHeightMap
from chia.full_node.block_store import BlockStore
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.full_node.store_protocols import NodeStores, OpenNodeStores
from chia.util.db_synchronous import db_synchronous_on
from chia.util.db_version import lookup_db_version, set_db_version_async
from chia.util.db_wrapper import DBWrapper2, manage_connection
from chia.util.path import path_from_root

log = logging.getLogger(__name__)


def sqlite_node_stores(config: dict[str, Any], root_path: Path) -> OpenNodeStores:
    """
    The SQLite stores for a full node with this (full_node section) config.
    The block, coin and hint stores share one DBWrapper2, so the block and
    coin writes in Blockchain.add_block commit in one transaction.
    """
    db_path_replaced: str = config["database_path"].replace("CHALLENGE", config["selected_network"])
    db_path = path_from_root(root_path, db_path_replaced)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextlib.asynccontextmanager
    async def open_stores() -> AsyncGenerator[NodeStores, None]:
        sql_log_path: Path | None = None
        with contextlib.ExitStack() as exit_stack:
            sql_log_file: TextIO | None = None
            if config.get("log_sqlite_cmds", False):
                sql_log_path = path_from_root(root_path, "log/sql.log")
                log.info(f"logging SQL commands to {sql_log_path}")
                sql_log_file = exit_stack.enter_context(sql_log_path.open("a", encoding="utf-8"))

            # TODO: is this standardized and thus able to be handled by DBWrapper2?
            async with manage_connection(db_path, log_file=sql_log_file, name="version_check") as db_connection:
                db_version = await lookup_db_version(db_connection)

        log.info(f"using blockchain database {db_path}, which is version {db_version}")

        db_sync = db_synchronous_on(config.get("db_sync", "auto"))
        log.info(f"opening blockchain DB: synchronous={db_sync}")

        async with DBWrapper2.managed(
            db_path,
            db_version=db_version,
            reader_count=config.get("db_readers", 4),
            log_path=sql_log_path,
            synchronous=db_sync,
        ) as db_wrapper:
            if db_wrapper.db_version != 2:
                async with db_wrapper.reader_no_transaction() as conn:
                    async with conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='full_blocks'"
                    ) as cur:
                        if len(list(await cur.fetchall())) == 0:
                            try:
                                # this is a new DB file. Make it v2
                                async with db_wrapper.writer_maybe_transaction() as w_conn:
                                    await set_db_version_async(w_conn, 2)
                                    db_wrapper.db_version = 2
                                    log.info("blockchain database is empty, configuring as v2")
                            except sqlite3.OperationalError:
                                # it could be a database created with "chia init", which is
                                # empty except it has the database_version table
                                pass

            block_store = await BlockStore.create(db_wrapper)
            coin_store = await CoinStore.create(db_wrapper, block_store=block_store)
            hint_store = await HintStore.create(coin_store)
            height_map = await BlockHeightMap.create(db_path.parent, db_wrapper, config.get("selected_network"))
            yield NodeStores(
                block_store=block_store,
                block_archive=block_store,
                coin_store=coin_store,
                hint_store=hint_store,
                height_map=height_map,
            )

    return open_stores
