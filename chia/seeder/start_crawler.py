import logging
import pathlib
from multiprocessing import freeze_support
from typing import Dict

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.crawler_rpc_api import CrawlerRpcApi
from chia.seeder.crawler import Crawler
from chia.seeder.crawler_api import CrawlerAPI
from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service
from chia.util.config import load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "full_node"
log = logging.getLogger(__name__)


def service_kwargs_for_full_node_crawler(
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

    if config.get("crawler", {}).get("start_rpc_server", True):
        kwargs["rpc_info"] = (CrawlerRpcApi, config.get("crawler", {}).get("rpc_port", 8561))

    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", "seeder")
    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    updated_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
    kwargs = service_kwargs_for_full_node_crawler(DEFAULT_ROOT_PATH, config, updated_constants)
    return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
