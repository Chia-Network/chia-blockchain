import asyncio
from multiprocessing import freeze_support
from pathlib import Path
from typing import Dict, Optional

from chia.consensus.constants import ConsensusConstants
from chia.full_node.full_node import FullNode
from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.SimulatorFullNodeRpcApi import SimulatorFullNodeRpcApi
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash
from chia.util.config import load_config_cli, override_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.keychain import Keychain
from chia.util.path import path_from_root
from tests.block_tools import BlockTools, test_constants

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "full_node"


def service_kwargs_for_full_node_simulator(root_path: Path, config: Dict, bt: BlockTools) -> Dict:
    path_from_root(root_path, config[SERVICE_NAME]["database_path"]).parent.mkdir(parents=True, exist_ok=True)
    constants = bt.constants

    node = FullNode(
        config=config[SERVICE_NAME],
        root_path=root_path,
        consensus_constants=constants,
        name=SERVICE_NAME,
    )

    peer_api = FullNodeSimulator(node, bt, config)
    network_id = config[SERVICE_NAME]["selected_network"]
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


def create_block_tools_simulator(
    constants: ConsensusConstants = test_constants,
    root_path: Optional[Path] = None,
    const_dict: Optional[Dict] = None,
    keychain: Optional[Keychain] = None,
    config_overrides: Optional[Dict] = None,
    automated_testing: bool = True,
    fingerprint: Optional[int] = None,
    reward_ph: Optional[bytes32] = None,
    plot_dir: str = "test-plots",
    plots: Optional[int] = None,
    plot_size: int = 20,
) -> BlockTools:
    bt = BlockTools(
        constants,
        root_path,
        const_dict,
        keychain,
        config_overrides=config_overrides,
        automated_testing=automated_testing,
        plot_dir=plot_dir,
    )
    asyncio.run(bt.setup_keys(fingerprint=fingerprint, reward_ph=reward_ph))
    if plots is not None:
        asyncio.run(bt.setup_plots(num_og_plots=plots, num_pool_plots=0, num_non_keychain_plots=0, plot_size=plot_size))
    else:
        asyncio.run(bt.setup_plots())
    return bt


def main() -> None:
    # We always use a real keychain for the new simulator.
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml")
    fingerprint: Optional[int] = None
    farming_puzzle_hash: Optional[bytes32] = None
    plot_dir: str = "simulator-plots"
    plots = 3  # 3 plots should be enough
    plot_size = 19  # anything under k19 is a bit buggy
    if "simulator" in config:
        overrides = {}
        plot_dir = config["simulator"].get("plot_directory", "simulator-plots")
        if config["simulator"]["key_fingerprint"] is not None:
            fingerprint = int(config["simulator"]["key_fingerprint"])
        if config["simulator"]["farming_address"] is not None:
            farming_puzzle_hash = decode_puzzle_hash(config["simulator"]["farming_address"])
    else:  # old config format
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
        create_block_tools_simulator(
            test_constants,
            root_path=DEFAULT_ROOT_PATH,
            config_overrides=overrides,
            automated_testing=False,
            fingerprint=fingerprint,
            reward_ph=farming_puzzle_hash,
            plot_dir=plot_dir,
            plots=plots,
            plot_size=plot_size,
        ),
    )
    return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
