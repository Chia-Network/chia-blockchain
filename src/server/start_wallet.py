import pathlib
from multiprocessing import freeze_support
from typing import Dict

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.rpc.wallet_rpc_api import WalletRpcApi
from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service
from chia.types.peer_info import PeerInfo
from chia.util.block_tools import test_constants
from chia.util.config import load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.keychain import Keychain
from chia.wallet.wallet_node import WalletNode

# See: https://bugs.python.org/issue29288
from chia.wallet.wallet_node_api import WalletNodeAPI

"".encode("idna")

SERVICE_NAME = "wallet"


def service_kwargs_for_wallet(
    root_path: pathlib.Path,
    config: Dict,
    consensus_constants: ConsensusConstants,
    keychain: Keychain,
) -> Dict:
    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    updated_constants = consensus_constants.replace_str_to_bytes(**overrides)
    # add local node to trusted peers if old config
    if "trusted_peers" not in config:
        full_node_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", "full_node")
        trusted_peer = full_node_config["ssl"]["public_crt"]
        config["trusted_peers"] = {}
        config["trusted_peers"]["local_node"] = trusted_peer
    node = WalletNode(
        config,
        keychain,
        root_path,
        consensus_constants=updated_constants,
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
    kwargs = dict(
        root_path=root_path,
        node=node,
        peer_api=peer_api,
        node_type=NodeType.WALLET,
        service_name=SERVICE_NAME,
        on_connect_callback=node.on_connect,
        connect_peers=connect_peers,
        auth_connect_peers=False,
        network_id=network_id,
    )
    port = config.get("port")
    if port is not None:
        kwargs.update(
            advertised_port=config["port"],
            server_listen_ports=[config["port"]],
        )
    rpc_port = config.get("rpc_port")
    if rpc_port is not None:
        kwargs["rpc_info"] = (WalletRpcApi, config["rpc_port"])

    return kwargs


def main():
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    # This is simulator
    local_test = config["testing"]
    if local_test is True:
        constants = test_constants
        current = config["database_path"]
        config["database_path"] = f"{current}_simulation"
        config["selected_network"] = "testnet0"
    else:
        constants = DEFAULT_CONSTANTS
    keychain = Keychain(testing=False)
    kwargs = service_kwargs_for_wallet(DEFAULT_ROOT_PATH, config, constants, keychain)
    return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
