import pathlib

from typing import Dict

from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.timelord import Timelord
from src.server.outbound_message import NodeType
from src.types.peer_info import PeerInfo
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH

from src.server.start_service import run_service

# See: https://bugs.python.org/issue29288
u"".encode("idna")


def service_kwargs_for_timelord(
    root_path: pathlib.Path, discriminant_size_bits: int
) -> Dict:
    service_name = "timelord"
    config = load_config_cli(root_path, "config.yaml", service_name)

    connect_peers = [
        PeerInfo(config["full_node_peer"]["host"], config["full_node_peer"]["port"])
    ]

    api = Timelord(config, discriminant_size_bits)

    kwargs = dict(
        root_path=root_path,
        api=api,
        node_type=NodeType.TIMELORD,
        advertised_port=config["port"],
        service_name=service_name,
        server_listen_ports=[config["port"]],
        connect_peers=connect_peers,
        auth_connect_peers=False,
    )
    return kwargs


def main():
    kwargs = service_kwargs_for_timelord(
        DEFAULT_ROOT_PATH, DEFAULT_CONSTANTS.DISCRIMINANT_SIZE_BITS
    )
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
