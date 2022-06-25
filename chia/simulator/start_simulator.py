import sys
from pathlib import Path
from multiprocessing import freeze_support
from typing import Dict

from chia.full_node.full_node import FullNode
from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service
from chia.simulator.SimulatorFullNodeRpcApi import SimulatorFullNodeRpcApi
from chia.util.config import load_config_cli, override_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.path import path_from_root
from tests.block_tools import BlockTools, create_block_tools, test_constants
from tests.util.keyring import TempKeyring

from chia.simulator.full_node_simulator import FullNodeSimulator

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "full_node"


def service_kwargs_for_full_node_simulator(root_path: Path, config: Dict, bt: BlockTools) -> Dict:
    path_from_root(root_path, config[SERVICE_NAME]["database_path"]).parent.mkdir(parents=True, exist_ok=True)

    network_id = config[SERVICE_NAME]["selected_network"]
    overrides = config[SERVICE_NAME]["network_overrides"]["constants"][network_id]
    constants = bt.constants.replace_str_to_bytes(**overrides)

    node = FullNode(
        config=config[SERVICE_NAME],
        root_path=root_path,
        consensus_constants=constants,
        name=SERVICE_NAME,
    )

    peer_api = FullNodeSimulator(node, bt, config)
    kwargs = dict(
        root_path=root_path,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.FULL_NODE,
        advertised_port=config[SERVICE_NAME]["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config[SERVICE_NAME]["port"]],
        on_connect_callback=node.on_connect,
        rpc_info=(SimulatorFullNodeRpcApi, config[SERVICE_NAME]["rpc_port"]),
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
        config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml")
        if "simulator" in config:
            overrides = {
                "full_node.selected_network": config["simulator"]["selected_network"],
                "full_node.introducer_peer": {
                    "host": config["simulator"]["introducer_peer"]["host"],
                    "port": config["simulator"]["introducer_peer"]["port"],
                },
            }
        else:  # old config
            overrides = {
                "full_node.selected_network": "testnet0",
                "full_node.database_path": config[SERVICE_NAME]["simulator_database_path"],
                "full_node.peers_file_path": config[SERVICE_NAME]["simulator_peers_file_path"],
                "full_node.introducer_peer": {"host": "127.0.0.1", "port": 58555},
            }
        overrides["full_node.simulation"] = True
        kwargs = service_kwargs_for_full_node_simulator(
            DEFAULT_ROOT_PATH,
            override_config(config, overrides),
            create_block_tools(
                test_constants, root_path=DEFAULT_ROOT_PATH, keychain=keychain, config_overrides=overrides
            ),
        )
        return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
