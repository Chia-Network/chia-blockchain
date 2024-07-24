from __future__ import annotations

import asyncio
import gc
import logging
import signal
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import FrameType
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Iterator, List, Optional, Tuple, Union

from chia.cmds.init_funcs import init
from chia.consensus.constants import ConsensusConstants, replace_str_to_bytes
from chia.daemon.server import WebSocketServer, daemon_launch_lock_path
from chia.protocols.shared_protocol import Capability, default_capabilities
from chia.seeder.dns_server import DNSServer, create_dns_server_service
from chia.seeder.start_crawler import create_full_node_crawler_service
from chia.server.outbound_message import NodeType
from chia.server.signal_handlers import SignalHandlers
from chia.server.start_farmer import create_farmer_service
from chia.server.start_full_node import create_full_node_service
from chia.server.start_harvester import create_harvester_service
from chia.server.start_introducer import create_introducer_service
from chia.server.start_timelord import create_timelord_service
from chia.server.start_wallet import create_wallet_service
from chia.simulator.block_tools import BlockTools, test_constants
from chia.simulator.keyring import TempKeyring
from chia.simulator.ssl_certs import get_next_nodes_certs_and_keys, get_next_private_ca_cert_and_key
from chia.simulator.start_simulator import SimulatorFullNodeService, create_full_node_simulator_service
from chia.ssl.create_ssl import create_all_ssl
from chia.timelord.timelord_launcher import VDFClientProcessMgr, find_vdf_client, spawn_process
from chia.types.aliases import (
    CrawlerService,
    FarmerService,
    FullNodeService,
    HarvesterService,
    IntroducerService,
    TimelordService,
    WalletService,
)
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import config_path_for_filename, load_config, lock_and_load_config, save_config, set_peer_info
from chia.util.db_wrapper import generate_in_memory_db_uri
from chia.util.ints import uint16
from chia.util.keychain import bytes_to_mnemonic
from chia.util.lock import Lockfile

log = logging.getLogger(__name__)


@contextmanager
def create_lock_and_load_config(certs_path: Path, root_path: Path) -> Iterator[Dict[str, Any]]:
    init(None, root_path)
    init(certs_path, root_path)
    path = config_path_for_filename(root_path=root_path, filename="config.yaml")
    # Using localhost leads to flakiness on CI
    path.write_text(path.read_text().replace("localhost", "127.0.0.1"))
    with lock_and_load_config(root_path, "config.yaml") as config:
        yield config


def get_capability_overrides(node_type: NodeType, disabled_capabilities: List[Capability]) -> List[Tuple[uint16, str]]:
    return [
        (
            capability
            if Capability(int(capability[0])) not in disabled_capabilities
            or Capability(int(capability[0])) == Capability.BASE
            else (capability[0], "0")
        )
        for capability in default_capabilities[node_type]
    ]


@asynccontextmanager
async def setup_daemon(btools: BlockTools) -> AsyncGenerator[WebSocketServer, None]:
    root_path = btools.root_path
    config = btools.config
    assert "daemon_port" in config
    crt_path = root_path / config["daemon_ssl"]["private_crt"]
    key_path = root_path / config["daemon_ssl"]["private_key"]
    ca_crt_path = root_path / config["private_ssl_ca"]["crt"]
    ca_key_path = root_path / config["private_ssl_ca"]["key"]
    with Lockfile.create(daemon_launch_lock_path(root_path)):
        ws_server = WebSocketServer(root_path, ca_crt_path, ca_key_path, crt_path, key_path)
        async with ws_server.run():
            yield ws_server


