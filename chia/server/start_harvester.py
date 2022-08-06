import pathlib
import sys
from typing import Dict, Optional

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.rpc.harvester_rpc_api import HarvesterRpcApi
from chia.server.outbound_message import NodeType
from chia.server.start_service import RpcInfo, Service, async_run
from chia.types.peer_info import PeerInfo
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "harvester"


def create_harvester_service(
    root_path: pathlib.Path,
    config: Dict,
    consensus_constants: ConsensusConstants,
    connect_to_daemon: bool = True,
) -> Service:
    service_config = config[SERVICE_NAME]

    connect_peers = [PeerInfo(service_config["farmer_peer"]["host"], service_config["farmer_peer"]["port"])]
    overrides = service_config["network_overrides"]["constants"][service_config["selected_network"]]
    updated_constants = consensus_constants.replace_str_to_bytes(**overrides)

    harvester = Harvester(root_path, service_config, updated_constants)
    peer_api = HarvesterAPI(harvester)
    network_id = service_config["selected_network"]
    rpc_info: Optional[RpcInfo] = None
    if service_config["start_rpc_server"]:
        rpc_info = (HarvesterRpcApi, service_config["rpc_port"])
    return Service(
        root_path=root_path,
        config=config,
        node=harvester,
        peer_api=peer_api,
        node_type=NodeType.HARVESTER,
        advertised_port=service_config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[service_config["port"]],
        connect_peers=connect_peers,
        auth_connect_peers=True,
        network_id=network_id,
        rpc_info=rpc_info,
        connect_to_daemon=connect_to_daemon,
    )


async def async_main() -> int:
    # TODO: refactor to avoid the double load
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    service_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config[SERVICE_NAME] = service_config
    initialize_logging(
        service_name=SERVICE_NAME,
        logging_config=service_config["logging"],
        root_path=DEFAULT_ROOT_PATH,
    )
    service = create_harvester_service(DEFAULT_ROOT_PATH, config, DEFAULT_CONSTANTS)
    await service.setup_process_global_state()
    await service.run()

    return 0


def main() -> int:
    return async_run(async_main())


if __name__ == "__main__":
    sys.exit(main())
