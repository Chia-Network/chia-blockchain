import asyncio
import logging
import signal
import sqlite3
from pathlib import Path
from secrets import token_bytes
from typing import AsyncGenerator, List, Optional, Tuple

from chia.cmds.init_funcs import init
from chia.consensus.constants import ConsensusConstants
from chia.daemon.server import WebSocketServer, daemon_launch_lock_path, singleton
from chia.protocols.shared_protocol import Capability, capabilities
from chia.server.start_farmer import service_kwargs_for_farmer
from chia.server.start_full_node import service_kwargs_for_full_node
from chia.server.start_harvester import service_kwargs_for_harvester
from chia.server.start_introducer import service_kwargs_for_introducer
from chia.server.start_service import Service
from chia.server.start_timelord import service_kwargs_for_timelord
from chia.server.start_wallet import service_kwargs_for_wallet
from chia.simulator.start_simulator import service_kwargs_for_full_node_simulator
from chia.timelord.timelord_launcher import kill_processes, spawn_process
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import lock_and_load_config, save_config
from chia.util.ints import uint16
from chia.util.keychain import bytes_to_mnemonic
from tests.block_tools import BlockTools
from tests.util.keyring import TempKeyring

log = logging.getLogger(__name__)


def get_capabilities(disable_capabilities_values: Optional[List[Capability]]) -> List[Tuple[uint16, str]]:
    if disable_capabilities_values is not None:
        try:
            if Capability.BASE in disable_capabilities_values:
                # BASE capability cannot be removed
                disable_capabilities_values.remove(Capability.BASE)

            updated_capabilities = []
            for capability in capabilities:
                if Capability(int(capability[0])) in disable_capabilities_values:
                    # "0" means capability is disabled
                    updated_capabilities.append((capability[0], "0"))
                else:
                    updated_capabilities.append(capability)
            return updated_capabilities
        except Exception:
            logging.getLogger(__name__).exception("Error disabling capabilities, defaulting to all capabilities")
    return capabilities.copy()


async def setup_daemon(btools: BlockTools) -> AsyncGenerator[WebSocketServer, None]:
    root_path = btools.root_path
    config = btools.config
    assert "daemon_port" in config
    lockfile = singleton(daemon_launch_lock_path(root_path))
    crt_path = root_path / config["daemon_ssl"]["private_crt"]
    key_path = root_path / config["daemon_ssl"]["private_key"]
    ca_crt_path = root_path / config["private_ssl_ca"]["crt"]
    ca_key_path = root_path / config["private_ssl_ca"]["key"]
    assert lockfile is not None
    shutdown_event = asyncio.Event()
    ws_server = WebSocketServer(root_path, ca_crt_path, ca_key_path, crt_path, key_path, shutdown_event)
    await ws_server.start()

    yield ws_server

    await ws_server.stop()


async def setup_full_node(
    consensus_constants: ConsensusConstants,
    db_name: str,
    self_hostname: str,
    local_bt: BlockTools,
    introducer_port=None,
    simulator=False,
    send_uncompact_interval=0,
    sanitize_weight_proof_only=False,
    connect_to_daemon=False,
    db_version=1,
    disable_capabilities: Optional[List[Capability]] = None,
):
    db_path = local_bt.root_path / f"{db_name}"
    if db_path.exists():
        db_path.unlink()

        if db_version > 1:
            with sqlite3.connect(db_path) as connection:
                connection.execute("CREATE TABLE database_version(version int)")
                connection.execute("INSERT INTO database_version VALUES (?)", (db_version,))
                connection.commit()

    if connect_to_daemon:
        assert local_bt.config["daemon_port"] is not None
    config = local_bt.config
    service_config = config["full_node"]
    service_config["database_path"] = db_name
    service_config["send_uncompact_interval"] = send_uncompact_interval
    service_config["target_uncompact_proofs"] = 30
    service_config["peer_connect_interval"] = 50
    service_config["sanitize_weight_proof_only"] = sanitize_weight_proof_only
    if introducer_port is not None:
        service_config["introducer_peer"]["host"] = self_hostname
        service_config["introducer_peer"]["port"] = introducer_port
    else:
        service_config["introducer_peer"] = None
    service_config["dns_servers"] = []
    service_config["port"] = 0
    service_config["rpc_port"] = 0

    overrides = service_config["network_overrides"]["constants"][service_config["selected_network"]]
    updated_constants = consensus_constants.replace_str_to_bytes(**overrides)
    if simulator:
        kwargs = service_kwargs_for_full_node_simulator(local_bt.root_path, config, local_bt)
    else:
        kwargs = service_kwargs_for_full_node(local_bt.root_path, config, updated_constants)

    kwargs.update(
        connect_to_daemon=connect_to_daemon,
    )
    if disable_capabilities is not None:
        kwargs.update(override_capabilities=get_capabilities(disable_capabilities))

    service = Service(**kwargs)

    await service.start()

    yield service._api

    service.stop()
    await service.wait_closed()
    if db_path.exists():
        db_path.unlink()


