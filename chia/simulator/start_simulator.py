import sys
from pathlib import Path
from multiprocessing import freeze_support
from typing import Dict

from chia.full_node.full_node import FullNode
from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service
from chia.simulator.SimulatorFullNodeRpcApi import SimulatorFullNodeRpcApi
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.path import path_from_root
from tests.block_tools import BlockTools, create_block_tools, test_constants
from tests.util.keyring import TempKeyring

from chia.simulator.full_node_simulator import FullNodeSimulator

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "full_node"


def service_kwargs_for_full_node_simulator(root_path: Path, config: Dict, bt: BlockTools) -> Dict:
    service_config = config[SERVICE_NAME]

    path_from_root(root_path, service_config["database_path"]).parent.mkdir(parents=True, exist_ok=True)
    constants = bt.constants

    node = FullNode(
        service_config,
        root_path=root_path,
        consensus_constants=constants,
        name=SERVICE_NAME,
    )

    peer_api = FullNodeSimulator(node, bt)
    network_id = service_config["selected_network"]
    kwargs = dict(
        root_path=root_path,
        config=config,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.FULL_NODE,
        advertised_port=service_config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[service_config["port"]],
        on_connect_callback=node.on_connect,
        rpc_info=(SimulatorFullNodeRpcApi, service_config["rpc_port"]),
        network_id=network_id,
    )
    return kwargs


def main() -> None:
    # Use a temp keychain which will be deleted when it exits scope
    with TempKeyring() as keychain:
        # If launched with -D, we should connect to the keychain via the daemon instead
        # of using a local keychain
        if "-D" in sys.argv:
            keychain = None
            sys.argv.remove("-D")  # Remove -D to avoid conflicting with load_config_cli's argparse usage
        # TODO: refactor to avoid the double load
        config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
        service_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
        config[SERVICE_NAME] = service_config
        service_config["database_path"] = service_config["simulator_database_path"]
        service_config["peers_file_path"] = service_config["simulator_peers_file_path"]
        service_config["introducer_peer"]["host"] = "127.0.0.1"
        service_config["introducer_peer"]["port"] = 58555
        service_config["selected_network"] = "testnet0"
        service_config["simulation"] = True
        kwargs = service_kwargs_for_full_node_simulator(
            DEFAULT_ROOT_PATH,
            config,
            create_block_tools(test_constants, root_path=DEFAULT_ROOT_PATH, keychain=keychain),
        )
        return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
