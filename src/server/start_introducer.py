import pathlib

from typing import Dict

from src.consensus.constants import ConsensusConstants
from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.introducer import Introducer
from src.server.outbound_message import NodeType
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH

from src.server.start_service import run_service

# See: https://bugs.python.org/issue29288
u"".encode("idna")


def service_kwargs_for_introducer(
    root_path: pathlib.Path, constants: ConsensusConstants
) -> Dict:
    service_name = "introducer"
    config = load_config_cli(root_path, "config.yaml", service_name)
    introducer = Introducer(
        config["max_peers_to_send"], config["recent_peer_threshold"]
    )

    async def start_callback():
        await introducer._start()

    def stop_callback():
        introducer._close()

    async def await_closed_callback():
        await introducer._await_closed()

    kwargs = dict(
        root_path=root_path,
        api=introducer,
        node_type=NodeType.INTRODUCER,
        advertised_port=config["port"],
        service_name=service_name,
        server_listen_ports=[config["port"]],
        start_callback=start_callback,
        stop_callback=stop_callback,
        await_closed_callback=await_closed_callback,
    )
    return kwargs


def main():
    kwargs = service_kwargs_for_introducer(DEFAULT_ROOT_PATH, DEFAULT_CONSTANTS)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
