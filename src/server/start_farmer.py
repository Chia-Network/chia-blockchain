import asyncio
import signal
from typing import List
import logging

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
from src.util.logging import initialize_logging
from src.util.config import load_config, load_config_cli
from setproctitle import setproctitle


async def main():
    config = load_config_cli("config.yaml", "farmer")
    try:
        key_config = load_config("keys.yaml")
    except FileNotFoundError:
        raise RuntimeError(
            "Keys not generated. Run python3 ./scripts/regenerate_keys.py."
        )
    initialize_logging("Farmer %(name)-25s", config["logging"])
    log = logging.getLogger(__name__)
    setproctitle("chia_farmer")

    farmer = Farmer(config, key_config)

    harvester_peer = PeerInfo(
        config["harvester_peer"]["host"], config["harvester_peer"]["port"]
    )
    full_node_peer = PeerInfo(
        config["full_node_peer"]["host"], config["full_node_peer"]["port"]
    )
    server = ChiaServer(config["port"], farmer, NodeType.FARMER)

    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, server.close_all)
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, server.close_all)

    async def on_connect():
        # Sends a handshake to the harvester
        pool_sks: List[PrivateKey] = [
            PrivateKey.from_bytes(bytes.fromhex(ce)) for ce in key_config["pool_sks"]
        ]
        msg = HarvesterHandshake([sk.get_public_key() for sk in pool_sks])
        yield OutboundMessage(
            NodeType.HARVESTER, Message("harvester_handshake", msg), Delivery.BROADCAST
        )

    _ = await server.start_server(config["host"], on_connect)
    await asyncio.sleep(1)  # Prevents TCP simultaneous connect with harvester
    _ = await server.start_client(harvester_peer, None)
    _ = await server.start_client(full_node_peer, None)

    await server.await_closed()
    log.info("Farmer fully closed.")


if uvloop is not None:
    uvloop.install()
asyncio.run(main())