@asynccontextmanager
async def setup_full_node(
    consensus_constants: ConsensusConstants,
    db_name: str,
    self_hostname: str,
    local_bt: BlockTools,
    introducer_port: Optional[int] = None,
    simulator: bool = False,
    send_uncompact_interval: int = 0,
    sanitize_weight_proof_only: bool = False,
    connect_to_daemon: bool = False,
    db_version: int = 1,
    disable_capabilities: Optional[List[Capability]] = None,
    *,
    reuse_db: bool = False,
) -> AsyncGenerator[Union[FullNodeService, SimulatorFullNodeService], None]:
    if reuse_db:
        db_path: Union[str, Path] = local_bt.root_path / f"{db_name}"
        uri = False
    else:
        db_path = generate_in_memory_db_uri()
        uri = True

    if not reuse_db and db_version > 1:
        with sqlite3.connect(db_path, uri=uri) as connection:
            connection.execute("CREATE TABLE database_version(version int)")
            connection.execute("INSERT INTO database_version VALUES (?)", (db_version,))
            connection.commit()

    if connect_to_daemon:
        assert local_bt.config["daemon_port"] is not None
    config = local_bt.config
    service_config = config["full_node"]
    service_config["database_path"] = db_name
    service_config["testing"] = True
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
    config["simulator"]["auto_farm"] = False  # Disable Auto Farm for tests
    config["simulator"]["use_current_time"] = False  # Disable Real timestamps when running tests
    overrides = service_config["network_overrides"]["constants"][service_config["selected_network"]]
    updated_constants = replace_str_to_bytes(consensus_constants, **overrides)
    local_bt.change_config(config)
    override_capabilities = (
        None if disable_capabilities is None else get_capability_overrides(NodeType.FULL_NODE, disable_capabilities)
    )
    service: Union[FullNodeService, SimulatorFullNodeService]
    if simulator:
        service = await create_full_node_simulator_service(
            local_bt.root_path,
            config,
            local_bt,
            connect_to_daemon=connect_to_daemon,
            override_capabilities=override_capabilities,
        )
    else:
        service = await create_full_node_service(
            local_bt.root_path,
            config,
            updated_constants,
            connect_to_daemon=connect_to_daemon,
            override_capabilities=override_capabilities,
        )

    async with service.manage():
        yield service


@asynccontextmanager
async def setup_crawler(
    root_path_populated_with_config: Path, database_uri: str, start_crawler_loop: bool = True
) -> AsyncGenerator[CrawlerService, None]:
    create_all_ssl(
        root_path=root_path_populated_with_config,
        private_ca_crt_and_key=get_next_private_ca_cert_and_key().collateral.cert_and_key,
        node_certs_and_keys=get_next_nodes_certs_and_keys().collateral.certs_and_keys,
    )
    config = load_config(root_path_populated_with_config, "config.yaml")
    service_config = config["seeder"]

    service_config["selected_network"] = "testnet0"
    service_config["port"] = 0
    service_config["crawler"]["start_rpc_server"] = False
    service_config["other_peers_port"] = 58444
    service_config["crawler_db_path"] = database_uri

    overrides = service_config["network_overrides"]["constants"][service_config["selected_network"]]
    updated_constants = replace_str_to_bytes(test_constants, **overrides)

    service = create_full_node_crawler_service(
        root_path_populated_with_config,
        config,
        updated_constants,
        connect_to_daemon=False,
        start_crawler_loop=start_crawler_loop,
    )
    async with service.manage():
        if not service_config["crawler"]["start_rpc_server"]:  # otherwise the loops don't work.
            service._node.state_changed_callback = lambda x, y: None

        yield service


@asynccontextmanager
async def setup_seeder(root_path_populated_with_config: Path, database_uri: str) -> AsyncGenerator[DNSServer, None]:
    config = load_config(root_path_populated_with_config, "config.yaml")
    service_config = config["seeder"]

    service_config["selected_network"] = "testnet0"
    if service_config["domain_name"].endswith("."):  # remove the trailing . so that we can test that logic.
        service_config["domain_name"] = service_config["domain_name"][:-1]
    service_config["dns_port"] = 0
    service_config["crawler_db_path"] = database_uri

    service = create_dns_server_service(
        config,
        root_path_populated_with_config,
    )
    async with service.run():
        yield service


