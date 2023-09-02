from __future__ import annotations

import os
import pathlib
import sys
from multiprocessing import freeze_support
from typing import Any, Dict, Optional

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.server.outbound_message import NodeType
from chia.server.start_service import RpcInfo, Service, async_run
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.chia_logging import initialize_service_logging
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.keychain import Keychain
from chia.util.task_timing import maybe_manage_task_instrumentation
from chia.wallet.wallet_node import WalletNode

# See: https://bugs.python.org/issue29288
from chia.wallet.wallet_node_api import WalletNodeAPI

"".encode("idna")

SERVICE_NAME = "wallet"


def create_wallet_service(
    root_path: pathlib.Path,
    config: Dict[str, Any],
    consensus_constants: ConsensusConstants,
    keychain: Optional[Keychain] = None,
    connect_to_daemon: bool = True,
) -> Service[WalletNode, WalletNodeAPI]:
    service_config = config[SERVICE_NAME]

    overrides = service_config["network_overrides"]["constants"][service_config["selected_network"]]
    updated_constants = consensus_constants.replace_str_to_bytes(**overrides)
    if "short_sync_blocks_behind_threshold" not in service_config:
        service_config["short_sync_blocks_behind_threshold"] = 20

    node = WalletNode(
        service_config,
        root_path,
        constants=updated_constants,
        local_keychain=keychain,
    )
    peer_api = WalletNodeAPI(node)
    fnp = service_config.get("full_node_peer")
    connect_peers = set() if fnp is None else {UnresolvedPeerInfo(fnp["host"], fnp["port"])}

    network_id = service_config["selected_network"]
    rpc_port = service_config.get("rpc_port")
    rpc_info: Optional[RpcInfo] = None
    if rpc_port is not None:
        rpc_info = (WalletRpcApi, service_config["rpc_port"])

    return Service(
        root_path=root_path,
        config=config,
        node=node,
        peer_api=peer_api,
        listen=False,
        node_type=NodeType.WALLET,
        service_name=SERVICE_NAME,
        on_connect_callback=node.on_connect,
        connect_peers=connect_peers,
        network_id=network_id,
        rpc_info=rpc_info,
        advertised_port=service_config["port"],
        connect_to_daemon=connect_to_daemon,
    )


async def async_main() -> int:
    # TODO: refactor to avoid the double load
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    service_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    config[SERVICE_NAME] = service_config

    # This is simulator
    local_test = service_config.get("testing", False)
    if local_test is True:
        from chia.simulator.block_tools import test_constants

        constants = test_constants
        current = service_config["database_path"]
        service_config["database_path"] = f"{current}_simulation"
        service_config["selected_network"] = "testnet0"
    else:
        constants = DEFAULT_CONSTANTS
    initialize_service_logging(service_name=SERVICE_NAME, config=config)
    service = create_wallet_service(DEFAULT_ROOT_PATH, config, constants)
    await service.setup_process_global_state()
    await service.run()

    return 0


def main() -> int:
    freeze_support()

    with maybe_manage_task_instrumentation(enable=os.environ.get("CHIA_INSTRUMENT_WALLET") is not None):
        return async_run(async_main())


if __name__ == "__main__":
    sys.exit(main())
