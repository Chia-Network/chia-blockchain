import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

import pytest
import pytest_asyncio
from blspy import PrivateKey

from chia.cmds.init_funcs import create_all_ssl
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.daemon.server import WebSocketServer, daemon_launch_lock_path
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_full_node_rpc_client import SimulatorFullNodeRpcClient
from chia.simulator.socket import find_available_listen_port
from chia.simulator.ssl_certs import get_next_nodes_certs_and_keys, get_next_private_ca_cert_and_key
from chia.simulator.start_simulator import async_main as start_simulator_main
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import create_default_chia_config, load_config, save_config
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32
from chia.util.keychain import Keychain
from chia.util.lock import Lockfile
from chia.wallet.derive_keys import master_sk_to_wallet_sk


def mnemonic_fingerprint() -> Tuple[str, int]:
    mnemonic = (
        "today grape album ticket joy idle supreme sausage "
        "oppose voice angle roast you oven betray exact "
        "memory riot escape high dragon knock food blade"
    )
    # add key to keychain
    passphrase = ""
    sk = Keychain().add_private_key(mnemonic, passphrase)
    fingerprint = sk.get_g1().get_fingerprint()
    return mnemonic, fingerprint


def get_puzzle_hash_from_key(fingerprint: int, key_id: int = 1) -> bytes32:
    priv_key_and_entropy = Keychain().get_private_key_by_fingerprint(fingerprint)
    if priv_key_and_entropy is None:
        raise Exception("Fingerprint not found")
    private_key = priv_key_and_entropy[0]
    sk_for_wallet_id: PrivateKey = master_sk_to_wallet_sk(private_key, uint32(key_id))
    puzzle_hash: bytes32 = create_puzzlehash_for_pk(sk_for_wallet_id.get_g1())
    return puzzle_hash


