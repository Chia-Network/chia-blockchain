import pathlib

from multiprocessing import freeze_support
from typing import Dict

from src.consensus.constants import ConsensusConstants
from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.wallet.wallet_node import WalletNode
from src.rpc.wallet_rpc_api import WalletRpcApi
from src.server.outbound_message import NodeType
from src.server.start_service import run_service
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.keychain import Keychain
from src.simulator.simulator_constants import test_constants
from src.types.peer_info import PeerInfo

# See: https://bugs.python.org/issue29288
u"".encode("idna")


def service_kwargs_for_wallet(
    root_path: pathlib.Path, consensus_constants: ConsensusConstants
) -> Dict:
    service_name = "wallet"
    config = load_config_cli(root_path, "config.yaml", service_name)
    keychain = Keychain(testing=False)

    wallet_constants = consensus_constants
    if config["testing"] is True:
        config["database_path"] = "test_db_wallet.db"
        wallet_constants = test_constants

    api = WalletNode(config, keychain, root_path, consensus_constants=wallet_constants)

    if "full_node_peer" in config:
        connect_peers = [
            PeerInfo(config["full_node_peer"]["host"], config["full_node_peer"]["port"])
        ]
    else:
        connect_peers = []

    kwargs = dict(
        root_path=root_path,
        api=api,
        node_type=NodeType.WALLET,
        advertised_port=config["port"],
        service_name=service_name,
        server_listen_ports=[config["port"]],
        on_connect_callback=api._on_connect,
        rpc_info=(WalletRpcApi, config["rpc_port"]),
        connect_peers=connect_peers,
        auth_connect_peers=False,
    )
    return kwargs


def main():
    kwargs = service_kwargs_for_wallet(DEFAULT_ROOT_PATH, DEFAULT_CONSTANTS)
    return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
