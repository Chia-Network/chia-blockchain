from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, Optional

from chia_rs import PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.daemon.server import WebSocketServer, daemon_launch_lock_path
from chia.server.signal_handlers import SignalHandlers
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.socket import find_available_listen_port
from chia.simulator.ssl_certs import (
    SSLTestCACertAndPrivateKey,
    SSLTestCollateralWrapper,
    SSLTestNodeCertsAndKeys,
    get_next_nodes_certs_and_keys,
    get_next_private_ca_cert_and_key,
)
from chia.simulator.start_simulator import async_main as start_simulator_main
from chia.ssl.create_ssl import create_all_ssl
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import create_default_chia_config, load_config, save_config
from chia.util.errors import KeychainFingerprintExists
from chia.util.keychain import Keychain
from chia.util.lock import Lockfile
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_hash_for_pk

"""
These functions are used to test the simulator.
"""


def mnemonic_fingerprint(keychain: Keychain) -> tuple[str, int]:
    mnemonic = (
        "today grape album ticket joy idle supreme sausage "
        "oppose voice angle roast you oven betray exact "
        "memory riot escape high dragon knock food blade"
    )
    # add key to keychain
    try:
        sk = keychain.add_key(mnemonic)
    except KeychainFingerprintExists:
        pass
    fingerprint = sk.get_g1().get_fingerprint()
    return mnemonic, fingerprint


def get_puzzle_hash_from_key(keychain: Keychain, fingerprint: int, key_id: int = 1) -> bytes32:
    priv_key_and_entropy = keychain.get_private_key_by_fingerprint(fingerprint)
    if priv_key_and_entropy is None:
        raise Exception("Fingerprint not found")
    private_key = priv_key_and_entropy[0]
    sk_for_wallet_id: PrivateKey = master_sk_to_wallet_sk(private_key, uint32(key_id))
    puzzle_hash: bytes32 = puzzle_hash_for_pk(sk_for_wallet_id.get_g1())
    return puzzle_hash


def create_config(
    chia_root: Path,
    fingerprint: int,
    private_ca_crt_and_key: tuple[bytes, bytes],
    node_certs_and_keys: dict[str, dict[str, dict[str, bytes]]],
    keychain: Keychain,
) -> dict[str, Any]:
    # create chia directories
    create_default_chia_config(chia_root)
    create_all_ssl(
        chia_root,
        private_ca_crt_and_key=private_ca_crt_and_key,
        node_certs_and_keys=node_certs_and_keys,
    )
    # load config
    config = load_config(chia_root, "config.yaml")
    config["full_node"]["send_uncompact_interval"] = 0
    config["full_node"]["target_uncompact_proofs"] = 30
    config["full_node"]["peer_connect_interval"] = 50
    config["full_node"]["sanitize_weight_proof_only"] = False
    config["full_node"]["introducer_peer"] = None
    config["full_node"]["dns_servers"] = []
    config["logging"]["log_stdout"] = True
    config["selected_network"] = "testnet0"
    for service in [
        "harvester",
        "farmer",
        "full_node",
        "wallet",
        "introducer",
        "timelord",
        "pool",
        "simulator",
    ]:
        config[service]["selected_network"] = "testnet0"
    config["daemon_port"] = find_available_listen_port("BlockTools daemon")
    config["full_node"]["port"] = 0
    config["full_node"]["rpc_port"] = find_available_listen_port("Node RPC")
    # simulator overrides
    config["simulator"]["key_fingerprint"] = fingerprint
    config["simulator"]["farming_address"] = encode_puzzle_hash(get_puzzle_hash_from_key(keychain, fingerprint), "txch")
    config["simulator"]["plot_directory"] = "test-simulator/plots"
    # save config
    save_config(chia_root, "config.yaml", config)
    return config


async def start_simulator(chia_root: Path, automated_testing: bool = False) -> AsyncGenerator[FullNodeSimulator, None]:
    sys.argv = [sys.argv[0]]  # clear sys.argv to avoid issues with config.yaml
    started_simulator = await start_simulator_main(True, automated_testing, root_path=chia_root)
    service = started_simulator.service

    async with service.manage():
        yield service._api


async def get_full_chia_simulator(
    chia_root: Path,
    keychain: Optional[Keychain] = None,
    automated_testing: bool = False,
    config: Optional[dict[str, Any]] = None,
) -> AsyncGenerator[tuple[FullNodeSimulator, Path, dict[str, Any], str, int, Keychain], None]:
    """
    A chia root Path is required.
    The chia root Path can be a temporary directory (tempfile.TemporaryDirectory)
    Passing in a Keychain prevents test keys from being added to the default key location
    This test can either be run in automated mode or not, which determines which mode block tools run in.
    This test is fully interdependent and can be used without the rest of the chia test suite.
    Please refer to the documentation for more information.
    """

    if keychain is None:
        keychain = Keychain()

    with Lockfile.create(daemon_launch_lock_path(chia_root)):
        mnemonic, fingerprint = mnemonic_fingerprint(keychain)

        ssl_ca_cert_and_key_wrapper: SSLTestCollateralWrapper[SSLTestCACertAndPrivateKey] = (
            get_next_private_ca_cert_and_key()
        )
        ssl_nodes_certs_and_keys_wrapper: SSLTestCollateralWrapper[SSLTestNodeCertsAndKeys] = (
            get_next_nodes_certs_and_keys()
        )
        if config is None:
            config = create_config(
                chia_root,
                fingerprint,
                ssl_ca_cert_and_key_wrapper.collateral.cert_and_key,
                ssl_nodes_certs_and_keys_wrapper.collateral.certs_and_keys,
                keychain,
            )
        crt_path = chia_root / config["daemon_ssl"]["private_crt"]
        key_path = chia_root / config["daemon_ssl"]["private_key"]
        ca_crt_path = chia_root / config["private_ssl_ca"]["crt"]
        ca_key_path = chia_root / config["private_ssl_ca"]["key"]

        ws_server = WebSocketServer(chia_root, ca_crt_path, ca_key_path, crt_path, key_path)
        async with SignalHandlers.manage() as signal_handlers:
            await ws_server.setup_process_global_state(signal_handlers=signal_handlers)
            async with ws_server.run():
                async for simulator in start_simulator(chia_root, automated_testing):
                    yield simulator, chia_root, config, mnemonic, fingerprint, keychain
