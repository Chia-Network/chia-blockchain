import pathlib
from multiprocessing import freeze_support
from typing import Dict, Optional

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.server.outbound_message import NodeType
from chia.server.start_service import RpcInfo, Service, async_run
from chia.types.peer_info import PeerInfo
from chia.util.config import load_config_cli, load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.keychain import Keychain
from chia.wallet.wallet_node import WalletNode

# See: https://bugs.python.org/issue29288
from chia.wallet.wallet_node_api import WalletNodeAPI

"".encode("idna")

SERVICE_NAME = "wallet"


def create_wallet_service(
    root_path: pathlib.Path,
    config: Dict,
    consensus_constants: ConsensusConstants,
    keychain: Optional[Keychain] = None,
    parse_cli_args: bool = True,
    connect_to_daemon: bool = True,
    service_name_prefix: str = "",
    running_new_process: bool = True,
) -> Service:
    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    updated_constants = consensus_constants.replace_str_to_bytes(**overrides)
    # add local node to trusted peers if old config
    if "trusted_peers" not in config:
        full_node_config = load_config(DEFAULT_ROOT_PATH, "config.yaml", "full_node")
        trusted_peer = full_node_config["ssl"]["public_crt"]
        config["trusted_peers"] = {}
        config["trusted_peers"]["local_node"] = trusted_peer
    if "short_sync_blocks_behind_threshold" not in config:
        config["short_sync_blocks_behind_threshold"] = 20
    node = WalletNode(
        config,
        root_path,
        constants=updated_constants,
        local_keychain=keychain,
    )
    peer_api = WalletNodeAPI(node)
    fnp = config.get("full_node_peer")

    if fnp:
        connect_peers = [PeerInfo(fnp["host"], fnp["port"])]
        node.full_node_peer = PeerInfo(fnp["host"], fnp["port"])
    else:
        connect_peers = []
        node.full_node_peer = None
    network_id = config["selected_network"]
    rpc_port = config.get("rpc_port")
    rpc_info: RpcInfo = None
    if rpc_port is not None:
        rpc_info = (WalletRpcApi, config["rpc_port"])

    return Service(
        advertised_port=config["port"],
        server_listen_ports=[config["port"]],
        root_path=root_path,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.WALLET,
        service_name=SERVICE_NAME,
        on_connect_callback=node.on_connect,
        connect_peers=connect_peers,
        auth_connect_peers=False,
        network_id=network_id,
        rpc_info=rpc_info,
        parse_cli_args=parse_cli_args,
        connect_to_daemon=connect_to_daemon,
        service_name_prefix=service_name_prefix,
        running_new_process=running_new_process,
    )


def main() -> None:
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    # This is simulator
    local_test = config["testing"]
    if local_test is True:
        from tests.block_tools import test_constants

        constants = test_constants
        current = config["database_path"]
        config["database_path"] = f"{current}_simulation"
        config["selected_network"] = "testnet0"
    else:
        constants = DEFAULT_CONSTANTS
    service = create_wallet_service(DEFAULT_ROOT_PATH, config, constants)
    return async_run(service.run())


if __name__ == "__main__":
    freeze_support()
    main()
