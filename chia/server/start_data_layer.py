import logging
import pathlib

# from multiprocessing import freeze_support
from typing import Any, Dict

from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_api import DataLayerAPI

# from chia.rpc.full_node_rpc_api import FullNodeRpcApi
# from chia.server.outbound_message import NodeType
from chia.server.start_service import run_service
from chia.util.config import load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "data_layer"
log = logging.getLogger(__name__)


def service_kwargs_for_data_layer(
    root_path: pathlib.Path, config: Dict, consensus_constants: ConsensusConstants
) -> Dict[str, Any]:
    data_layer = DataLayer(
        config,
        root_path=root_path,
        consensus_constants=consensus_constants,
    )
    api = DataLayerAPI(data_layer)

    # upnp_list = []
    # if config["enable_upnp"]:
    #     upnp_list = [config["port"]]
    # network_id = config["selected_network"]
    kwargs: Dict[str, Any] = dict(
        # root_path=root_path,
        # node=api.full_node,
        # TODO: not for peers...
        peer_api=api,
        # node_type=NodeType.FULL_NODE,
        # advertised_port=config["port"],
        # service_name=SERVICE_NAME,
        # upnp_ports=upnp_list,
        # server_listen_ports=[config["port"]],
        # on_connect_callback=full_node.on_connect,
        # network_id=network_id,
    )
    # if config["start_rpc_server"]:
    #     kwargs["rpc_info"] = (FullNodeRpcApi, config["rpc_port"])
    return kwargs


def main() -> None:
    config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME)
    # overrides = config["network_overrides"]["constants"][config["selected_network"]]
    # updated_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
    kwargs = service_kwargs_for_data_layer(DEFAULT_ROOT_PATH, config, DEFAULT_CONSTANTS)
    return run_service(**kwargs)


if __name__ == "__main__":
    main()
