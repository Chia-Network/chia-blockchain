from __future__ import annotations

import asyncio
import asyncio.events
import asyncio.protocols
import dataclasses
import functools
import logging.config
import sys
import threading
from typing import List, Optional, final

from chia.server.chia_policy import ChiaPolicy
from chia.server.start_service import async_run
from chia.util.misc import SignalHandlers
from tests.util.misc import create_logger

if sys.platform == "win32":
    import _winapi

    NULL = _winapi.NULL


@final
@dataclasses.dataclass
class EchoServer(asyncio.Protocol):
    logger: logging.Logger

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        peername = transport.get_extra_info("peername")
        self.logger.info("connection from {}".format(peername))
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
    logger = create_logger()

    async with SignalHandlers.manage() as signal_handlers:
        if thread_end_event is None:
            thread_end_event = threading.Event()

        def dun(*args: object, **kwargs: object) -> None:
            thread_end_event.set()

        signal_handlers.setup_sync_signal_handler(handler=dun)

        loop = asyncio.get_event_loop()
        server = await loop.create_server(functools.partial(EchoServer, logger=logger), ip, port)
        if port_holder is not None:
            [server_socket] = server.sockets
            # TODO: review if this is general enough, such as for ipv6
            port_holder.append(server_socket.getsockname()[1])
        logger.info("serving on {}".format(server.sockets[0].getsockname()))

        try:
            while not thread_end_event.is_set():
                await asyncio.sleep(0.1)
            logger.info("exit: thread end event set")
        except KeyboardInterrupt:
            logger.info("exit: keyboard interrupt")
        except asyncio.CancelledError:
            logger.info("exit: cancelled")
        finally:
            logger.info("closing server")
            server.close()
            await server.wait_closed()
            logger.info("server closed")
            # await asyncio.sleep(5)


def main(connection_limit: int = 25) -> None:
    asyncio.set_event_loop_policy(ChiaPolicy())
    async_run(async_main(), connection_limit=connection_limit - 100)


if __name__ == "__main__":
    main()
