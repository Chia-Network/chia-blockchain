from multiprocessing import freeze_support
from pathlib import Path
from typing import Dict

from src.full_node.full_node import FullNode
from src.rpc.full_node_rpc_api import FullNodeRpcApi
from src.server.outbound_message import NodeType
from src.server.start_service import run_service
from src.util.block_tools import BlockTools, test_constants
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.path import mkdir, path_from_root

from .full_node_simulator import FullNodeSimulator


# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "full_node"


def service_kwargs_for_full_node_simulator(
    root_path: Path,
    config: Dict,
    bt: BlockTools,
) -> Dict:
    mkdir(path_from_root(root_path, config["database_path"]).parent)
    overrides = config["network_overrides"][config["selected_network"]]
    consensus_constants = bt.constants
    updated_constants = consensus_constants.replace_str_to_bytes(**overrides)
    bt.constants = updated_constants

    node = FullNode(
        config,
        root_path=root_path,
        consensus_constants=updated_constants,
        name=SERVICE_NAME,
    )

    peer_api = FullNodeSimulator(node, bt)

    kwargs = dict(
        root_path=root_path,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.FULL_NODE,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
        on_connect_callback=node.on_connect,
        rpc_info=(FullNodeRpcApi, config["rpc_port"]),
        network_id=updated_constants.GENESIS_CHALLENGE,
    )
    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config["database_path"] = config["simulator_database_path"]
    config["peer_db_path"] = config["simulator_peer_db_path"]
    config["introducer_peer"]["host"] = "127.0.0.1"
    config["introducer_peer"]["port"] = 58555
    config["selected_network"] = "testnet0"
    kwargs = service_kwargs_for_full_node_simulator(
        DEFAULT_ROOT_PATH,
        config,
        BlockTools(test_constants),
    )
    return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
