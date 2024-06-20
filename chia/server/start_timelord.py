from __future__ import annotations

import logging
import pathlib
import sys
from typing import Any, Dict, Optional

from chia.consensus.constants import ConsensusConstants, replace_str_to_bytes
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.timelord_rpc_api import TimelordRpcApi
from chia.server.outbound_message import NodeType
from chia.server.signal_handlers import SignalHandlers
from chia.server.start_service import RpcInfo, Service, async_run
from chia.timelord.timelord import Timelord
from chia.timelord.timelord_api import TimelordAPI
from chia.types.aliases import TimelordService
from chia.util.chia_logging import initialize_service_logging
from chia.util.config import get_unresolved_peer_infos, load_config, load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "timelord"


log = logging.getLogger(__name__)


def create_timelord_service(
    root_path: pathlib.Path,
    config: Dict[str, Any],
    constants: ConsensusConstants,
    connect_to_daemon: bool = True,
) -> TimelordService:
    service_config = config[SERVICE_NAME]
    overrides = service_config["network_overrides"]["constants"][service_config["selected_network"]]
    updated_constants = replace_str_to_bytes(constants, **overrides)

    node = Timelord(root_path, service_config, updated_constants)
    peer_api = TimelordAPI(node)
    network_id = service_config["selected_network"]

    rpc_info: Optional[RpcInfo[TimelordRpcApi]] = None
    if service_config.get("start_rpc_server", True):
        rpc_info = (TimelordRpcApi, service_config.get("rpc_port", 8557))

    return Service(
        root_path=root_path,
        config=config,
        peer_api=peer_api,
        node=node,
        node_type=NodeType.TIMELORD,
        advertised_port=None,
        service_name=SERVICE_NAME,
        connect_peers=get_unresolved_peer_infos(service_config, NodeType.FULL_NODE),
        network_id=network_id,
        rpc_info=rpc_info,
        connect_to_daemon=connect_to_daemon,
    )


async def async_main() -> int:
    # TODO: refactor to avoid the double load
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    service_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config[SERVICE_NAME] = service_config
    initialize_service_logging(service_name=SERVICE_NAME, config=config)
    service = create_timelord_service(DEFAULT_ROOT_PATH, config, DEFAULT_CONSTANTS)
    async with SignalHandlers.manage() as signal_handlers:
        await service.setup_process_global_state(signal_handlers=signal_handlers)
        await service.run()

    return 0


def main() -> int:
    return async_run(async_main())


if __name__ == "__main__":
    sys.exit(main())
