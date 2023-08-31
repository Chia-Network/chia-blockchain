from __future__ import annotations

import asyncio
import functools
import signal
import sys
import time

# TODO: CAMPid 0945094189459712842390t591
IP = "127.0.0.1"
PORT = 8444
NUM_CLIENTS = 5000


async def tcp_echo_client(counter: str) -> None:
    while True:
        t1 = time.monotonic()
        writer = None
        try:
            print(f"Opened connection: {counter}")
            reader, writer = await asyncio.open_connection(IP, PORT)
            await asyncio.sleep(15)
            # writer.close()
            # await writer.wait_closed()
        except Exception as e:
            t2 = time.monotonic()
            print(f"Closed connection {counter}: {e}. Time: {t2 - t1}")
            pass
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()


async def main() -> None:
    current_task = asyncio.current_task()
    assert current_task is not None, "we are in an async function, there should be a current task"

    def dun(*args: object, **kwargs: object) -> None:
        current_task.cancel()

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
    await asyncio.gather(*[tcp_echo_client("{}".format(i)) for i in range(0, NUM_CLIENTS)])


asyncio.run(main())
