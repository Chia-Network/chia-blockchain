import logging
import pathlib

# from multiprocessing import freeze_support
from typing import Any, Dict, Optional

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_api import DataLayerAPI

from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service

from chia.util.config import load_config_cli, load_config
from chia.util.default_root import DEFAULT_ROOT_PATH

# See: https://bugs.python.org/issue29288
from chia.util.keychain import Keychain
from chia.wallet.wallet_node import WalletNode

"".encode("idna")

SERVICE_NAME = "data_layer"
log = logging.getLogger(__name__)


def service_kwargs_for_data_layer(
    root_path: pathlib.Path, config: Dict, constants, keychain: Optional[Keychain] = None
) -> Dict[str, Any]:
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", "wallet")

    # add local node to trusted peers if old config
    node = WalletNode(
        config,
        root_path,
        consensus_constants=constants,
        local_keychain=keychain,
    )
    data_layer = DataLayer(root_path=root_path, wallet_node=node)
    api = DataLayerAPI(data_layer)
    network_id = config["selected_network"]
    kwargs: Dict[str, Any] = dict(
        root_path=root_path,
        node=data_layer,
        # TODO: not for peers...
        peer_api=api,
        node_type=NodeType.DATA_LAYER,
        # TODO: no publicly advertised port, at least not yet
        advertised_port=config["port"],
        service_name=SERVICE_NAME,
        network_id=network_id,
    )
    port = config.get("port")
    if port is not None:
        kwargs.update(advertised_port=config["port"], server_listen_ports=[config["port"]])
    rpc_port = config.get("rpc_port")
    if rpc_port is not None:
        kwargs["rpc_info"] = (DataLayerRpcApi, config["rpc_port"])
    return kwargs


def main() -> None:
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    kwargs = service_kwargs_for_data_layer(DEFAULT_ROOT_PATH, config, DEFAULT_CONSTANTS)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
