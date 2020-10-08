import pathlib

from typing import Dict

from src.consensus.constants import ConsensusConstants
from src.consensus.default_constants import DEFAULT_CONSTANTS
from src.harvester import Harvester
from src.server.outbound_message import NodeType
from src.types.peer_info import PeerInfo
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.rpc.harvester_rpc_api import HarvesterRpcApi

from src.server.start_service import run_service

# See: https://bugs.python.org/issue29288
u"".encode("idna")


def service_kwargs_for_harvester(
    root_path: pathlib.Path, consensus_constants: ConsensusConstants
) -> Dict:
    service_name = "harvester"
    config = load_config_cli(root_path, "config.yaml", service_name)

    connect_peers = [
        PeerInfo(config["farmer_peer"]["host"], config["farmer_peer"]["port"])
    ]

    api = Harvester(root_path, consensus_constants)

    async def start_callback():
        await api._start()

    def stop_callback():
        api._close()

    async def await_closed_callback():
        await api._await_closed()

    kwargs = dict(
        root_path=root_path,
        api=api,
        node_type=NodeType.HARVESTER,
        advertised_port=config["port"],
        service_name=service_name,
        server_listen_ports=[config["port"]],
        connect_peers=connect_peers,
        auth_connect_peers=True,
        start_callback=start_callback,
        stop_callback=stop_callback,
        await_closed_callback=await_closed_callback,
    )
    if config["start_rpc_server"]:
        kwargs["rpc_info"] = (HarvesterRpcApi, config["rpc_port"])
    return kwargs


def main():
    kwargs = service_kwargs_for_harvester(DEFAULT_ROOT_PATH, DEFAULT_CONSTANTS)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
