import pathlib
from typing import Dict

from chia.introducer.introducer import Introducer
from chia.introducer.introducer_api import IntroducerAPI
from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "introducer"


def service_kwargs_for_introducer(
    root_path: pathlib.Path,
    config: Dict,
) -> Dict:
    service_config = config[SERVICE_NAME]

    introducer = Introducer(service_config["max_peers_to_send"], service_config["recent_peer_threshold"])
    node__api = IntroducerAPI(introducer)
    network_id = service_config["selected_network"]
    kwargs = dict(
        root_path=root_path,
        config=config,
        node=introducer,
        peer_api=node__api,
        node_type=NodeType.INTRODUCER,
        advertised_port=service_config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[service_config["port"]],
        network_id=network_id,
    )
    return kwargs


def main() -> None:
    # TODO: refactor to avoid the double load
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    service_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config[SERVICE_NAME] = service_config
    kwargs = service_kwargs_for_introducer(DEFAULT_ROOT_PATH, config)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
