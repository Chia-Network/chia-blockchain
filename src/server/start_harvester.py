from src.harvester import Harvester
from src.server.outbound_message import NodeType
from src.types.peer_info import PeerInfo
from src.util.config import load_config, load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.rpc.harvester_rpc_server import start_harvester_rpc_server

from src.server.start_service import run_service

# See: https://bugs.python.org/issue29288
u''.encode('idna')


def service_kwargs_for_harvester(root_path=DEFAULT_ROOT_PATH):
    service_name = "harvester"
    config = load_config_cli(root_path, "config.yaml", service_name)

    try:
        plot_config = load_config(root_path, "plots.yaml")
    except FileNotFoundError:
        raise RuntimeError("Plots not generated. Run chia-create-plots")

    connect_peers = [
        PeerInfo(config["farmer_peer"]["host"], config["farmer_peer"]["port"])
    ]

    api = Harvester(config, plot_config, root_path)

    kwargs = dict(
        root_path=root_path,
        api=api,
        node_type=NodeType.HARVESTER,
        advertised_port=config["port"],
        service_name=service_name,
        server_listen_ports=[config["port"]],
        connect_peers=connect_peers,
        rpc_start_callback_port=(start_harvester_rpc_server, config["rpc_port"]),
    )
    return kwargs


def main():
    kwargs = service_kwargs_for_harvester()
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
