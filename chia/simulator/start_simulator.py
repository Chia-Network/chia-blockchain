import logging
import sys
from multiprocessing import freeze_support
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from chia.full_node.full_node import FullNode
from chia.server.outbound_message import NodeType
from chia.server.start_service import Service, async_run
from chia.simulator.simulator_full_node_rpc_api import SimulatorFullNodeRpcApi
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config_cli, override_config, load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.simulator.block_tools import BlockTools, test_constants
from chia.util.ints import uint16
from chia.simulator.full_node_simulator import FullNodeSimulator

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "full_node"
log = logging.getLogger(__name__)
PLOTS = 3  # 3 plots should be enough
PLOT_SIZE = 19  # anything under k19 is a bit buggy


def create_full_node_simulator_service(
    root_path: Path,
    config: Dict,
    bt: BlockTools,
    connect_to_daemon: bool = True,
    override_capabilities: List[Tuple[uint16, str]] = None,
) -> Service[FullNode]:
    service_config = config[SERVICE_NAME]
    constants = bt.constants

    node = FullNode(
        config=service_config,
        root_path=root_path,
        consensus_constants=constants,
    )

    peer_api = FullNodeSimulator(node, bt, config)
    network_id = service_config["selected_network"]
    return Service(
        root_path=root_path,
        config=config,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.FULL_NODE,
        advertised_port=service_config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[service_config["port"]],
        on_connect_callback=node.on_connect,
        network_id=network_id,
        rpc_info=(SimulatorFullNodeRpcApi, service_config["rpc_port"]),
        connect_to_daemon=connect_to_daemon,
        override_capabilities=override_capabilities,
    )


async def async_main(test_mode: bool = False, automated_testing: bool = False, root_path: Path = DEFAULT_ROOT_PATH):
    # Same as full node, but the root_path is defined above
    config = load_config(root_path, "config.yaml")
    service_config = load_config_cli(root_path, "config.yaml", SERVICE_NAME)
    config[SERVICE_NAME] = service_config
    # THIS IS Simulator specific.
    fingerprint: Optional[int] = None
    farming_puzzle_hash: Optional[bytes32] = None
    plot_dir: str = "simulator/plots"
    if "simulator" in config:
        overrides = {}
        plot_dir = config["simulator"].get("plot_directory", "simulator/plots")
        if config["simulator"]["key_fingerprint"] is not None:
            fingerprint = int(config["simulator"]["key_fingerprint"])
        if config["simulator"]["farming_address"] is not None:
            farming_puzzle_hash = decode_puzzle_hash(config["simulator"]["farming_address"])
    else:  # old config format
        overrides = {
            "full_node.selected_network": "testnet0",
            "full_node.database_path": service_config["simulator_database_path"],
            "full_node.peers_file_path": service_config["simulator_peers_file_path"],
            "full_node.introducer_peer": {"host": "127.0.0.1", "port": 58555},
        }
    overrides["simulator.use_current_time"] = True

    # create block tools
    bt = BlockTools(
        test_constants,
        root_path,
        config_overrides=overrides,
        automated_testing=automated_testing,
        plot_dir=plot_dir,
    )
    await bt.setup_keys(fingerprint=fingerprint, reward_ph=farming_puzzle_hash)
    await bt.setup_plots(num_og_plots=PLOTS, num_pool_plots=0, num_non_keychain_plots=0, plot_size=PLOT_SIZE)
    # Everything after this is not simulator specific, excluding the if test_mode.
    initialize_logging(
        service_name=SERVICE_NAME,
        logging_config=service_config["logging"],
        root_path=root_path,
    )
    service = create_full_node_simulator_service(root_path, override_config(config, overrides), bt)
    if test_mode:
        return service
    await service.setup_process_global_state()
    await service.run()
    return 0


def main() -> int:
    freeze_support()
    return async_run(async_main())


if __name__ == "__main__":
    sys.exit(main())
