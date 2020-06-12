from src.introducer import Introducer
from src.server.outbound_message import NodeType
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH

from src.server.start_service import run_service

# See: https://bugs.python.org/issue29288
u''.encode('idna')


def service_kwargs_for_introducer(root_path=DEFAULT_ROOT_PATH):
    service_name = "introducer"
    config = load_config_cli(root_path, "config.yaml", service_name)
    introducer = Introducer(
        config["max_peers_to_send"], config["recent_peer_threshold"]
    )

    kwargs = dict(
        root_path=root_path,
        api=introducer,
        node_type=NodeType.INTRODUCER,
        advertised_port=config["port"],
        service_name=service_name,
        server_listen_ports=[config["port"]],
    )
    return kwargs


def main():
    kwargs = service_kwargs_for_introducer()
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
