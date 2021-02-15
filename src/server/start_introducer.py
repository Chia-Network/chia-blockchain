import pathlib

from typing import Dict

from src.introducer.introducer import Introducer
from src.introducer.introducer_api import IntroducerAPI
from src.server.outbound_message import NodeType
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH

from src.server.start_service import run_service

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "introducer"


def service_kwargs_for_introducer(
    root_path: pathlib.Path,
    config: Dict,
) -> Dict:
    genesis_challenge = bytes32(bytes.fromhex(config["network_genesis_challenges"][config["selected_network"]]))
    introducer = Introducer(config["max_peers_to_send"], config["recent_peer_threshold"])
    node__api = IntroducerAPI(introducer)

    kwargs = dict(
        root_path=root_path,
        node=introducer,
        peer_api=node__api,
        node_type=NodeType.INTRODUCER,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
        network_id=genesis_challenge,
    )
    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    kwargs = service_kwargs_for_introducer(DEFAULT_ROOT_PATH, config)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
