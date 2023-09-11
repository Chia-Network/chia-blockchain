from __future__ import annotations

import asyncio
import asyncio.events
import asyncio.protocols
import dataclasses
import functools
import logging.config
import pathlib
import sys
import threading
from typing import List, Optional, final

from chia.server.chia_policy import ChiaPolicy
from chia.server.start_service import async_run
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
    path = pathlib.Path.cwd().joinpath("serve")
    out_path = path.with_suffix(".out")

    with out_path.open(mode="w") as file:
        logger = create_logger(file=file)
        if thread_end_event is None:
            thread_end_event = threading.Event()

        async def dun() -> None:
            while path.exists():
                await asyncio.sleep(0.25)

            thread_end_event.set()

        file_task = asyncio.create_task(dun())

        loop = asyncio.get_event_loop()
        server = await loop.create_server(functools.partial(EchoServer, logger=logger), ip, port)
        if port_holder is not None:
            [server_socket] = server.sockets
            # TODO: review if this is general enough, such as for ipv6
            port_holder.append(server_socket.getsockname()[1])
        logger.info("serving on {}".format(server.sockets[0].getsockname()))
        logger.handlers[0].flush()

        try:
            try:
                while not thread_end_event.is_set():
                    await asyncio.sleep(0.1)
            finally:
                # the test checks explicitly for this
                logger.info("exit: shutting down")
                logger.handlers[0].flush()
            logger.info("exit: thread end event set")
            logger.handlers[0].flush()
        except KeyboardInterrupt:
            logger.info("exit: keyboard interrupt")
            logger.handlers[0].flush()
        except asyncio.CancelledError:
            logger.info("exit: cancelled")
            logger.handlers[0].flush()
        finally:
            logger.info("closing server")
            logger.handlers[0].flush()
            server.close()
            await server.wait_closed()
            logger.info("server closed")
            logger.handlers[0].flush()
            # await asyncio.sleep(5)
            await file_task


def main(connection_limit: int = 25) -> None:
    asyncio.set_event_loop_policy(ChiaPolicy())
    async_run(async_main(), connection_limit=connection_limit - 100)


if __name__ == "__main__":
    main()
