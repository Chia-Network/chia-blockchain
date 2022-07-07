import logging
import pathlib
from typing import Dict

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.timelord_rpc_api import TimelordRpcApi
from chia.server.outbound_message import NodeType
from chia.server.start_service import RpcInfo, Service, async_run
from chia.timelord.timelord import Timelord
from chia.timelord.timelord_api import TimelordAPI
from chia.types.peer_info import PeerInfo
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "timelord"


log = logging.getLogger(__name__)


def create_timelord_service(
    root_path: pathlib.Path,
    config: Dict,
    constants: ConsensusConstants,
    parse_cli_args: bool = True,
    connect_to_daemon: bool = True,
    service_name_prefix: str = "",
    running_new_process: bool = True,
) -> Service:

    connect_peers = [PeerInfo(config["full_node_peer"]["host"], config["full_node_peer"]["port"])]
    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    updated_constants = constants.replace_str_to_bytes(**overrides)

    node = Timelord(root_path, config, updated_constants)
    peer_api = TimelordAPI(node)
    network_id = config["selected_network"]

    rpc_info: RpcInfo = None
    if config.get("start_rpc_server", True):
        rpc_info = (TimelordRpcApi, config.get("rpc_port", 8557))

    return Service(
        root_path=root_path,
        peer_api=peer_api,
        node=node,
        node_type=NodeType.TIMELORD,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
        connect_peers=connect_peers,
        auth_connect_peers=False,
        network_id=network_id,
        rpc_info=rpc_info,
        parse_cli_args=parse_cli_args,
        connect_to_daemon=connect_to_daemon,
    )


async def main() -> None:
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    initialize_logging(
        service_name=SERVICE_NAME,
        logging_config=config["service_name"]["logging"],
        root_path=DEFAULT_ROOT_PATH,
    )
    service = create_timelord_service(DEFAULT_ROOT_PATH, config, DEFAULT_CONSTANTS)
    await service.setup_process_global_state()
    await service.run()


if __name__ == "__main__":
    async_run(main())
