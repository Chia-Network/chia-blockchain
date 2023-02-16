from __future__ import annotations

import asyncio
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
    await asyncio.gather(*[tcp_echo_client("{}".format(i)) for i in range(0, NUM_CLIENTS)])


asyncio.run(main())
