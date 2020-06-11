import signal
import asyncio
import aiosqlite
import logging
import pathlib
import pkg_resources
from src.util.logging import initialize_logging
from src.util.config import load_config
from asyncio import Lock
from typing import List
from src.util.default_root import DEFAULT_ROOT_PATH
from src.server.server import ChiaServer
from src.server.outbound_message import Delivery, Message, NodeType, OutboundMessage
from src.protocols import introducer_protocol
from src.full_node.full_node import FullNode
from src.types.peer_info import PeerInfo
from src.util.setproctitle import setproctitle
from src.util.ints import uint16

log = logging.getLogger(__name__)


async def main():
    root_path = DEFAULT_ROOT_PATH
    setproctitle("chia_timelord_launcher")
    config = load_config(root_path, "config.yaml", "full_node")
    initialize_logging("Launcher %(name)-23s", config["logging"], root_path)

    msg = Message("request_peers", introducer_protocol.RequestPeers())
    o_msg = OutboundMessage(NodeType.INTRODUCER, msg, Delivery.BROADCAST)
    servers = []

    api = FullNode(config, root_path=root_path)

    print("starting")
    for i in range(1):
        server = ChiaServer(
            60000 + i, api, NodeType.FULL_NODE, 100000, "testnet", root_path, config
        )
        # api._set_server(server)
        print("start client")
        await server.start_client(PeerInfo("localhost", uint16(8445)), None)
        print("start push")
        for i in range(2000):
            print("pushing")
            server.push_message(o_msg)
        servers.append(server)

    await asyncio.sleep(20)
    # print("Starting to close")
    # for server in servers:
    #     server.close_all()
    # for server in servers:
    #     await server.await_closed()


asyncio.run(main())
