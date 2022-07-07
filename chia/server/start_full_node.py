import logging
import pathlib
from multiprocessing import freeze_support
from typing import Dict, List, Tuple

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.server.outbound_message import NodeType
from chia.server.start_service import RpcInfo, Service, async_run
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "full_node"
log = logging.getLogger(__name__)


def create_full_node_service(
    root_path: pathlib.Path,
    config: Dict,
    consensus_constants: ConsensusConstants,
    parse_cli_args: bool = True,
    connect_to_daemon: bool = True,
    service_name_prefix: str = "",
    running_new_process: bool = True,
    override_capabilities: List[Tuple[uint16, str]] = None,
) -> Service:

    full_node = FullNode(
        config,
        root_path=root_path,
        consensus_constants=consensus_constants,
    )
    api = FullNodeAPI(full_node)

    upnp_list = []
    if config["enable_upnp"]:
        upnp_list = [config["port"]]
    network_id = config["selected_network"]
    rpc_info: RpcInfo = None
    if config["start_rpc_server"]:
        rpc_info = (FullNodeRpcApi, config["rpc_port"])
    return Service(
        root_path=root_path,
        node=api.full_node,
        peer_api=api,
        node_type=NodeType.FULL_NODE,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        upnp_ports=upnp_list,
        server_listen_ports=[config["port"]],
        on_connect_callback=full_node.on_connect,
        network_id=network_id,
        rpc_info=rpc_info,
        parse_cli_args=parse_cli_args,
        connect_to_daemon=connect_to_daemon,
        override_capabilities=override_capabilities,
    )


async def main() -> None:
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    updated_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
    initialize_logging(
        service_name=SERVICE_NAME,
        logging_config=config["service_name"]["logging"],
        root_path=DEFAULT_ROOT_PATH,
    )
    service = create_full_node_service(DEFAULT_ROOT_PATH, config, updated_constants)
    await service.setup_process_global_state()
    await service.run()


if __name__ == "__main__":
    freeze_support()
    async_run(main())
