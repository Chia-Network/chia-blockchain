from __future__ import annotations

import asyncio
import cProfile
import time
from contextlib import contextmanager
from subprocess import check_call
from typing import Iterator

from chia._tests.util.blockchain import persistent_blocks
from chia.simulator.block_tools import create_block_tools_async, test_constants
from chia.simulator.keyring import TempKeyring
from chia.util.keyring_wrapper import KeyringWrapper


@contextmanager
def enable_profiler(profile: bool, name: str) -> Iterator[None]:
    if not profile:
        yield
        return

    with cProfile.Profile() as pr:
        yield

    pr.create_stats()
    output_file = f"{name}"
    pr.dump_stats(output_file + ".profile")
    check_call(["gprof2dot", "-f", "pstats", "-o", output_file + ".dot", output_file + ".profile"])
    with open(output_file + ".png", "w+") as f:
        check_call(["dot", "-T", "png", output_file + ".dot"], stdout=f)
    print(f"  output written to: {output_file}.png")


async def run_test_chain_benchmark() -> None:
    with TempKeyring() as keychain:
        bt = await create_block_tools_async(constants=test_constants, keychain=keychain)
        with enable_profiler(True, "load-test-chain"):
            start = time.monotonic()
            for version in ["", "_hardfork"]:
                for count, name in [
                    (400, "test_blocks_400_rc5"),
                    (1000, "test_blocks_1000_rc5"),
                    (1000, "pre_genesis_empty_slots_1000_blocksrc5"),
                    (1500, "test_blocks_1500_rc5"),
                    (10000, "test_blocks_10000_rc5"),
                    (758 + 320, "test_blocks_long_reorg_rc5"),
                    (2000, "test_blocks_2000_compact_rc5"),
                    (10000, "test_blocks_10000_compact_rc5"),
                ]:
                    persistent_blocks(count, f"{name}{version}.db", bt, seed=b"100")
            end = time.monotonic()
        KeyringWrapper.cleanup_shared_instance()

        print(f"time to load test chains: {end - start:.2f}s")


if __name__ == "__main__":
    import logging

    logger = logging.getLogger()
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.WARNING)

    asyncio.run(run_test_chain_benchmark())
