from multiprocessing import freeze_support

from src.wallet.wallet_node import WalletNode
from src.rpc.wallet_rpc_api import WalletRpcApi
from src.server.outbound_message import NodeType
from src.server.start_service import run_service
from src.util.config import load_config_cli
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.keychain import Keychain
from src.simulator.simulator_constants import test_constants
from src.types.peer_info import PeerInfo

# See: https://bugs.python.org/issue29288
u"".encode("idna")


def service_kwargs_for_wallet(root_path):
    service_name = "wallet"
    config = load_config_cli(root_path, "config.yaml", service_name)
    keychain = Keychain(testing=False)

    if config["testing"] is True:
        config["database_path"] = "test_db_wallet.db"
        api = WalletNode(
            config, keychain, root_path, override_constants=test_constants,
        )
    else:
        api = WalletNode(config, keychain, root_path)

    introducer = config["introducer_peer"]
    peer_info = PeerInfo(introducer["host"], introducer["port"])
    connect_peers = [
        PeerInfo(config["full_node_peer"]["host"], config["full_node_peer"]["port"])
    ]

    async def start_callback():
        await api._start()

    def stop_callback():
        api._close()

    async def await_closed_callback():
        await api._await_closed()

    kwargs = dict(
        root_path=root_path,
        api=api,
        node_type=NodeType.WALLET,
        advertised_port=config["port"],
        service_name=service_name,
        server_listen_ports=[config["port"]],
        on_connect_callback=api._on_connect,
        stop_callback=stop_callback,
        start_callback=start_callback,
        await_closed_callback=await_closed_callback,
        rpc_info=(WalletRpcApi, config["rpc_port"]),
        connect_peers=connect_peers,
        auth_connect_peers=False,
        periodic_introducer_poll=(
            peer_info,
            config["introducer_connect_interval"],
            config["target_peer_count"],
        ),
    )
    return kwargs


def main():
    kwargs = service_kwargs_for_wallet(DEFAULT_ROOT_PATH)
    return run_service(**kwargs)


if __name__ == "__main__":
    freeze_support()
    main()
