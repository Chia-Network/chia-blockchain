import asyncio
import signal
from typing import List

try:
    import uvloop
except ImportError:
    uvloop = None

from blspy import PrivateKey

from src.farmer import Farmer
from src.protocols.harvester_protocol import HarvesterHandshake
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.server.server import ChiaServer
from src.types.peer_info import PeerInfo
from src.util.network import parse_host_port
from src.util.logging import initialize_logging
from setproctitle import setproctitle

initialize_logging("Farmer %(name)-25s")
setproctitle("chia_farmer")


async def main():
    farmer = Farmer()
    harvester_peer = PeerInfo(
        farmer.config["harvester_peer"]["host"], farmer.config["harvester_peer"]["port"]
    )
    full_node_peer = PeerInfo(
        farmer.config["full_node_peer"]["host"], farmer.config["full_node_peer"]["port"]
    )
    host, port = parse_host_port(farmer)
    server = ChiaServer(port, farmer, NodeType.FARMER)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

    async def on_connect():
        # Sends a handshake to the harvester
        pool_sks: List[PrivateKey] = [
            PrivateKey.from_bytes(bytes.fromhex(ce))
            for ce in farmer.key_config["pool_sks"]
        ]
        msg = HarvesterHandshake([sk.get_public_key() for sk in pool_sks])
        yield OutboundMessage(
            NodeType.HARVESTER, Message("harvester_handshake", msg), Delivery.BROADCAST
        )

    _ = await server.start_server(host, on_connect)
    await asyncio.sleep(1)  # Prevents TCP simultaneous connect with harvester
    _ = await server.start_client(harvester_peer, None)
    _ = await server.start_client(full_node_peer, None)

    await server.await_closed()


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
