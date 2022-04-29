import asyncio
import logging
import signal
import sqlite3
from secrets import token_bytes
from typing import AsyncGenerator, Optional

from chia.consensus.constants import ConsensusConstants
from chia.daemon.server import WebSocketServer, create_server_for_daemon, daemon_launch_lock_path, singleton
from chia.server.start_farmer import service_kwargs_for_farmer
from chia.server.start_full_node import service_kwargs_for_full_node
from chia.server.start_harvester import service_kwargs_for_harvester
from chia.server.start_introducer import service_kwargs_for_introducer
from chia.server.start_service import Service
from chia.server.start_timelord import service_kwargs_for_timelord
from chia.server.start_wallet import service_kwargs_for_wallet
from chia.simulator.start_simulator import service_kwargs_for_full_node_simulator
from chia.timelord.timelord_launcher import kill_processes, spawn_process
from chia.types.peer_info import PeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint16
from chia.util.keychain import bytes_to_mnemonic
from tests.block_tools import BlockTools
from tests.util.keyring import TempKeyring

log = logging.getLogger(__name__)


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
    create_server_for_daemon(btools.root_path)
    ws_server = WebSocketServer(root_path, ca_crt_path, ca_key_path, crt_path, key_path)
    await ws_server.start()

    yield ws_server

    await ws_server.stop()


async def setup_full_node(
    consensus_constants: ConsensusConstants,
    db_name,
    self_hostname: str,
    port,
    rpc_port,
    local_bt: BlockTools,
    introducer_port=None,
    simulator=False,
    send_uncompact_interval=0,
    sanitize_weight_proof_only=False,
    connect_to_daemon=False,
    db_version=1,
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
    config = local_bt.config["full_node"]

    config["database_path"] = db_name
    config["send_uncompact_interval"] = send_uncompact_interval
    config["target_uncompact_proofs"] = 30
    config["peer_connect_interval"] = 50
    config["sanitize_weight_proof_only"] = sanitize_weight_proof_only
    if introducer_port is not None:
        config["introducer_peer"]["host"] = self_hostname
        config["introducer_peer"]["port"] = introducer_port
    else:
        config["introducer_peer"] = None
    config["dns_servers"] = []
    config["port"] = port
    config["rpc_port"] = rpc_port
    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    updated_constants = consensus_constants.replace_str_to_bytes(**overrides)
    if simulator:
        kwargs = service_kwargs_for_full_node_simulator(local_bt.root_path, config, local_bt)
    else:
        kwargs = service_kwargs_for_full_node(local_bt.root_path, config, updated_constants)

    kwargs.update(
        parse_cli_args=False,
        connect_to_daemon=connect_to_daemon,
        service_name_prefix="test_",
    )

    service = Service(**kwargs, handle_signals=False)

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
    port,
    rpc_port,
    consensus_constants: ConsensusConstants,
    local_bt: BlockTools,
    full_node_port=None,
    introducer_port=None,
    key_seed=None,
    starting_height=None,
    initial_num_public_keys=5,
):
    with TempKeyring(populate=True) as keychain:
        config = local_bt.config["wallet"]
        config["port"] = port
        config["rpc_port"] = rpc_port
        if starting_height is not None:
            config["starting_height"] = starting_height
        config["initial_num_public_keys"] = initial_num_public_keys

        entropy = token_bytes(32)
        if key_seed is None:
            key_seed = entropy
        keychain.add_private_key(bytes_to_mnemonic(key_seed), "")
        first_pk = keychain.get_first_public_key()
        assert first_pk is not None
        db_path_key_suffix = str(first_pk.get_fingerprint())
        db_name = f"test-wallet-db-{port}-KEY.sqlite"
        db_path_replaced: str = db_name.replace("KEY", db_path_key_suffix)
        db_path = local_bt.root_path / db_path_replaced

        if db_path.exists():
            db_path.unlink()
        config["database_path"] = str(db_name)
        config["testing"] = True

        config["introducer_peer"]["host"] = self_hostname
        if introducer_port is not None:
            config["introducer_peer"]["port"] = introducer_port
            config["peer_connect_interval"] = 10
        else:
            config["introducer_peer"] = None

        if full_node_port is not None:
            config["full_node_peer"] = {}
            config["full_node_peer"]["host"] = self_hostname
            config["full_node_peer"]["port"] = full_node_port
        else:
            del config["full_node_peer"]

        kwargs = service_kwargs_for_wallet(local_bt.root_path, config, consensus_constants, keychain)
        kwargs.update(
            parse_cli_args=False,
            connect_to_daemon=False,
            service_name_prefix="test_",
        )

        service = Service(**kwargs, handle_signals=False)

        await service.start()

        yield service._node, service._node.server

        service.stop()
        await service.wait_closed()
        if db_path.exists():
            db_path.unlink()
        keychain.delete_all_keys()


