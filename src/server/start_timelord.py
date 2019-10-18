import asyncio
import logging
from src.server.server import start_chia_server
from src.server.outbound_message import NodeType
from src.util.network import parse_host_port
from src import timelord

logging.basicConfig(format='Timelord %(name)-25s: %(levelname)-8s %(asctime)s.%(msecs)03d %(message)s',
                    level=logging.INFO,
                    datefmt='%H:%M:%S'
                    )


async def main():
    host, port = parse_host_port(timelord)
    server, _ = await start_chia_server(host, port, timelord, NodeType.FULL_NODE)
    await server

asyncio.run(main())
