from __future__ import annotations

import os
import pathlib
import sys
from typing import Any, Optional

from chia.apis import ApiProtocolRegistry
from chia.introducer.introducer import Introducer
from chia.introducer.introducer_api import IntroducerAPI
from chia.server.outbound_message import NodeType
from chia.server.signal_handlers import SignalHandlers
from chia.server.start_service import Service, async_run
from chia.types.aliases import IntroducerService
from chia.util.chia_logging import initialize_service_logging
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import resolve_root_path
from chia.util.task_timing import maybe_manage_task_instrumentation

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "introducer"


def create_introducer_service(
    root_path: pathlib.Path,
    config: dict[str, Any],
    advertised_port: Optional[int] = None,
    connect_to_daemon: bool = True,
) -> IntroducerService:
    service_config = config[SERVICE_NAME]

    network_id = service_config["selected_network"]

    if advertised_port is None:
        advertised_port = service_config["port"]

    node = Introducer(service_config["max_peers_to_send"], service_config["recent_peer_threshold"])
    peer_api = IntroducerAPI(node)

    return Service(
        root_path=root_path,
        config=config,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.INTRODUCER,
        advertised_port=advertised_port,
        service_name=SERVICE_NAME,
        network_id=network_id,
        connect_to_daemon=connect_to_daemon,
        class_for_type=ApiProtocolRegistry,
    )


async def async_main(root_path: pathlib.Path) -> int:
    # TODO: refactor to avoid the double load
    config = load_config(root_path, "config.yaml")
    service_config = load_config_cli(root_path, "config.yaml", SERVICE_NAME)
    config[SERVICE_NAME] = service_config
    initialize_service_logging(service_name=SERVICE_NAME, config=config, root_path=root_path)

    service = create_introducer_service(root_path, config)
    async with SignalHandlers.manage() as signal_handlers:
        await service.setup_process_global_state(signal_handlers=signal_handlers)
        await service.run()

    return 0


def main() -> int:
    root_path = resolve_root_path(override=None)

    with maybe_manage_task_instrumentation(
        enable=os.environ.get(f"CHIA_INSTRUMENT_{SERVICE_NAME.upper()}") is not None
    ):
        return async_run(coro=async_main(root_path=root_path))


if __name__ == "__main__":
    sys.exit(main())