async def setup_harvester(
    b_tools: BlockTools,
    self_hostname: str,
    port,
    rpc_port,
    farmer_port,
    consensus_constants: ConsensusConstants,
    start_service: bool = True,
):

    config = b_tools.config["harvester"]
    config["port"] = port
    config["rpc_port"] = rpc_port
    kwargs = service_kwargs_for_harvester(b_tools.root_path, config, consensus_constants)
    kwargs.update(
        server_listen_ports=[port],
        advertised_port=port,
        connect_peers=[PeerInfo(self_hostname, farmer_port)],
        parse_cli_args=False,
        connect_to_daemon=False,
        service_name_prefix="test_",
    )

    service = Service(**kwargs, handle_signals=False)

    if start_service:
        await service.start()

    yield service

    service.stop()
    await service.wait_closed()


async def setup_farmer(
    b_tools: BlockTools,
    self_hostname: str,
    port,
    rpc_port,
    consensus_constants: ConsensusConstants,
    full_node_port: Optional[uint16] = None,
    start_service: bool = True,
):
    config = b_tools.config["farmer"]
    config_pool = b_tools.config["pool"]

    config["xch_target_address"] = encode_puzzle_hash(b_tools.farmer_ph, "xch")
    config["pool_public_keys"] = [bytes(pk).hex() for pk in b_tools.pool_pubkeys]
    config["port"] = port
    config["rpc_port"] = rpc_port
    config_pool["xch_target_address"] = encode_puzzle_hash(b_tools.pool_ph, "xch")

    if full_node_port:
        config["full_node_peer"]["host"] = self_hostname
        config["full_node_peer"]["port"] = full_node_port
    else:
        del config["full_node_peer"]

    kwargs = service_kwargs_for_farmer(
        b_tools.root_path, config, config_pool, consensus_constants, b_tools.local_keychain
    )
    kwargs.update(
        parse_cli_args=False,
        connect_to_daemon=False,
        service_name_prefix="test_",
    )

    service = Service(**kwargs, handle_signals=False)

    if start_service:
        await service.start()

    yield service

    service.stop()
    await service.wait_closed()


async def setup_introducer(bt: BlockTools, port):
    kwargs = service_kwargs_for_introducer(
        bt.root_path,
        bt.config["introducer"],
    )
    kwargs.update(
        advertised_port=port,
        parse_cli_args=False,
        connect_to_daemon=False,
        service_name_prefix="test_",
    )

    service = Service(**kwargs, handle_signals=False)

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
    port, full_node_port, rpc_port, vdf_port, sanitizer, consensus_constants: ConsensusConstants, b_tools: BlockTools
):
    config = b_tools.config["timelord"]
    config["port"] = port
    config["full_node_peer"]["port"] = full_node_port
    config["bluebox_mode"] = sanitizer
    config["fast_algorithm"] = False
    config["vdf_server"]["port"] = vdf_port
    config["start_rpc_server"] = True
    config["rpc_port"] = rpc_port

    kwargs = service_kwargs_for_timelord(b_tools.root_path, config, consensus_constants)
    kwargs.update(
        parse_cli_args=False,
        connect_to_daemon=False,
        service_name_prefix="test_",
    )

    service = Service(**kwargs, handle_signals=False)

    await service.start()

    yield service._api, service._node.server

    service.stop()
    await service.wait_closed()
