from __future__ import annotations

import asyncio
import itertools
import pathlib
import time

from chia.util.misc import SignalHandlers

# TODO: CAMPid 0945094189459712842390t591
IP = "127.0.0.1"
PORT = 8444
NUM_CLIENTS = 500


async def tcp_echo_client(task_counter: str, file) -> None:
    try:
        for loop_counter in itertools.count():
            label = f"{task_counter:5}-{loop_counter:5}"
            t1 = time.monotonic()
            writer = None
            try:
                print(f"Opening connection: {label}", file=file)
                reader, writer = await asyncio.open_connection(IP, PORT)
                print(f"Opened connection: {label}", file=file)
                assert writer is not None
                await asyncio.sleep(15)
            except asyncio.CancelledError as e:
                t2 = time.monotonic()
                print(f"Cancelled connection {label}: {e}. Time: {t2 - t1:.3f}", file=file)
                break
            except Exception as e:
                t2 = time.monotonic()
                print(f"Closed connection {label}: {e}. Time: {t2 - t1:.3f}", file=file)
            finally:
                print(f"--- {label} a", file=file)
                if writer is not None:
                    print(f"--- {label}   B", file=file)
                    writer.close()
                    await writer.wait_closed()
    finally:
        print(f"--- {task_counter:5} task finishing", file=file)


async def main() -> None:
    # def dun(*args: object, **kwargs: object) -> None:
    #     task.cancel()

    async with SignalHandlers.manage() as signal_handlers:
        # signal_handlers.setup_sync_signal_handler(handler=dun)

        path = pathlib.Path.cwd().joinpath("flood")
        out_path = path.with_suffix(".out")

        async def dun():
            while path.exists():
                await asyncio.sleep(0.25)

            task.cancel()

        file_task = asyncio.create_task(dun())

        with out_path.open(mode="w") as file:

            async def f() -> None:
                await asyncio.gather(
                    *[tcp_echo_client(task_counter="{}".format(i), file=file) for i in range(0, NUM_CLIENTS)]
                )

            task = asyncio.create_task(f())
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                print("leaving flood", file=file)
                await file_task


from chia.server.chia_policy import ChiaPolicy

asyncio.set_event_loop_policy(ChiaPolicy())
asyncio.run(main())
