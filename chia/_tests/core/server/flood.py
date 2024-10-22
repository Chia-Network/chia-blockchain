from __future__ import annotations

import asyncio
import itertools
import logging
import pathlib
import random
import sys
import time

from chia._tests.util.misc import create_logger

# TODO: CAMPid 0945094189459712842390t591
IP = "127.0.0.1"
PORT = 8444
NUM_CLIENTS = 500

total_open_connections = 0


async def tcp_echo_client(task_counter: str, logger: logging.Logger) -> None:
    global total_open_connections
    try:
        for loop_counter in itertools.count():
            label = f"{task_counter:5}-{loop_counter:5}"
            await asyncio.sleep(random.random())
            t1 = time.monotonic()
            writer = None
            try:
                logger.info(f"Opening connection: {label}")
                reader, writer = await asyncio.open_connection(IP, PORT)
                total_open_connections += 1
                logger.info(f"Opened connection: {label} (total: {total_open_connections})")
                assert writer is not None
                await asyncio.sleep(1 + 4 * random.random())
            except asyncio.CancelledError as e:
                t2 = time.monotonic()
                logger.info(f"Cancelled connection: {label} - {e}. Time: {t2 - t1:.3f}")
                break
            except Exception as e:
                t2 = time.monotonic()
                logger.info(f"Closed connection: {label} - {e}. Time: {t2 - t1:.3f}")
            finally:
                logger.info(f"--- {label} a")
                if writer is not None:
                    total_open_connections -= 1
                    logger.info(f"--- {label}   B (total: {total_open_connections})")
                    writer.close()
                    await writer.wait_closed()
    finally:
        logger.info(f"--- {task_counter:5} task finishing")


async def main() -> None:
    shutdown_path = pathlib.Path(sys.argv[1])
    out_path = shutdown_path.with_suffix(".out")

    async def dun() -> None:
        while shutdown_path.exists():
            await asyncio.sleep(0.25)

        task.cancel()

    file_task = asyncio.create_task(dun())

    with out_path.open(mode="w") as file:
        logger = create_logger(file=file)

        async def f() -> None:
            await asyncio.gather(*[tcp_echo_client(task_counter=f"{i}", logger=logger) for i in range(0, NUM_CLIENTS)])

        task = asyncio.create_task(f())
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("leaving flood")
            await file_task


asyncio.run(main())