# Note: convert these setup functions to fixtures, or push it one layer up,
# keeping these usable independently?
@asynccontextmanager
async def setup_wallet_node(
    self_hostname: str,
    consensus_constants: ConsensusConstants,
    local_bt: BlockTools,
    spam_filter_after_n_txs: Optional[int] = 200,
    xch_spam_amount: int = 1000000,
    full_node_port: Optional[uint16] = None,
    introducer_port: Optional[uint16] = None,
    key_seed: Optional[bytes] = None,
    initial_num_public_keys: int = 5,
) -> AsyncGenerator[WalletService, None]:
    with TempKeyring(populate=True) as keychain:
        config = local_bt.config
        service_config = config["wallet"]
        service_config["testing"] = True
        service_config["port"] = 0
        service_config["rpc_port"] = 0
        service_config["initial_num_public_keys"] = initial_num_public_keys
        service_config["spam_filter_after_n_txs"] = spam_filter_after_n_txs
        service_config["xch_spam_amount"] = xch_spam_amount

        entropy = bytes32.secret()
        if key_seed is None:
            key_seed = entropy
        keychain.add_key(bytes_to_mnemonic(key_seed))
        first_pk = keychain.get_first_public_key()
        assert first_pk is not None
        db_path_key_suffix = str(first_pk.get_fingerprint())
        db_name = f"test-wallet-db-{full_node_port}-KEY.sqlite"
        db_path_replaced: str = db_name.replace("KEY", db_path_key_suffix)
        db_path = local_bt.root_path / db_path_replaced

        if db_path.exists():
            # TODO: remove (maybe) when fixed https://github.com/python/cpython/issues/97641
            gc.collect()
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
            service_config.pop("full_node_peer", None)
            service_config["full_node_peers"] = [
                {
                    "host": self_hostname,
                    "port": full_node_port,
                },
            ]
        else:
            service_config.pop("full_node_peer", None)
            service_config.pop("full_node_peers", None)

        service = create_wallet_service(
            local_bt.root_path,
            config,
            consensus_constants,
            keychain,
            connect_to_daemon=False,
        )

        try:
            async with service.manage():
                yield service
        finally:
            if db_path.exists():
                # TODO: remove (maybe) when fixed https://github.com/python/cpython/issues/97641

                # 3.11 switched to using functools.lru_cache for the statement cache.
                # See #87028. This introduces a reference cycle involving the connection
                # object, so the connection object no longer gets immediately
                # deallocated, not until, for example, gc.collect() is called to break
                # the cycle.
                gc.collect()
                for _ in range(10):
                    try:
                        db_path.unlink()
                        break
                    except PermissionError as e:
                        print(f"db_path.unlink(): {e}")
                        time.sleep(0.1)
                        # filesystem operations are async on windows
                        # [WinError 32] The process cannot access the file because it is
                        # being used by another process
                        pass
            keychain.delete_all_keys()


@asynccontextmanager
async def setup_harvester(
    b_tools: BlockTools,
    root_path: Path,
    farmer_peer: Optional[UnresolvedPeerInfo],
    consensus_constants: ConsensusConstants,
    start_service: bool = True,
) -> AsyncGenerator[HarvesterService, None]:
    with create_lock_and_load_config(b_tools.root_path / "config" / "ssl" / "ca", root_path) as config:
        config["logging"]["log_stdout"] = True
        config["selected_network"] = "testnet0"
        config["harvester"]["selected_network"] = "testnet0"
        config["harvester"]["port"] = 0
        config["harvester"]["rpc_port"] = 0
        config["harvester"]["plot_directories"] = [str(b_tools.plot_dir.resolve())]
        # CI doesn't like GPU compressed farming
        config["harvester"]["parallel_decompressor_count"] = 0
        save_config(root_path, "config.yaml", config)
    service = create_harvester_service(
        root_path,
        config,
        consensus_constants,
        farmer_peers={farmer_peer} if farmer_peer is not None else set(),
        connect_to_daemon=False,
    )

    async with service.manage(start=start_service):
        yield service


