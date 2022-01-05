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
from chia.server.start_wallet import service_kwargs_for_wallet

from chia.util.config import load_config_cli, load_config
from chia.util.default_root import DEFAULT_ROOT_PATH

# See: https://bugs.python.org/issue29288
from chia.util.keychain import Keychain
from chia.wallet.wallet_node import WalletNode

"".encode("idna")

SERVICE_NAME = "data_layer"
log = logging.getLogger(__name__)


def service_kwargs_for_data_layer(
    root_path: pathlib.Path,
    config: Dict,
    wallet_config: Dict,
    constants: ConsensusConstants,
) -> Dict[str, Any]:
    wallet_kwargs = service_kwargs_for_wallet(DEFAULT_ROOT_PATH, wallet_config, constants)
    node = wallet_kwargs["node"]
    run_service(**wallet_kwargs)
    # assert node.wallet_state_manager
    data_layer = DataLayer(root_path=root_path, wallet_state_manager=node.wallet_state_manager)
    api = DataLayerAPI(data_layer)
    network_id = wallet_kwargs["selected_network"]
    kwargs: Dict[str, Any] = dict(
        root_path=root_path,
        node=data_layer,
        # TODO: not for peers...
        peer_api=api,
        node_type=NodeType.DATA_LAYER,
        # TODO: no publicly advertised port, at least not yet
        advertised_port=8562,
        service_name=SERVICE_NAME,
        network_id=network_id,
    )
    rpc_port = config.get("rpc_port")
    if rpc_port is not None:
        kwargs.update(advertised_port=rpc_port, server_listen_ports=[rpc_port])
        kwargs["rpc_info"] = (DataLayerRpcApi, config["rpc_port"])
    return kwargs


def main() -> None:
    wallet_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", "wallet")
    # This is simulator
    local_test = wallet_config.get("testing")
    if local_test is True:
        from tests.block_tools import test_constants

        constants = test_constants
        current = wallet_config["database_path"]
        wallet_config["database_path"] = f"{current}_simulation"
        wallet_config["selected_network"] = "testnet0"
    else:
        constants = DEFAULT_CONSTANTS
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", "data_layer")
    kwargs = service_kwargs_for_data_layer(
        DEFAULT_ROOT_PATH,
        config,
        wallet_config,
        constants,
    )
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
