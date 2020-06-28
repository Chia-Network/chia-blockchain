from src.consensus.constants import constants
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


def service_kwargs_for_farmer(root_path):
    service_name = "farmer"
    config = load_config_cli(root_path, "config.yaml", service_name)
    keychain = Keychain()

    connect_peers = [
        PeerInfo(config["full_node_peer"]["host"], config["full_node_peer"]["port"])
    ]

    # TOD: Remove once we have pool server
    config_pool = load_config_cli(root_path, "config.yaml", "pool")
    api = Farmer(config, config_pool, keychain, constants)

    kwargs = dict(
        root_path=root_path,
        api=api,
        node_type=NodeType.FARMER,
        advertised_port=config["port"],
        service_name=service_name,
        server_listen_ports=[config["port"]],
        connect_peers=connect_peers,
        auth_connect_peers=False,
        on_connect_callback=api._on_connect,
        rpc_info=(FarmerRpcApi, config["rpc_port"]),
    )
    return kwargs


def main():
    kwargs = service_kwargs_for_farmer(DEFAULT_ROOT_PATH)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
