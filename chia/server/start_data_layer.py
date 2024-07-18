from __future__ import annotations

import logging
import pathlib
import sys
from typing import Any, Dict, List, Optional, cast

from chia.data_layer.data_layer import DataLayer
from chia.data_layer.data_layer_api import DataLayerAPI
from chia.data_layer.data_layer_util import PluginRemote
from chia.data_layer.util.plugin import load_plugin_configurations
from chia.rpc.data_layer_rpc_api import DataLayerRpcApi
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.server.outbound_message import NodeType
from chia.server.signal_handlers import SignalHandlers
from chia.server.start_service import RpcInfo, Service, async_run
from chia.ssl.create_ssl import create_all_ssl
from chia.types.aliases import DataLayerService, WalletService
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config, load_config_cli
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint16

# See: https://bugs.python.org/issue29288
"".encode("idna")

SERVICE_NAME = "data_layer"
log = logging.getLogger(__name__)


# TODO: Review need for config and if retained then hint it properly.
def create_data_layer_service(
    root_path: pathlib.Path,
    config: Dict[str, Any],
    downloaders: List[PluginRemote],
    uploaders: List[PluginRemote],  # dont add FilesystemUploader to this, it is the default uploader
    wallet_service: Optional[WalletService] = None,
    connect_to_daemon: bool = True,
) -> DataLayerService:
    if uploaders is None:
        uploaders = []
    if downloaders is None:
        downloaders = []
    service_config = config[SERVICE_NAME]
    self_hostname = config["self_hostname"]
    wallet_rpc_port = service_config["wallet_peer"]["port"]
    if wallet_service is None:
        wallet_root_path = root_path
        wallet_config = config
    else:
        wallet_root_path = wallet_service.root_path
        wallet_config = wallet_service.config
    wallet_rpc_init = WalletRpcClient.create(self_hostname, uint16(wallet_rpc_port), wallet_root_path, wallet_config)

    data_layer = DataLayer.create(
        config=service_config,
        root_path=root_path,
        wallet_rpc_init=wallet_rpc_init,
        downloaders=downloaders,
        uploaders=uploaders,
    )  # dont add Fil)
    api = DataLayerAPI(data_layer)
    network_id = service_config["selected_network"]
    rpc_port = service_config.get("rpc_port")
    rpc_info: Optional[RpcInfo[DataLayerRpcApi]] = None
    if rpc_port is not None:
        rpc_info = (DataLayerRpcApi, cast(int, service_config["rpc_port"]))

    return Service(
        root_path=root_path,
        config=config,
        node=data_layer,
        # TODO: not for peers...
        peer_api=api,
        node_type=NodeType.DATA_LAYER,
        advertised_port=None,
        service_name=SERVICE_NAME,
        network_id=network_id,
        max_request_body_size=service_config.get("rpc_server_max_request_body_size", 26214400),
        rpc_info=rpc_info,
        connect_to_daemon=connect_to_daemon,
    )


async def async_main() -> int:
    # TODO: refactor to avoid the double load
    config = load_config(DEFAULT_ROOT_PATH, "config.yaml", fill_missing_services=True)
    service_config = load_config_cli(DEFAULT_ROOT_PATH, "config.yaml", SERVICE_NAME, fill_missing_services=True)
    config[SERVICE_NAME] = service_config
    initialize_logging(
        service_name=SERVICE_NAME,
        logging_config=service_config["logging"],
        root_path=DEFAULT_ROOT_PATH,
    )

    create_all_ssl(
        root_path=DEFAULT_ROOT_PATH,
        private_node_names=["data_layer"],
        public_node_names=["data_layer"],
        overwrite=False,
    )

    plugins_config = config["data_layer"].get("plugins", {})
    service_dir = DEFAULT_ROOT_PATH / SERVICE_NAME

    old_uploaders = config["data_layer"].get("uploaders", [])
    new_uploaders = plugins_config.get("uploaders", [])
    conf_file_uploaders = await load_plugin_configurations(service_dir, "uploaders", log)
    uploaders: List[PluginRemote] = [
        *(PluginRemote(url=url) for url in old_uploaders),
        *(PluginRemote.unmarshal(marshalled=marshalled) for marshalled in new_uploaders),
        *conf_file_uploaders,
    ]

    old_downloaders = config["data_layer"].get("downloaders", [])
    new_downloaders = plugins_config.get("downloaders", [])
    conf_file_uploaders = await load_plugin_configurations(service_dir, "downloaders", log)
    downloaders: List[PluginRemote] = [
        *(PluginRemote(url=url) for url in old_downloaders),
        *(PluginRemote.unmarshal(marshalled=marshalled) for marshalled in new_downloaders),
        *conf_file_uploaders,
    ]

    service = create_data_layer_service(DEFAULT_ROOT_PATH, config, downloaders, uploaders)
    async with SignalHandlers.manage() as signal_handlers:
        await service.setup_process_global_state(signal_handlers=signal_handlers)
        await service.run()

    return 0


def main() -> int:
    return async_run(async_main())


if __name__ == "__main__":
    sys.exit(main())
