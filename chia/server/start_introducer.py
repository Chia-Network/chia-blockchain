import pathlib
from typing import Dict, Optional

from chia.introducer.introducer import Introducer
from chia.introducer.introducer_api import IntroducerAPI
from chia.server.outbound_message import NodeType
from chia.server.start_service import Service, async_run
from chia.util.config import load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "introducer"


def create_introducer_service(
    root_path: pathlib.Path,
    config: Dict,
    advertised_port: Optional[int] = None,
    parse_cli_args: bool = True,
    connect_to_daemon: bool = True,
    service_name_prefix: str = "",
    running_new_process: bool = True,
) -> Service:
    if advertised_port is None:
        advertised_port = config["port"]

    introducer = Introducer(config["max_peers_to_send"], config["recent_peer_threshold"])
    node__api = IntroducerAPI(introducer)
    network_id = config["selected_network"]
    return Service(
        root_path=root_path,
        node=introducer,
        peer_api=node__api,
        node_type=NodeType.INTRODUCER,
        service_name=SERVICE_NAME,
        server_listen_ports=[config["port"]],
        network_id=network_id,
        advertised_port=advertised_port,
        parse_cli_args=parse_cli_args,
        connect_to_daemon=connect_to_daemon,
        service_name_prefix=service_name_prefix,
        running_new_process=running_new_process,
    )


def main() -> None:
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    service = create_introducer_service(DEFAULT_ROOT_PATH, config)
    return async_run(service.run())


if __name__ == "__main__":
    main()