def create_config(chia_root: Path, fingerprint: int) -> Dict[str, Any]:
    # create chia directories
    create_default_chia_config(chia_root)
    create_all_ssl(
        chia_root,
        private_ca_crt_and_key=get_next_private_ca_cert_and_key(),
        node_certs_and_keys=get_next_nodes_certs_and_keys(),
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
    config["simulator"]["farming_address"] = encode_puzzle_hash(get_puzzle_hash_from_key(fingerprint), "txch")
    config["simulator"]["plot_directory"] = "test-simulator/plots"
    # save config
    save_config(chia_root, "config.yaml", config)
    return config


async def start_simulator(chia_root: Path, automated_testing: bool = False) -> AsyncGenerator[FullNodeSimulator, None]:
    sys.argv = [sys.argv[0]]  # clear sys.argv to avoid issues with config.yaml
    service = await start_simulator_main(True, automated_testing, root_path=chia_root)
    await service.start()

    yield service._api

    service.stop()
    await service.wait_closed()


async def get_num_coins_for_ph(simulator_client: SimulatorFullNodeRpcClient, ph: bytes32) -> int:
    return len(await simulator_client.get_coin_records_by_puzzle_hash(ph))


class TestStartSimulator:
    """
    These tests are designed to test the user facing functionality of the simulator.
    """

    @pytest_asyncio.fixture(scope="function")
    async def get_user_simulator(
        self, automated_testing: bool = False, chia_root: Optional[Path] = None, config: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[Tuple[FullNodeSimulator, Path, Dict[str, Any], str, int], None]:
        # Create and setup temporary chia directories.
        if chia_root is None:
            chia_root = Path(tempfile.TemporaryDirectory().name)
        mnemonic, fingerprint = mnemonic_fingerprint()
        if config is None:
            config = create_config(chia_root, fingerprint)
        crt_path = chia_root / config["daemon_ssl"]["private_crt"]
        key_path = chia_root / config["daemon_ssl"]["private_key"]
        ca_crt_path = chia_root / config["private_ssl_ca"]["crt"]
        ca_key_path = chia_root / config["private_ssl_ca"]["key"]
        with Lockfile.create(daemon_launch_lock_path(chia_root)):
            shutdown_event = asyncio.Event()
            ws_server = WebSocketServer(chia_root, ca_crt_path, ca_key_path, crt_path, key_path, shutdown_event)
            await ws_server.start()  # type: ignore[no-untyped-call]

            async for simulator in start_simulator(chia_root, automated_testing):
                yield simulator, chia_root, config, mnemonic, fingerprint

            await ws_server.stop()

    @pytest.mark.asyncio
    async def test_start_simulator(
        self, get_user_simulator: Tuple[FullNodeSimulator, Path, Dict[str, Any], str, int]
    ) -> None:
        simulator, root_path, config, mnemonic, fingerprint = get_user_simulator
        ph_1 = get_puzzle_hash_from_key(fingerprint, key_id=1)
        ph_2 = get_puzzle_hash_from_key(fingerprint, key_id=2)
        dummy_hash = std_hash(b"test")
        num_blocks = 2
        # connect to rpc
        rpc_port = config["full_node"]["rpc_port"]
        simulator_rpc_client = await SimulatorFullNodeRpcClient.create(
            config["self_hostname"], uint16(rpc_port), root_path, config
        )
        # test auto_farm logic
        assert await simulator_rpc_client.get_auto_farming()
        await time_out_assert(10, simulator_rpc_client.set_auto_farming, False, False)
        await simulator.autofarm_transaction(dummy_hash)  # this should do nothing
        await asyncio.sleep(3)  # wait for block to be processed
        assert len(await simulator.get_all_full_blocks()) == 0

        # now check if auto_farm is working
        await time_out_assert(10, simulator_rpc_client.set_auto_farming, True, True)
        for i in range(num_blocks):
            await simulator.autofarm_transaction(dummy_hash)
        await time_out_assert(10, simulator.full_node.blockchain.get_peak_height, 2)
        # check if reward was sent to correct target
        await time_out_assert(10, get_num_coins_for_ph, 2, simulator_rpc_client, ph_1)
        # test both block RPC's
        await simulator_rpc_client.farm_block(ph_2)
        new_height = await simulator_rpc_client.farm_block(ph_2, guarantee_tx_block=True)
        # check if farming reward was received correctly & if block was created
        await time_out_assert(10, simulator.full_node.blockchain.get_peak_height, new_height)
        await time_out_assert(10, get_num_coins_for_ph, 2, simulator_rpc_client, ph_2)
        # test balance rpc
        ph_amount = await simulator_rpc_client.get_all_puzzle_hashes()
        assert ph_amount[ph_2][0] == 2000000000000
        assert ph_amount[ph_2][1] == 2
        # test all coins rpc.
        coin_records = await simulator_rpc_client.get_all_coins()
        ph_2_total = 0
        ph_1_total = 0
        for cr in coin_records:
            if cr.coin.puzzle_hash == ph_2:
                ph_2_total += cr.coin.amount
            elif cr.coin.puzzle_hash == ph_1:
                ph_1_total += cr.coin.amount
        assert ph_2_total == 2000000000000 and ph_1_total == 4000000000000
        # block rpc tests.
        # test reorg
        old_blocks = await simulator_rpc_client.get_all_blocks()  # len should be 4
        await simulator_rpc_client.reorg_blocks(2)  # fork point 2 blocks, now height is 5
        await time_out_assert(10, simulator.full_node.blockchain.get_peak_height, 5)
        # now validate that the blocks don't match
        assert (await simulator.get_all_full_blocks())[0:4] != old_blocks
        # test block deletion
        await simulator_rpc_client.revert_blocks(3)  # height 5 to 2
        await time_out_assert(10, simulator.full_node.blockchain.get_peak_height, 2)
        await time_out_assert(10, get_num_coins_for_ph, 2, simulator_rpc_client, ph_1)
        # close up
        simulator_rpc_client.close()
        await simulator_rpc_client.await_closed()
