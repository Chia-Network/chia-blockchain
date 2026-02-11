from __future__ import annotations

from sqlite3 import Row

from chia_rs import Coin, G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32, uint64
from typing_extensions import Self

from chia.pools.plotnft_drivers import PlotNFT, PoolConfig, PoolReward, UserConfig
from chia.types.blockchain_format.program import Program
from chia.util.db_wrapper import DBWrapper2
from chia.wallet.lineage_proof import LineageProof

DEFAULT_POOL_REWARDS_PER_CLAIM = 20


def _row_to_plotnft(row: Row, genesis_challenge: bytes32) -> PlotNFT:
    return PlotNFT(
        coin=Coin(parent_coin_info=bytes32(row[1]), puzzle_hash=bytes32(row[2]), amount=uint64.from_bytes(row[3])),
        singleton_lineage_proof=LineageProof.from_bytes(row[4]),
        launcher_id=bytes32(row[5]),
        user_config=UserConfig(synthetic_pubkey=G1Element.from_bytes(row[6])),
        pool_config=PoolConfig(
            pool_puzzle_hash=bytes32(row[7]),
            heightlock=uint32.from_bytes(row[8]),
            pool_memoization=Program.from_bytes(row[9]),
        )
        if row[7:10] != (b"", b"", b"")
        else None,
        genesis_challenge=genesis_challenge,
        exiting=False if row[10] == 0 else True,
        remarks=[row[11]] if row[11] is not None else [],
    )


