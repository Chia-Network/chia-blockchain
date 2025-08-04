from __future__ import annotations

import logging
import pathlib
import sys
from multiprocessing import freeze_support
from typing import Any, Optional

from chia_rs import ConsensusConstants

from chia.apis import ApiProtocolRegistry
from chia.consensus.constants import replace_str_to_bytes
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.protocols.outbound_message import NodeType
from chia.seeder.crawler import Crawler
from chia.seeder.crawler_api import CrawlerAPI
from chia.seeder.crawler_rpc_api import CrawlerRpcApi
from chia.server.aliases import CrawlerService
from chia.server.signal_handlers import SignalHandlers
from chia.server.start_service import RpcInfo, Service, async_run
from chia.util.chia_logging import initialize_service_logging
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import resolve_root_path

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "seeder"
log = logging.getLogger(__name__)


def create_full_node_crawler_service(
    root_path: pathlib.Path,
    config: dict[str, Any],
    consensus_constants: ConsensusConstants,
    connect_to_daemon: bool = True,
    start_crawler_loop: bool = True,
) -> CrawlerService:
    service_config = config[SERVICE_NAME]
    crawler_config = service_config["crawler"]

    crawler = Crawler(
        service_config, root_path=root_path, constants=consensus_constants, start_crawler_loop=start_crawler_loop
    )
    api = CrawlerAPI(crawler)

    network_id = service_config["selected_network"]

    rpc_info: Optional[RpcInfo[CrawlerRpcApi]] = None
    if crawler_config.get("start_rpc_server", True):
        rpc_info = (CrawlerRpcApi, crawler_config.get("rpc_port", 8561))

    return Service(
        root_path=root_path,
        config=config,
        node=api.crawler,
        peer_api=api,
        node_type=NodeType.FULL_NODE,
        advertised_port=service_config["port"],
        service_name="full_node",
        upnp_ports=[],
        on_connect_callback=crawler.on_connect,
        network_id=network_id,
        rpc_info=rpc_info,
        connect_to_daemon=connect_to_daemon,
        class_for_type=ApiProtocolRegistry,
    )


async def async_main(root_path: pathlib.Path) -> int:
    # TODO: refactor to avoid the double load
    config = load_config(root_path, "config.yaml")
    service_config = load_config_cli(root_path, "config.yaml", SERVICE_NAME)
    config[SERVICE_NAME] = service_config
    overrides = service_config["network_overrides"]["constants"][service_config["selected_network"]]
    updated_constants = replace_str_to_bytes(DEFAULT_CONSTANTS, **overrides)
    initialize_service_logging(service_name=SERVICE_NAME, config=config, root_path=root_path)
    service = create_full_node_crawler_service(root_path, config, updated_constants)
    async with SignalHandlers.manage() as signal_handlers:
        await service.setup_process_global_state(signal_handlers=signal_handlers)
        await service.run()

    return 0


def main() -> int:
    freeze_support()
    root_path = resolve_root_path(override=None)

    return async_run(async_main(root_path=root_path))


if __name__ == "__main__":
    sys.exit(main())
