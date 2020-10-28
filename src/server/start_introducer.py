import pathlib

from typing import Dict

from src.introducer import Introducer
from src.server.outbound_message import NodeType
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH

from src.server.start_service import run_service

# See: https://bugs.python.org/issue29288
u"".encode("idna")

SERVICE_NAME = "introducer"


def service_kwargs_for_introducer(
    root_path: pathlib.Path,
    config: Dict,
) -> Dict:
    api = Introducer(config["max_peers_to_send"], config["recent_peer_threshold"])

    kwargs = dict(
        root_path=root_path,
        api=api,
        node_type=NodeType.INTRODUCER,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
    )
    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    kwargs = service_kwargs_for_introducer(DEFAULT_ROOT_PATH, config)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
