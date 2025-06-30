from __future__ import annotations

from chia.consensus.coin_store_protocol import CoinStoreProtocol
from chia.types.coin_record import CoinRecord
from chia.util.db_wrapper import DBWrapper2


async def add_coin_records_to_db(coin_store: CoinStoreProtocol, records: list[CoinRecord]) -> None:
    if len(records) == 0:
        return
    db_wrapper = getattr(coin_store, "db_wrapper", None)
    assert isinstance(db_wrapper, DBWrapper2), "CoinStore must use DBWrapper2"
    async with db_wrapper.writer_maybe_transaction() as conn:
        await conn.executemany(
            "INSERT INTO coin_record VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    record.coin.name(),
                    record.confirmed_block_index,
                    record.spent_block_index,
                    int(record.coinbase),
                    record.coin.puzzle_hash,
                    record.coin.parent_coin_info,
                    record.coin.amount.stream_to_bytes(),
                    record.timestamp,
                )
                for record in records
            ),
        )
