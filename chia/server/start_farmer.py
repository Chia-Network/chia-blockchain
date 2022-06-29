import pathlib
from typing import Dict, Optional

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.rpc.farmer_rpc_api import FarmerRpcApi
from chia.server.outbound_message import NodeType
from chia.server.start_service import RpcInfo, Service, async_run
from chia.types.peer_info import PeerInfo
from chia.util.config import load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.keychain import Keychain

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "farmer"


def create_farmer_service(
    root_path: pathlib.Path,
    config: Dict,
    config_pool: Dict,
    consensus_constants: ConsensusConstants,
    keychain: Optional[Keychain] = None,
    parse_cli_args: bool = True,
    connect_to_daemon: bool = True,
    service_name_prefix: str = "",
    running_new_process: bool = True,
) -> Service:
    connect_peers = []
    fnp = config.get("full_node_peer")
    if fnp is not None:
        connect_peers.append(PeerInfo(fnp["host"], fnp["port"]))

    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    updated_constants = consensus_constants.replace_str_to_bytes(**overrides)

    farmer = Farmer(root_path, config, config_pool, consensus_constants=updated_constants, local_keychain=keychain)
    peer_api = FarmerAPI(farmer)
    network_id = config["selected_network"]
    rpc_info: RpcInfo = None
    if config["start_rpc_server"]:
        rpc_info = (FarmerRpcApi, config["rpc_port"])
    return Service(
        root_path=root_path,
        node=farmer,
        peer_api=peer_api,
        node_type=NodeType.FARMER,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
        connect_peers=connect_peers,
        auth_connect_peers=False,
        on_connect_callback=farmer.on_connect,
        network_id=network_id,
        rpc_info=rpc_info,
        parse_cli_args=parse_cli_args,
        connect_to_daemon=connect_to_daemon,
        service_name_prefix=service_name_prefix,
        running_new_process=running_new_process,
    )


def main() -> None:
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config_pool = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", "pool")
    service = create_farmer_service(DEFAULT_ROOT_PATH, config, config_pool, DEFAULT_CONSTANTS)
    return async_run(service.run())


if __name__ == "__main__":
    main()
