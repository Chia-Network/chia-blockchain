import logging
import pathlib
from typing import Any, Dict
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_api import DataLayerAPI

from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service

from chia.util.config import load_config_cli, load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "data_layer"
log = logging.getLogger(__name__)


# TODO: Review need for config and if retained then hint it properly.
def service_kwargs_for_data_layer(root_path: pathlib.Path, wallet_rpc_port=None) -> Dict[str, Any]:
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    dl_config = load_config(DEFAULT_ROOT_PATH, "config.yaml", "data_layer")
    self_hostname = config["self_hostname"]
    if wallet_rpc_port is None:
        wallet_rpc_port = dl_config["wallet_peer"]["port"]
    wallet_rpc_init = WalletRpcClient.create(self_hostname, uint16(wallet_rpc_port), DEFAULT_ROOT_PATH, config)
    data_layer = DataLayer(root_path=root_path, wallet_rpc_init=wallet_rpc_init)
    api = DataLayerAPI(data_layer)
    network_id = dl_config["selected_network"]
    kwargs: Dict[str, Any] = dict(
        root_path=root_path,
        node=data_layer,
        # TODO: not for peers...
        peer_api=api,
        node_type=NodeType.DATA_LAYER,
        # TODO: no publicly advertised port, at least not yet
        advertised_port=dl_config["port"],
        service_name=SERVICE_NAME,
        network_id=network_id,
    )
    port = dl_config.get("port")
    if port is not None:
        kwargs.update(advertised_port=dl_config["port"], server_listen_ports=[dl_config["port"]])
    rpc_port = dl_config.get("rpc_port")
    if rpc_port is not None:
        kwargs["rpc_info"] = (DataLayerRpcApi, dl_config["rpc_port"])
    return kwargs


def main() -> None:
    kwargs = service_kwargs_for_data_layer(DEFAULT_ROOT_PATH)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
