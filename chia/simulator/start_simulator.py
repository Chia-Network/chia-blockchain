import sys
from pathlib import Path
from multiprocessing import freeze_support
from typing import Dict, List, Tuple

from chia.full_node.full_node import FullNode
from chia.server.outbound_message import NodeType
from chia.server.start_service import Service, async_run
from chia.simulator.SimulatorFullNodeRpcApi import SimulatorFullNodeRpcApi
from chia.util.config import load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.path import path_from_root
from tests.block_tools import BlockTools, create_block_tools, test_constants
from chia.util.ints import uint16
from tests.util.keyring import TempKeyring
from chia.simulator.full_node_simulator import FullNodeSimulator

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "full_node"


def create_full_node_simulator_service(
    root_path: Path,
    config: Dict,
    bt: BlockTools,
    parse_cli_args: bool = True,
    connect_to_daemon: bool = True,
    service_name_prefix: str = "",
    running_new_process: bool = True,
    override_capabilities: List[Tuple[uint16, str]] = None,
) -> Service:
    path_from_root(root_path, config["database_path"]).parent.mkdir(parents=True, exist_ok=True)
    constants = bt.constants

    node = FullNode(
        config,
        root_path=root_path,
        consensus_constants=constants,
        name=SERVICE_NAME,
    )

    peer_api = FullNodeSimulator(node, bt)
    network_id = config["selected_network"]
    return Service(
        root_path=root_path,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.FULL_NODE,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
        on_connect_callback=node.on_connect,
        network_id=network_id,
        rpc_info=(SimulatorFullNodeRpcApi, config["rpc_port"]),
        parse_cli_args=parse_cli_args,
        connect_to_daemon=connect_to_daemon,
        service_name_prefix=service_name_prefix,
        running_new_process=running_new_process,
        override_capabilities=override_capabilities,
    )


def main() -> None:
    # Use a temp keychain which will be deleted when it exits scope
    with TempKeyring() as keychain:
        # If launched with -D, we should connect to the keychain via the daemon instead
        # of using a local keychain
        if "-D" in sys.argv:
            keychain = None
            sys.argv.remove("-D")  # Remove -D to avoid conflicting with load_config_cli's argparse usage
        config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
        config["database_path"] = config["simulator_database_path"]
        config["peers_file_path"] = config["simulator_peers_file_path"]
        config["introducer_peer"]["host"] = "127.0.0.1"
        config["introducer_peer"]["port"] = 58555
        config["selected_network"] = "testnet0"
        config["simulation"] = True
        service = create_full_node_simulator_service(
            DEFAULT_ROOT_PATH,
            config,
            create_block_tools(test_constants, root_path=DEFAULT_ROOT_PATH, keychain=keychain),
        )
        return async_run(service.run())


if __name__ == "__main__":
    freeze_support()
    main()
