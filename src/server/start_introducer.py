import asyncio
import logging
import signal

from src.introducer import Introducer
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.util.network import parse_host_port

logging.basicConfig(
    format="Introducer %(name)-24s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)


async def main():
    introducer = Introducer()
    host, port = parse_host_port(introducer)
    server = ChiaServer(port, introducer, NodeType.INTRODUCER)
    introducer.set_server(server)
    _ = await server.start_server(host, None)

    def signal_received():
        server.close_all()

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, signal_received)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, signal_received)

    await server.await_closed()


asyncio.run(main())
