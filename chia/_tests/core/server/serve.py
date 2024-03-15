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
from typing import List, Optional, final, overload

from chia._tests.util.misc import create_logger
from chia.server.chia_policy import ChiaPolicy
from chia.server.start_service import async_run

if sys.platform == "win32":
    import _winapi

    NULL = _winapi.NULL


@final
@dataclasses.dataclass
class EchoServer(asyncio.Protocol):
    logger: logging.Logger

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        peername = transport.get_extra_info("peername")
        self.logger.info(f"connection from {peername}")
        self.transport = transport

    def data_received(self, data: bytes) -> None:
        print(f"data received: {data.hex()}")
        # TODO: review this
        self.transport.write(data)  # type: ignore[attr-defined]
        # print("and sent back")

        # close the socket
        # self.transport.close()


@overload
async def async_main(
    *,
    out_path: pathlib.Path,
    shutdown_path: pathlib.Path,
    ip: str = "127.0.0.1",
    port: int = 8444,
    port_holder: Optional[List[int]] = None,
) -> None: ...


@overload
async def async_main(
    *,
    out_path: pathlib.Path,
    thread_end_event: threading.Event,
    ip: str = "127.0.0.1",
    port: int = 8444,
    port_holder: Optional[List[int]] = None,
) -> None: ...


async def async_main(
    *,
    out_path: pathlib.Path,
    shutdown_path: Optional[pathlib.Path] = None,
    thread_end_event: Optional[threading.Event] = None,
    ip: str = "127.0.0.1",
    port: int = 8444,
    port_holder: Optional[List[int]] = None,
) -> None:
    with out_path.open(mode="w") as file:
        logger = create_logger(file=file)
        file_task: Optional[asyncio.Task[None]] = None
        if thread_end_event is None:
            assert shutdown_path is not None
            thread_end_event = threading.Event()

            async def dun() -> None:
                while shutdown_path.exists():
                    await asyncio.sleep(0.25)

                thread_end_event.set()

            file_task = asyncio.create_task(dun())

        loop = asyncio.get_event_loop()
        server = await loop.create_server(functools.partial(EchoServer, logger=logger), ip, port)
        if port_holder is not None:
            [server_socket] = server.sockets
            # TODO: review if this is general enough, such as for ipv6
            port_holder.append(server_socket.getsockname()[1])
        logger.info(f"serving on {server.sockets[0].getsockname()}")

        try:
            try:
                while not thread_end_event.is_set():
                    await asyncio.sleep(0.1)
            finally:
                # the test checks explicitly for this
                logger.info("exit: shutting down")
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
            if file_task is not None:
                await file_task


def main(connection_limit: int = 25) -> None:
    asyncio.set_event_loop_policy(ChiaPolicy())
    shutdown_path = pathlib.Path(sys.argv[1])
    async_run(
        async_main(
            shutdown_path=shutdown_path,
            out_path=shutdown_path.with_suffix(".out"),
        ),
        connection_limit=connection_limit - 100,
    )


if __name__ == "__main__":
    main()
