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

SERVICE_NAME = "timelord"


def service_kwargs_for_timelord(
    root_path: pathlib.Path, config: Dict, discriminant_size_bits: int
) -> Dict:

    connect_peers = [
        PeerInfo(config["full_node_peer"]["host"], config["full_node_peer"]["port"])
    ]

    api = Timelord(config, discriminant_size_bits)

    kwargs = dict(
        root_path=root_path,
        api=api,
        node_type=NodeType.TIMELORD,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
        connect_peers=connect_peers,
        auth_connect_peers=False,
    )
    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    kwargs = service_kwargs_for_timelord(
        DEFAULT_ROOT_PATH, config, DEFAULT_CONSTANTS.DISCRIMINANT_SIZE_BITS
    )
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
