import pathlib

from multiprocessing import freeze_support
from typing import Dict

from src.consensus.constants import ConsensusConstants
from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.full_node.full_node import FullNode
from src.full_node.full_node_api import FullNodeAPI
from src.rpc.full_node_rpc_api import FullNodeRpcApi
from src.server.outbound_message import NodeType
from src.server.start_service import run_service
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH


# See: https://bugs.python.org/issue29288
u"".encode("idna")

SERVICE_NAME = "full_node"


def service_kwargs_for_full_node(
    root_path: pathlib.Path, config: Dict, consensus_constants: ConsensusConstants
) -> Dict:
    config = load_config_cli(root_path, "config.yaml", SERVICE_NAME)

    full_node = FullNode(config, root_path=root_path, consensus_constants=consensus_constants)
    api = FullNodeAPI(full_node)

    async def start_callback():
        if config["enable_upnp"]:
            upnp_remap_port(config["port"])
        await full_node._start()

    def stop_callback():
        full_node._close()

    async def await_closed_callback():
        await full_node._await_closed()

    upnp_list = []
    if config["enable_upnp"]:
        upnp_list = [config["port"]]

    kwargs = dict(
        root_path=root_path,
        node=api.full_node,
        peer_api=api,
        node_type=NodeType.FULL_NODE,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        upnp_ports=upnp_list,
        server_listen_ports=[config["port"]],
        on_connect_callback=full_node._on_connect,
        start_callback=start_callback,
        stop_callback=stop_callback,
        await_closed_callback=await_closed_callback,
    )
    if config["start_rpc_server"]:
        kwargs["rpc_info"] = (FullNodeRpcApi, config["rpc_port"])
    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    kwargs = service_kwargs_for_full_node(DEFAULT_ROOT_PATH, config, DEFAULT_CONSTANTS)
    return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
