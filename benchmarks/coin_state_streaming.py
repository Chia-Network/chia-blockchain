from __future__ import annotations

import asyncio
from time import monotonic

from benchmarks.utils import setup_db
from chia.full_node.coin_store import CoinStore
from chia.full_node.hint_store import HintStore
from chia.util.ints import uint32
from tests.core.full_node.stores.test_coin_store import generate_crs, generate_phs


async def run_benchmark(version: int) -> None:
    async with setup_db("state-streaming-benchmark.db", version) as db_wrapper:
        coin_store = await CoinStore.create(db_wrapper)
        await HintStore.create(db_wrapper)
        async with coin_store.db_wrapper.writer() as conn:
            await conn.execute("DELETE FROM coin_record")

        generation = monotonic()

        # The limit to the number of puzzle hashes you can subscribe to on an untrusted peer.
        phs = generate_phs(200000)

        # Generate a lot of coin records using those puzzle hashes.
        crs = generate_crs(
            phs,
            spent_per_ph_modulo=4,
            unspent_per_ph_modulo=2,
            duplicates_per_height=2,
            created_multiplier=1724,
            spent_multiplier=2109,
        )

        generation = monotonic() - generation
        print(f"Time to generate {len(crs)} coin records: {generation:0.4f}s")

        insertion = monotonic()

        await coin_store._add_coin_records(crs)

        insertion = monotonic() - insertion
        print(f"Time to insert {len(crs)} coin records: {insertion:0.4f}s")

        ph_set = set(phs)
        streaming = monotonic()
        batches = []

        async for (batch, _) in coin_store.stream_coin_states_by_puzzle_hashes(ph_set, uint32(0), True, True, True):
            batches.append(len(batch))

        streaming = monotonic() - streaming
        print(f"Time to stream {batches}: {streaming:0.4f}s")


if __name__ == "__main__":
    asyncio.run(run_benchmark(2))
