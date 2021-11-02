import asyncio
import logging
import pathlib
import time
from multiprocessing import freeze_support
from typing import Dict, List

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.seeder.crawler import Crawler
from chia.seeder.crawler_api import CrawlerAPI
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.server.start_service import run_service
from chia.util.config import load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH

# Patch some methods on the upstream server with crawler-specific overrides.


async def incoming_connection(self, request):
    return


async def garbage_collect_connections_task(self) -> None:
    """
    Periodically checks for connections with no activity (have not sent us any data), and removes them,
    to allow room for other peers.
    """
    while True:
        # Modification for crawler.
        await asyncio.sleep(2)
        to_remove: List[WSChiaConnection] = []
        for connection in self.all_connections.values():
            if self._local_type == NodeType.FULL_NODE and connection.connection_type == NodeType.FULL_NODE:
                if time.time() - connection.creation_time > 5:
                    to_remove.append(connection)
        for connection in to_remove:
            self.log.info(f"Garbage collecting connection {connection.peer_host}, max time reached.")
            await connection.close()

        # Also garbage collect banned_peers dict
        to_remove_ban = []
        for peer_ip, ban_until_time in self.banned_peers.items():
            if time.time() > ban_until_time:
                to_remove_ban.append(peer_ip)
        for peer_ip in to_remove_ban:
            del self.banned_peers[peer_ip]


ChiaServer.incoming_connection = incoming_connection
ChiaServer.garbage_collect_connections_task = garbage_collect_connections_task


# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "full_node"
log = logging.getLogger(__name__)


def service_kwargs_for_full_node(
    root_path: pathlib.Path, config: Dict, consensus_constants: ConsensusConstants
) -> Dict:
    crawler = Crawler(
        config,
        root_path=root_path,
        consensus_constants=consensus_constants,
    )
    api = CrawlerAPI(crawler)

    network_id = config["selected_network"]
    kwargs = dict(
        root_path=root_path,
        node=api.crawler,
        peer_api=api,
        node_type=NodeType.FULL_NODE,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        upnp_ports=[],
        server_listen_ports=[config["port"]],
        on_connect_callback=crawler.on_connect,
        network_id=network_id,
    )

    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", "dns")
    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    updated_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
    kwargs = service_kwargs_for_full_node(DEFAULT_ROOT_PATH, config, updated_constants)
    return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
