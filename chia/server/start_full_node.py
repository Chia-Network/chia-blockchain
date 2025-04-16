from __future__ import annotations

import os
import pathlib
import sys
from multiprocessing import freeze_support
from typing import Any, Optional

from chia_rs import ConsensusConstants
from chia_rs.sized_ints import uint16

from chia.apis import ApiProtocolRegistry
from chia.consensus.constants import replace_str_to_bytes
from chia.consensus.default_constants import DEFAULT_CONSTANTS, update_testnet_overrides
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.rpc.full_node_rpc_api import FullNodeRpcApi
from chia.server.outbound_message import NodeType
from chia.server.signal_handlers import SignalHandlers
from chia.server.start_service import RpcInfo, Service, async_run
from chia.types.aliases import FullNodeService
from chia.util.chia_logging import initialize_service_logging
from chia.util.config import get_unresolved_peer_infos, load_config, load_config_cli
from chia.util.default_root import resolve_root_path
from chia.util.task_timing import maybe_manage_task_instrumentation

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "full_node"


async def create_full_node_service(
    root_path: pathlib.Path,
    config: dict[str, Any],
    consensus_constants: ConsensusConstants,
    connect_to_daemon: bool = True,
    override_capabilities: Optional[list[tuple[uint16, str]]] = None,
) -> FullNodeService:
    service_config = config[SERVICE_NAME]

    network_id = service_config["selected_network"]
    upnp_list = []
    if service_config["enable_upnp"]:
        upnp_list = [service_config["port"]]

    node = await FullNode.create(
        service_config,
        root_path=root_path,
        consensus_constants=consensus_constants,
    )
    peer_api = FullNodeAPI(node)

    rpc_info: Optional[RpcInfo[FullNodeRpcApi]] = None
    if service_config.get("start_rpc_server", True):
        rpc_info = (FullNodeRpcApi, service_config["rpc_port"])

    return Service(
        root_path=root_path,
        config=config,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.FULL_NODE,
        advertised_port=service_config["port"],
        service_name=SERVICE_NAME,
        upnp_ports=upnp_list,
        connect_peers=get_unresolved_peer_infos(service_config, NodeType.FULL_NODE),
        on_connect_callback=node.on_connect,
        network_id=network_id,
        rpc_info=rpc_info,
        connect_to_daemon=connect_to_daemon,
        override_capabilities=override_capabilities,
        class_for_type=ApiProtocolRegistry,
    )


async def async_main(service_config: dict[str, Any], root_path: pathlib.Path) -> int:
    # TODO: refactor to avoid the double load
    config = load_config(root_path, "config.yaml")
    config[SERVICE_NAME] = service_config
    network_id = service_config["selected_network"]
    overrides = service_config["network_overrides"]["constants"][network_id]
    update_testnet_overrides(network_id, overrides)
    updated_constants = replace_str_to_bytes(DEFAULT_CONSTANTS, **overrides)
    initialize_service_logging(service_name=SERVICE_NAME, config=config, root_path=root_path)

    service = await create_full_node_service(root_path, config, updated_constants)
    async with SignalHandlers.manage() as signal_handlers:
        await service.setup_process_global_state(signal_handlers=signal_handlers)
        await service.run()

    return 0


def main() -> int:
    freeze_support()
    root_path = resolve_root_path(override=None)

    with maybe_manage_task_instrumentation(
        enable=os.environ.get(f"CHIA_INSTRUMENT_{SERVICE_NAME.upper()}") is not None
    ):
        service_config = load_config_cli(root_path, "config.yaml", SERVICE_NAME)
        target_peer_count = service_config.get("target_peer_count", 40) - service_config.get(
            "target_outbound_peer_count", 8
        )
        if target_peer_count < 0:
            target_peer_count = None
        if not service_config.get("use_chia_loop_policy", True):
            target_peer_count = None
        return async_run(coro=async_main(service_config, root_path=root_path), connection_limit=target_peer_count)


if __name__ == "__main__":
    sys.exit(main())
