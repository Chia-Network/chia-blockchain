from multiprocessing import freeze_support
from pathlib import Path
from typing import Dict

from src.consensus.constants import ConsensusConstants
from src.full_node.full_node import FullNode
from src.rpc.full_node_rpc_api import FullNodeRpcApi
from src.server.outbound_message import NodeType
from src.server.start_service import run_service
from src.util.block_tools import BlockTools
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.path import mkdir, path_from_root

from .full_node_simulator import FullNodeSimulator
from .simulator_constants import test_constants


# See: https://bugs.python.org/issue29288
u"".encode("idna")

SERVICE_NAME = "full_node"


def service_kwargs_for_full_node_simulator(
    root_path: Path,
    config: Dict,
    consensus_constants: ConsensusConstants,
    bt: BlockTools,
) -> Dict:
    mkdir(path_from_root(root_path, config["database_path"]).parent)

    node = FullNode(
        config,
        root_path=root_path,
        consensus_constants=consensus_constants,
        name=SERVICE_NAME,
    )

    peer_api = FullNodeSimulator(node, bt)

    async def start_callback():
        await node._start()

    def stop_callback():
        node._close()

    async def await_closed_callback():
        await node._await_closed()

    kwargs = dict(
        root_path=root_path,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.FULL_NODE,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
        on_connect_callback=node._on_connect,
        rpc_info=(FullNodeRpcApi, config["rpc_port"]),
    )
    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config["database_path"] = config["simulator_database_path"]
    kwargs = service_kwargs_for_full_node_simulator(
        DEFAULT_ROOT_PATH,
        config,
        test_constants,
        BlockTools(),
    )
    return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
