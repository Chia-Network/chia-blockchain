import pathlib

from typing import Dict

from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.introducer.introducer import Introducer
from src.introducer.introducer_api import IntroducerAPI
from src.server.outbound_message import NodeType
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
    overrides = config["network_overrides"][config["selected_network"]]
    updated_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
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
        network_id=updated_constants.GENESIS_CHALLENGE,
    )
    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    kwargs = service_kwargs_for_introducer(DEFAULT_ROOT_PATH, config)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
