from __future__ import annotations

from chia.types.coin_record import CoinRecord
from chia.util.db_wrapper import DBWrapper2


async def add_coin_records_to_db(db_wrapper: DBWrapper2, records: list[CoinRecord]) -> None:
    if len(records) == 0:
        return
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