@asynccontextmanager
async def setup_farmer(
    b_tools: BlockTools,
    root_path: Path,
    self_hostname: str,
    consensus_constants: ConsensusConstants,
    full_node_port: Optional[uint16] = None,
    start_service: bool = True,
    port: uint16 = uint16(0),
) -> AsyncGenerator[FarmerService, None]:
    with create_lock_and_load_config(b_tools.root_path / "config" / "ssl" / "ca", root_path) as root_config:
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
        service_config.pop("full_node_peer", None)
        service_config["full_node_peers"] = [
            {
                "host": self_hostname,
                "port": full_node_port,
            },
        ]
    else:
        service_config.pop("full_node_peer", None)
        service_config.pop("full_node_peers", None)

    service = create_farmer_service(
        root_path,
        root_config,
        config_pool,
        consensus_constants,
        b_tools.local_keychain,
        connect_to_daemon=False,
    )

    async with service.manage(start=start_service):
        yield service


@asynccontextmanager
async def setup_introducer(bt: BlockTools, port: int) -> AsyncGenerator[IntroducerService, None]:
    service = create_introducer_service(
        bt.root_path,
        bt.config,
        advertised_port=port,
        connect_to_daemon=False,
    )

    async with service.manage():
        yield service


@asynccontextmanager
async def setup_vdf_client(bt: BlockTools, self_hostname: str, port: int) -> AsyncIterator[None]:
    find_vdf_client()  # raises FileNotFoundError if not found
    process_mgr = VDFClientProcessMgr()
    vdf_task_1 = asyncio.create_task(
        spawn_process(self_hostname, port, 1, process_mgr, prefer_ipv6=bt.config.get("prefer_ipv6", False)),
        name="vdf_client_1",
    )

    async def stop(
        signal_: signal.Signals,
        stack_frame: Optional[FrameType],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        await process_mgr.kill_processes()

    async with SignalHandlers.manage() as signal_handlers:
        signal_handlers.setup_async_signal_handler(handler=stop)
        try:
            yield
        finally:
            await process_mgr.kill_processes()
            vdf_task_1.cancel()
            try:
                await vdf_task_1
            except (Exception, asyncio.CancelledError):
                pass


@asynccontextmanager
async def setup_vdf_clients(bt: BlockTools, self_hostname: str, port: int) -> AsyncIterator[None]:
    find_vdf_client()  # raises FileNotFoundError if not found

    process_mgr = VDFClientProcessMgr()
    tasks = []
    prefer_ipv6 = bt.config.get("prefer_ipv6", False)
    for i in range(1, 4):
        tasks.append(
            asyncio.create_task(
                spawn_process(
                    host=self_hostname, port=port, counter=i, process_mgr=process_mgr, prefer_ipv6=prefer_ipv6
                ),
                name=f"vdf_client_{i}",
            )
        )

    async def stop(
        signal_: signal.Signals,
        stack_frame: Optional[FrameType],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        await process_mgr.kill_processes()

    signal_handlers = SignalHandlers()
    async with signal_handlers.manage():
        signal_handlers.setup_async_signal_handler(handler=stop)
        try:
            yield
        finally:
            await process_mgr.kill_processes()
            for task in tasks:
                task.cancel()
                try:
                    await task
                except (Exception, asyncio.CancelledError):
                    pass


@asynccontextmanager
async def setup_timelord(
    full_node_port: int,
    sanitizer: bool,
    consensus_constants: ConsensusConstants,
    config: Dict[str, Any],
    root_path: Path,
    vdf_port: uint16 = uint16(0),
) -> AsyncGenerator[TimelordService, None]:
    service_config = config["timelord"]
    set_peer_info(service_config, peer_type=NodeType.FULL_NODE, peer_port=full_node_port)
    service_config["bluebox_mode"] = sanitizer
    service_config["fast_algorithm"] = False
    service_config["vdf_server"]["port"] = vdf_port
    service_config["start_rpc_server"] = True
    service_config["rpc_port"] = uint16(0)

    service = create_timelord_service(
        root_path,
        config,
        consensus_constants,
        connect_to_daemon=False,
    )

    async with service.manage():
        yield service