# Note: convert these setup functions to fixtures, or push it one layer up,
# keeping these usable independently?
async def setup_wallet_node(
    self_hostname: str,
    consensus_constants: ConsensusConstants,
    local_bt: BlockTools,
    full_node_port=None,
    introducer_port=None,
    key_seed=None,
    starting_height=None,
    initial_num_public_keys=5,
):
    with TempKeyring(populate=True) as keychain:
        config = local_bt.config
        service_config = config["wallet"]
        service_config["port"] = 0
        service_config["rpc_port"] = 0
        if starting_height is not None:
            service_config["starting_height"] = starting_height
        service_config["initial_num_public_keys"] = initial_num_public_keys

        entropy = token_bytes(32)
        if key_seed is None:
            key_seed = entropy
        keychain.add_private_key(bytes_to_mnemonic(key_seed), "")
        first_pk = keychain.get_first_public_key()
        assert first_pk is not None
        db_path_key_suffix = str(first_pk.get_fingerprint())
        db_name = f"test-wallet-db-{full_node_port}-KEY.sqlite"
        db_path_replaced: str = db_name.replace("KEY", db_path_key_suffix)
        db_path = local_bt.root_path / db_path_replaced

        if db_path.exists():
            db_path.unlink()
        service_config["database_path"] = str(db_name)
        service_config["testing"] = True

        service_config["introducer_peer"]["host"] = self_hostname
        if introducer_port is not None:
            service_config["introducer_peer"]["port"] = introducer_port
            service_config["peer_connect_interval"] = 10
        else:
            service_config["introducer_peer"] = None

        if full_node_port is not None:
            service_config["full_node_peer"] = {}
            service_config["full_node_peer"]["host"] = self_hostname
            service_config["full_node_peer"]["port"] = full_node_port
        else:
            del service_config["full_node_peer"]

        kwargs = service_kwargs_for_wallet(local_bt.root_path, config, consensus_constants, keychain)
        kwargs.update(
            connect_to_daemon=False,
        )

        service = Service(**kwargs)

        await service.start()

        yield service._node, service._node.server

        service.stop()
        await service.wait_closed()
        if db_path.exists():
            db_path.unlink()
        keychain.delete_all_keys()


async def setup_harvester(
    b_tools: BlockTools,
    root_path: Path,
    self_hostname: str,
    farmer_port: uint16,
    consensus_constants: ConsensusConstants,
    start_service: bool = True,
):
    init(None, root_path)
    init(b_tools.root_path / "config" / "ssl" / "ca", root_path)
    with lock_and_load_config(root_path, "config.yaml") as config:
        config["logging"]["log_stdout"] = True
        config["selected_network"] = "testnet0"
        config["harvester"]["selected_network"] = "testnet0"
        config["harvester"]["port"] = 0
        config["harvester"]["rpc_port"] = 0
        config["harvester"]["farmer_peer"]["host"] = self_hostname
        config["harvester"]["farmer_peer"]["port"] = int(farmer_port)
        config["harvester"]["plot_directories"] = [str(b_tools.plot_dir.resolve())]
        save_config(root_path, "config.yaml", config)
    kwargs = service_kwargs_for_harvester(root_path, config, consensus_constants)
    kwargs.update(
        connect_to_daemon=False,
    )

    service = Service(**kwargs)

    if start_service:
        await service.start()

    yield service

    service.stop()
    await service.wait_closed()


