import pathlib
from typing import Dict, Optional

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.farmer.farmer import Farmer
from chia.farmer.farmer_api import FarmerAPI
from chia.rpc.farmer_rpc_api import FarmerRpcApi
from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service
from chia.types.peer_info import PeerInfo
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.keychain import Keychain

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "farmer"


def service_kwargs_for_farmer(
    root_path: pathlib.Path,
    config: Dict,
    config_pool: Dict,
    consensus_constants: ConsensusConstants,
    keychain: Optional[Keychain] = None,
) -> Dict:
    service_config = config[SERVICE_NAME]

    connect_peers = []
    fnp = service_config.get("full_node_peer")
    if fnp is not None:
        connect_peers.append(PeerInfo(fnp["host"], fnp["port"]))

    overrides = service_config["network_overrides"]["constants"][service_config["selected_network"]]
    updated_constants = consensus_constants.replace_str_to_bytes(**overrides)

    farmer = Farmer(
        root_path, service_config, config_pool, consensus_constants=updated_constants, local_keychain=keychain
    )
    peer_api = FarmerAPI(farmer)
    network_id = service_config["selected_network"]
    kwargs = dict(
        root_path=root_path,
        config=config,
        node=farmer,
        peer_api=peer_api,
        node_type=NodeType.FARMER,
        advertised_port=service_config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[service_config["port"]],
        connect_peers=connect_peers,
        auth_connect_peers=False,
        on_connect_callback=farmer.on_connect,
        network_id=network_id,
    )
    if service_config["start_rpc_server"]:
        kwargs["rpc_info"] = (FarmerRpcApi, service_config["rpc_port"])
    return kwargs


def main() -> None:
    # TODO: refactor to avoid the double load
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    service_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config[SERVICE_NAME] = service_config
    config_pool = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", "pool")
    config["pool"] = config_pool
    kwargs = service_kwargs_for_farmer(DEFAULT_ROOT_PATH, config, config_pool, DEFAULT_CONSTANTS)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
