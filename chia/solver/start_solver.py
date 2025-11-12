from __future__ import annotations

import os
import pathlib
import sys
from multiprocessing import freeze_support
from typing import Any, Optional

from chia_rs import ConsensusConstants
from chia_rs.sized_ints import uint16

from chia.apis import StubMetadataRegistry
from chia.consensus.constants import replace_str_to_bytes
from chia.consensus.default_constants import DEFAULT_CONSTANTS, update_testnet_overrides
from chia.protocols.outbound_message import NodeType
from chia.server.signal_handlers import SignalHandlers
from chia.server.start_service import Service, async_run
from chia.solver.solver import Solver
from chia.solver.solver_api import SolverAPI
from chia.solver.solver_rpc_api import SolverRpcApi
from chia.solver.solver_service import SolverService
from chia.util.chia_logging import initialize_service_logging
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import resolve_root_path
from chia.util.task_timing import maybe_manage_task_instrumentation

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "solver"


def create_solver_service(
    root_path: pathlib.Path,
    config: dict[str, Any],
    consensus_constants: ConsensusConstants,
    connect_to_daemon: bool = True,
    override_capabilities: Optional[list[tuple[uint16, str]]] = None,
) -> SolverService:
    service_config = config[SERVICE_NAME]

    network_id = service_config["selected_network"]
    upnp_list = []
    if service_config["enable_upnp"]:
        upnp_list = [service_config["port"]]

    node = Solver(root_path, service_config, consensus_constants)
    peer_api = SolverAPI(node)
    network_id = service_config["selected_network"]

    rpc_info = None
    if service_config.get("start_rpc_server", True):
        rpc_info = (SolverRpcApi, service_config["rpc_port"])

    return Service(
        root_path=root_path,
        config=config,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.SOLVER,
        advertised_port=service_config["port"],
        service_name=SERVICE_NAME,
        upnp_ports=upnp_list,
        on_connect_callback=node.on_connect,
        network_id=network_id,
        rpc_info=rpc_info,
        connect_to_daemon=connect_to_daemon,
        override_capabilities=override_capabilities,
        stub_metadata_for_type=StubMetadataRegistry,
    )


async def async_main(service_config: dict[str, Any], root_path: pathlib.Path) -> int:
    config = load_config(root_path, "config.yaml", fill_missing_services=True)
    config[SERVICE_NAME] = service_config
    network_id = service_config["selected_network"]
    overrides = service_config["network_overrides"]["constants"][network_id]
    update_testnet_overrides(network_id, overrides)
    updated_constants = replace_str_to_bytes(DEFAULT_CONSTANTS, **overrides)
    initialize_service_logging(service_name=SERVICE_NAME, config=config, root_path=root_path)

    service = create_solver_service(root_path, config, updated_constants)
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
        return async_run(coro=async_main(service_config, root_path=root_path))


if __name__ == "__main__":
    sys.exit(main())