async def setup_farmer(
    b_tools: BlockTools,
    root_path: Path,
    self_hostname: str,
    consensus_constants: ConsensusConstants,
    full_node_port: Optional[uint16] = None,
    start_service: bool = True,
    port: uint16 = uint16(0),
):
    init(None, root_path)
    init(b_tools.root_path / "config" / "ssl" / "ca", root_path)
    with lock_and_load_config(root_path, "config.yaml") as root_config:
        root_config["logging"]["log_stdout"] = True
        root_config["selected_network"] = "testnet0"
        root_config["farmer"]["selected_network"] = "testnet0"
        save_config(root_path, "config.yaml", root_config)
    service_config = root_config["farmer"]
    config_pool = root_config["pool"]

    service_config["xch_target_address"] = encode_puzzle_hash(b_tools.farmer_ph, "xch")
    service_config["pool_public_keys"] = [bytes(pk).hex() for pk in b_tools.pool_pubkeys]
    service_config["port"] = port
    service_config["rpc_port"] = uint16(0)
    config_pool["xch_target_address"] = encode_puzzle_hash(b_tools.pool_ph, "xch")

    if full_node_port:
        service_config["full_node_peer"]["host"] = self_hostname
        service_config["full_node_peer"]["port"] = full_node_port
    else:
        del service_config["full_node_peer"]

    kwargs = service_kwargs_for_farmer(root_path, root_config, config_pool, consensus_constants, b_tools.local_keychain)
    kwargs.update(
        connect_to_daemon=False,
    )

    service = Service(**kwargs)

    if start_service:
        await service.start()

    yield service

    service.stop()
    await service.wait_closed()


async def setup_introducer(bt: BlockTools, port):
    kwargs = service_kwargs_for_introducer(
        bt.root_path,
        bt.config,
    )
    kwargs.update(
        advertised_port=port,
        connect_to_daemon=False,
    )

    service = Service(**kwargs)

    await service.start()

    yield service._api, service._node.server

    service.stop()
    await service.wait_closed()


async def setup_vdf_client(bt: BlockTools, self_hostname: str, port):
    vdf_task_1 = asyncio.create_task(spawn_process(self_hostname, port, 1, bt.config.get("prefer_ipv6")))

    def stop():
        asyncio.create_task(kill_processes())

    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop)
    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop)

    yield vdf_task_1
    await kill_processes()


async def setup_vdf_clients(bt: BlockTools, self_hostname: str, port):
    vdf_task_1 = asyncio.create_task(spawn_process(self_hostname, port, 1, bt.config.get("prefer_ipv6")))
    vdf_task_2 = asyncio.create_task(spawn_process(self_hostname, port, 2, bt.config.get("prefer_ipv6")))
    vdf_task_3 = asyncio.create_task(spawn_process(self_hostname, port, 3, bt.config.get("prefer_ipv6")))

    def stop():
        asyncio.create_task(kill_processes())

    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop)
    asyncio.get_running_loop().add_signal_handler(signal.SIGINT, stop)

    yield vdf_task_1, vdf_task_2, vdf_task_3

    await kill_processes()


async def setup_timelord(
    full_node_port,
    sanitizer,
    consensus_constants: ConsensusConstants,
    b_tools: BlockTools,
    vdf_port: uint16 = uint16(0),
):
    config = b_tools.config
    service_config = config["timelord"]
    service_config["full_node_peer"]["port"] = full_node_port
    service_config["bluebox_mode"] = sanitizer
    service_config["fast_algorithm"] = False
    service_config["vdf_server"]["port"] = vdf_port
    service_config["start_rpc_server"] = True
    service_config["rpc_port"] = uint16(0)

    kwargs = service_kwargs_for_timelord(b_tools.root_path, config, consensus_constants)
    kwargs.update(
        connect_to_daemon=False,
    )

    service = Service(**kwargs)

    await service.start()

    yield service._api, service._node.server

    service.stop()
    await service.wait_closed()
