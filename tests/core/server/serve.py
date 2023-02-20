from __future__ import annotations

import asyncio
import asyncio.events
import asyncio.protocols
import logging.config
import sys
import threading
from typing import List, Optional

from chia.server.chia_policy import ChiaPolicy
from chia.server.start_service import async_run

if sys.platform == "win32":
    import _winapi

    NULL = _winapi.NULL


class EchoServer(asyncio.Protocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        peername = transport.get_extra_info("peername")
        print("connection from {}".format(peername))
        self.transport = transport

    def data_received(self, data: bytes) -> None:
        print(f"data received: {data.hex()}")
        # TODO: review this
        self.transport.write(data)  # type: ignore[attr-defined]
        # print("and sent back")

        # close the socket
        # self.transport.close()


async def async_main(
    ip: str = "127.0.0.1",
    port: int = 8444,
    thread_end_event: Optional[threading.Event] = None,
    port_holder: Optional[List[int]] = None,
) -> None:
    loop = asyncio.get_event_loop()
    server = await loop.create_server(EchoServer, ip, port)
    if port_holder is not None:
        [server_socket] = server.sockets
        # TODO: review if this is general enough, such as for ipv6
        port_holder.append(server_socket.getsockname()[1])
    print("serving on {}".format(server.sockets[0].getsockname()))

    try:
        if thread_end_event is None:
            await asyncio.sleep(20)
        else:
            while not thread_end_event.is_set():
                await asyncio.sleep(0.1)
    except KeyboardInterrupt:
        print("exit")
    finally:
        print("closing server")
        server.close()
        await server.wait_closed()
        print("server closed")
        # await asyncio.sleep(5)


def main(connection_limit: int = 25) -> None:
    asyncio.set_event_loop_policy(ChiaPolicy())
    logger = logging.getLogger()
    logger.setLevel(level=logging.DEBUG)
    stream_handler = logging.StreamHandler(stream=sys.stdout)
    logger.addHandler(hdlr=stream_handler)
    async_run(async_main(), connection_limit=connection_limit - 100)


if __name__ == "__main__":
    main()
