import logging

from src.full_node.full_node import FullNode
from src.rpc.full_node_rpc_server import start_full_node_rpc_server
from src.server.outbound_message import NodeType
from src.server.start_service import run_service
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.server.upnp import upnp_remap_port

from src.types.peer_info import PeerInfo


log = logging.getLogger(__name__)


def service_kwargs_for_full_node(root_path):
    service_name = "full_node"
    config = load_config_cli(root_path, "config.yaml", service_name)

    api = FullNode(config, root_path=root_path)

    introducer = config["introducer_peer"]
    peer_info = PeerInfo(introducer["host"], introducer["port"])

    async def start_callback():
        await api.start()
        if config["enable_upnp"]:
            upnp_remap_port(config["port"])

    def stop_callback():
        api._close()

    async def await_closed_callback():
        await api._await_closed()

    kwargs = dict(
        root_path=root_path,
        api=api,
        node_type=NodeType.FULL_NODE,
        advertised_port=config["port"],
        service_name=service_name,
        server_listen_ports=[config["port"]],
        on_connect_callback=api._on_connect,
        start_callback=start_callback,
        stop_callback=stop_callback,
        await_closed_callback=await_closed_callback,
        rpc_start_callback_port=(start_full_node_rpc_server, config["rpc_port"]),
        periodic_introducer_poll=(
            peer_info,
            config["introducer_connect_interval"],
            config["target_peer_count"],
        ),
    )
    return kwargs


def main():
    kwargs = service_kwargs_for_full_node(DEFAULT_ROOT_PATH)
    return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
