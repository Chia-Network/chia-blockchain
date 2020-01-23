import asyncio
import signal

try:
    import uvloop
except ImportError:
    uvloop = None

from src.introducer import Introducer
from src.server.outbound_message import NodeType
from src.server.server import ChiaServer
from src.util.network import parse_host_port
from src.util.logging import initialize_logging
from setproctitle import setproctitle

initialize_logging("Introducer %(name)-21s")
setproctitle("chia_introducer")


async def main():
    introducer = Introducer()
    host, port = parse_host_port(introducer)
    server = ChiaServer(port, introducer, NodeType.INTRODUCER)
    introducer.set_server(server)
    _ = await server.start_server(host, None)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

    await server.await_closed()


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
