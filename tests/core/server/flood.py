from __future__ import annotations

import asyncio
import functools
import itertools
import signal
import sys
import time

# TODO: CAMPid 0945094189459712842390t591
IP = "127.0.0.1"
PORT = 8444
NUM_CLIENTS = 5000


async def tcp_echo_client(task_counter: str) -> None:
    try:
        for loop_counter in itertools.count():
            label = f"{task_counter:5}-{loop_counter:5}"
            t1 = time.monotonic()
            writer = None
            try:
                print(f"Opening connection: {label}")
                reader, writer = await asyncio.shield(asyncio.create_task(asyncio.open_connection(IP, PORT)))
                print(f"Opened connection: {label}")
                assert writer is not None
                await asyncio.sleep(15)
            except asyncio.CancelledError as e:
                t2 = time.monotonic()
                print(f"Cancelled connection {label}: {e}. Time: {t2 - t1}")
                break
            except Exception as e:
                t2 = time.monotonic()
                print(f"Closed connection {label}: {e}. Time: {t2 - t1}")
            finally:
                print(f"--- {label} a")
                if writer is not None:
                    print(f"--- {label}   B")
                    writer.close()
                    await writer.wait_closed()
    finally:
        print(f"--- {task_counter:5} task finishing")


async def main() -> None:
    def dun(*args: object, **kwargs: object) -> None:
        task.cancel()

    async def setup_process_global_state() -> None:
        # Being async forces this to be run from within an active event loop as is
        # needed for the signal handler setup.

        if sys.platform == "win32" or sys.platform == "cygwin":
            # pylint: disable=E1101
            signal.signal(signal.SIGBREAK, dun)
            signal.signal(signal.SIGINT, dun)
            signal.signal(signal.SIGTERM, dun)
        else:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(
                signal.SIGINT,
                functools.partial(dun, signal_number=signal.SIGINT),
            )
            loop.add_signal_handler(
                signal.SIGTERM,
                functools.partial(dun, signal_number=signal.SIGTERM),
            )

    await setup_process_global_state()

    async def f() -> None:
        await asyncio.gather(*[tcp_echo_client(task_counter="{}".format(i)) for i in range(0, NUM_CLIENTS)])

    task = asyncio.create_task(f())
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        print("leaving flood")


asyncio.run(main())