class PlotNFTStore:
    db_wrapper: DBWrapper2
    genesis_challenge: bytes32

    @classmethod
    async def create(cls, wrapper: DBWrapper2, genesis_challenge: bytes32) -> Self:
        self = cls()
        self.db_wrapper = wrapper
        self.genesis_challenge = genesis_challenge

        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS plotnft2s( "
                " coin_id blob PRIMARY KEY,"
                " parent_coin_id blob,"
                " puzzle_hash blob,"
                " amount blob,"
                " lineage_proof blob,"
                " launcher_id blob,"
                " synthetic_pubkey blob,"
                " pool_puzzle_hash blob,"
                " timelock blob,"
                " pool_memoization blob,"
                " exiting boolean,"
                " remark string,"
                " created_height int)"
            )

            await conn.execute(
                "CREATE TABLE IF NOT EXISTS pool_reward2s( "
                " coin_id blob PRIMARY KEY,"
                " parent_coin_id blob,"
                " puzzle_hash blob,"
                " amount blob,"
                " singleton_id blob,"
                " height int,"
                " spent_height int)"
            )

            await conn.execute("CREATE TABLE IF NOT EXISTS finish_exiting_fee (wallet_id int PRIMARY KEY, fee blob)")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS finish_exiting_height (wallet_id int PRIMARY KEY, height int)"
            )

        return self

    async def add_plotnft(self, *, plotnft: PlotNFT, created_height: uint32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute_insert(
                "INSERT OR REPLACE INTO plotnft2s "
                "(coin_id, parent_coin_id, puzzle_hash, amount, lineage_proof, launcher_id, synthetic_pubkey, "
                "pool_puzzle_hash, timelock, pool_memoization, exiting, remark, created_height) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plotnft.coin.name(),
                    plotnft.coin.parent_coin_info,
                    plotnft.coin.puzzle_hash,
                    bytes(plotnft.coin.amount),
                    bytes(plotnft.singleton_lineage_proof),
                    plotnft.launcher_id,
                    bytes(plotnft.user_config.synthetic_pubkey),
                    plotnft.pool_config.pool_puzzle_hash if plotnft.pool_config is not None else b"",
                    bytes(plotnft.pool_config.heightlock) if plotnft.pool_config is not None else b"",
                    bytes(plotnft.pool_config.pool_memoization) if plotnft.pool_config is not None else b"",
                    plotnft.exiting,
                    str(plotnft.remarks[0].rest.atom, "utf8")
                    if len(plotnft.remarks) > 0 and plotnft.remarks[0].rest.atom is not None
                    else None,
                    created_height,
                ),
            )

    async def add_pool_reward(self, *, pool_reward: PoolReward) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute_insert(
                "INSERT OR REPLACE INTO pool_reward2s ("
                "coin_id, parent_coin_id, puzzle_hash, amount, singleton_id, height, spent_height) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    pool_reward.coin.name(),
                    pool_reward.coin.parent_coin_info,
                    pool_reward.coin.puzzle_hash,
                    bytes(pool_reward.coin.amount),
                    pool_reward.singleton_id,
                    pool_reward.height,
                    None,
                ),
            )

    async def mark_pool_reward_as_spent(self, *, reward_id: bytes32, spent_height: uint32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute_insert(
                "UPDATE pool_reward2s SET spent_height = ? WHERE coin_id = ?",
                (spent_height, reward_id),
            )

    async def get_latest_plotnft(self, launcher_id: bytes32) -> PlotNFT:
        async with self.db_wrapper.reader() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT *
                FROM plotnft2s
                WHERE launcher_id=?
                ORDER BY created_height DESC
                LIMIT 1;
                """,
                (launcher_id,),
            )
            return _row_to_plotnft(next(iter(rows)), self.genesis_challenge)

    async def get_latest_remark(self, launcher_id: bytes32) -> str:
        async with self.db_wrapper.reader() as conn:
            rows = await conn.execute_fetchall(
                """
                SELECT remark
                FROM plotnft2s
                WHERE launcher_id=?
                AND remark IS NOT NULL
                ORDER BY created_height DESC
                LIMIT 1;
                """,
                (launcher_id,),
            )
            return str(next(iter(rows))[0])

    async def get_plotnfts(self, *, coin_ids: list[bytes32]) -> list[PlotNFT]:
        if coin_ids == []:
            return []
        async with self.db_wrapper.reader() as conn:
            rows = await conn.execute_fetchall(
                f"SELECT * from plotnft2s where coin_id in ({', '.join(['?'] * len(coin_ids))})", coin_ids
            )
            plot_nfts_selected = [_row_to_plotnft(row, self.genesis_challenge) for row in rows]
            if len(plot_nfts_selected) != len(coin_ids):
                symmetric_difference = set(bytes32(row[0]) for row in rows) ^ set(coin_ids)
                raise ValueError(f"coin IDs {symmetric_difference} not found in PlotNFTStore")
            else:
                return plot_nfts_selected

    async def get_pool_rewards(
        self,
        *,
        plotnft_id: bytes32,
        coin_ids: list[bytes32] | None = None,
        max: int = DEFAULT_POOL_REWARDS_PER_CLAIM,
        include_spent: bool = False,
    ) -> list[PoolReward]:
        if coin_ids == []:
            return []
        async with self.db_wrapper.reader() as conn:
            rows = await conn.execute_fetchall(
                (
                    "SELECT * from pool_reward2s WHERE singleton_id = ?"
                    + (f" AND coin_id in ({', '.join(['?'] * len(coin_ids))})" if coin_ids is not None else "")
                    + (" AND spent_height IS NULL" if not include_spent else "")
                    + " LIMIT ?"
                ),
                (plotnft_id, *coin_ids, max) if coin_ids is not None else (plotnft_id, max),
            )
            pool_rewards_selected = [
                PoolReward(
                    coin=Coin(
                        parent_coin_info=bytes32(row[1]), puzzle_hash=bytes32(row[2]), amount=uint64.from_bytes(row[3])
                    ),
                    singleton_id=bytes32(row[4]),
                    height=uint32(row[5]),
                )
                for row in rows
            ]
            if coin_ids is not None and len(pool_rewards_selected) != len(coin_ids):
                symmetric_difference = set(bytes32(row[0]) for row in rows) ^ set(coin_ids)
                raise ValueError(f"coin IDs {symmetric_difference} not found in PlotNFTStore")
            else:
                return pool_rewards_selected

    async def add_exiting_fee(self, *, wallet_id: uint32, fee: uint64) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                ("INSERT OR REPLACE INTO finish_exiting_fee (wallet_id, fee) VALUES (?, ?)"),
                (wallet_id, bytes(fee)),
            )

    async def get_exiting_fee(self, wallet_id: uint32) -> uint64 | None:
        async with self.db_wrapper.reader() as conn:
            rows = list(
                await conn.execute_fetchall(("SELECT fee FROM finish_exiting_fee WHERE wallet_id = ?"), (wallet_id,))
            )
            if len(rows) == 0:
                return None
            else:
                return uint64.from_bytes(rows[0][0])

    async def add_exiting_height(self, *, wallet_id: uint32, height: uint32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute(
                ("INSERT OR REPLACE INTO finish_exiting_height (wallet_id, height) VALUES (?, ?)"),
                (wallet_id, height),
            )

    async def get_exiting_height(self, wallet_id: uint32) -> uint32 | None:
        async with self.db_wrapper.reader() as conn:
            rows = list(
                await conn.execute_fetchall(
                    ("SELECT height FROM finish_exiting_height WHERE wallet_id = ?"), (wallet_id,)
                )
            )
            if len(rows) == 0:
                return None
            else:
                return uint32(rows[0][0])

    async def clear_exiting_info(self, wallet_id: uint32) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("DELETE FROM finish_exiting_fee WHERE wallet_id = ?", (wallet_id,))
            await conn.execute("DELETE FROM finish_exiting_height WHERE wallet_id = ?", (wallet_id,))

    async def rollback_to_block(self, *, height: int) -> None:
        async with self.db_wrapper.writer_maybe_transaction() as conn:
            await conn.execute("DELETE FROM plotnft2s WHERE created_height > ?", (height,))
            await conn.execute("DELETE FROM pool_reward2s WHERE height > ?", (height,))
            await conn.execute("UPDATE pool_reward2s SET spent_height = NULL WHERE spent_height > ?", (height,))
