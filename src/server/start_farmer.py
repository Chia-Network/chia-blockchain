import pathlib

from typing import Dict

from src.consensus.constants import ConsensusConstants
from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.farmer import Farmer
from src.server.outbound_message import NodeType
from src.types.peer_info import PeerInfo
from src.util.keychain import Keychain
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.rpc.farmer_rpc_api import FarmerRpcApi

from src.server.start_service import run_service

# See: https://bugs.python.org/issue29288
u"".encode("idna")

SERVICE_NAME = "farmer"


def service_kwargs_for_farmer(
    root_path: pathlib.Path,
    config: Dict,
    config_pool: Dict,
    keychain: Keychain,
    consensus_constants: ConsensusConstants,
) -> Dict:

    connect_peers = []
    fnp = config.get("full_node_peer")
    if fnp is not None:
        connect_peers.append(PeerInfo(fnp["host"], fnp["port"]))

    # TOD: Remove once we have pool server
    api = Farmer(config, config_pool, keychain, consensus_constants)

    kwargs = dict(
        root_path=root_path,
        api=api,
        node_type=NodeType.FARMER,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
        connect_peers=connect_peers,
        auth_connect_peers=False,
        on_connect_callback=api._on_connect,
    )
    if config["start_rpc_server"]:
        kwargs["rpc_info"] = (FarmerRpcApi, config["rpc_port"])
    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config_pool = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", "pool")
    keychain = Keychain()
    kwargs = service_kwargs_for_farmer(
        DEFAULT_ROOT_PATH, config, config_pool, keychain, DEFAULT_CONSTANTS
    )
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
