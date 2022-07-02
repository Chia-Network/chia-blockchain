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
    full_config: Dict,
) -> Dict:
    config = full_config[SERVICE_NAME]

    introducer = Introducer(config["max_peers_to_send"], config["recent_peer_threshold"])
    node__api = IntroducerAPI(introducer)
    network_id = config["selected_network"]
    kwargs = dict(
        root_path=root_path,
        config=full_config,
        node=introducer,
        peer_api=node__api,
        node_type=NodeType.INTRODUCER,
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
        network_id=network_id,
    )
    return kwargs


def main() -> None:
    # TODO: refactor to avoid the double load
    full_config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    full_config[SERVICE_NAME] = config
    kwargs = service_kwargs_for_introducer(DEFAULT_ROOT_PATH, full_config)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
