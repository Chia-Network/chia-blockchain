from __future__ import annotations

import asyncio
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
import enum
=======
>>>>>>> ee8e424 (build(deps): bump pytest-rerunfailures from 16.1 to 16.2)
=======
>>>>>>> d747b89 (build(deps): bump ruff from 0.15.8 to 0.15.13)
=======
>>>>>>> 8e73dd3 (build(deps): bump boto3 from 1.43.8 to 1.43.11)
=======
>>>>>>> 20feb6e (build(deps): bump lxml from 6.1.0 to 6.1.1)
import logging
import sys
import time
import types
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from chia_rs import CoinState, FullBlock, G1Element, PrivateKey
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64, uint128

from chia._tests.conftest import ConsensusMode
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
from chia._tests.connection_utils import add_dummy_connection_wsc
=======
>>>>>>> ee8e424 (build(deps): bump pytest-rerunfailures from 16.1 to 16.2)
=======
>>>>>>> d747b89 (build(deps): bump ruff from 0.15.8 to 0.15.13)
=======
>>>>>>> 8e73dd3 (build(deps): bump boto3 from 1.43.8 to 1.43.11)
=======
>>>>>>> 20feb6e (build(deps): bump lxml from 6.1.0 to 6.1.1)
from chia._tests.environments.wallet import WalletTestFramework
from chia._tests.util.misc import CoinGenerator, patch_request_handler
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.blockchain import AddBlockResult
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
from chia.consensus.generator_tools import get_block_header
from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import wallet_protocol
from chia.protocols.outbound_message import Message, NodeType, make_msg
=======
from chia.protocols import wallet_protocol
from chia.protocols.outbound_message import Message, make_msg
>>>>>>> ee8e424 (build(deps): bump pytest-rerunfailures from 16.1 to 16.2)
=======
from chia.protocols import wallet_protocol
from chia.protocols.outbound_message import Message, make_msg
>>>>>>> d747b89 (build(deps): bump ruff from 0.15.8 to 0.15.13)
=======
from chia.protocols import wallet_protocol
from chia.protocols.outbound_message import Message, make_msg
>>>>>>> 8e73dd3 (build(deps): bump boto3 from 1.43.8 to 1.43.11)
=======
from chia.protocols import wallet_protocol
from chia.protocols.outbound_message import Message, make_msg
>>>>>>> 20feb6e (build(deps): bump lxml from 6.1.0 to 6.1.1)
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.api_protocol import Self
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.add_blocks_in_batches import add_blocks_in_batches
from chia.simulator.block_tools import test_constants
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
=======
>>>>>>> ee8e424 (build(deps): bump pytest-rerunfailures from 16.1 to 16.2)
=======
>>>>>>> d747b89 (build(deps): bump ruff from 0.15.8 to 0.15.13)
=======
>>>>>>> 8e73dd3 (build(deps): bump boto3 from 1.43.8 to 1.43.11)
=======
>>>>>>> 20feb6e (build(deps): bump lxml from 6.1.0 to 6.1.1)
from chia.types.blockchain_format.coin import Coin
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.config import load_config
from chia.util.errors import Err
from chia.util.hash import std_hash
from chia.util.keychain import Keychain, KeyData, generate_mnemonic
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
from chia.wallet.util.peer_request_cache import PeerRequestCache
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_sync_utils import PeerRequestException
from chia.wallet.wallet_node import Balance, WalletNode, request_and_validate_header_block
=======
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_sync_utils import PeerRequestException
from chia.wallet.wallet_node import Balance, WalletNode
>>>>>>> ee8e424 (build(deps): bump pytest-rerunfailures from 16.1 to 16.2)
=======
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_sync_utils import PeerRequestException
from chia.wallet.wallet_node import Balance, WalletNode
>>>>>>> d747b89 (build(deps): bump ruff from 0.15.8 to 0.15.13)
=======
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_sync_utils import PeerRequestException
from chia.wallet.wallet_node import Balance, WalletNode
>>>>>>> 8e73dd3 (build(deps): bump boto3 from 1.43.8 to 1.43.11)
=======
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_sync_utils import PeerRequestException
from chia.wallet.wallet_node import Balance, WalletNode
>>>>>>> 20feb6e (build(deps): bump lxml from 6.1.0 to 6.1.1)


@pytest.mark.anyio
async def test_get_private_key(root_path_populated_with_config: Path, get_temp_keyring: Keychain) -> None:
    root_path = root_path_populated_with_config
    keychain = get_temp_keyring
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants, keychain)
    sk = keychain.add_key(generate_mnemonic())
    fingerprint = sk.get_g1().get_fingerprint()

    key = await node.get_key(fingerprint)

    assert key is not None
    assert isinstance(key, PrivateKey)
    assert key.get_g1().get_fingerprint() == fingerprint


@pytest.mark.anyio
async def test_get_private_key_default_key(root_path_populated_with_config: Path, get_temp_keyring: Keychain) -> None:
    root_path = root_path_populated_with_config
    keychain = get_temp_keyring
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants, keychain)
    sk = keychain.add_key(generate_mnemonic())
    fingerprint = sk.get_g1().get_fingerprint()

    # Add a couple more keys
    keychain.add_key(generate_mnemonic())
    keychain.add_key(generate_mnemonic())

    # When no fingerprint is provided, we should get the default (first) key
    key = await node.get_key(None)

    assert key is not None
    assert isinstance(key, PrivateKey)
    assert key.get_g1().get_fingerprint() == fingerprint


@pytest.mark.anyio
@pytest.mark.parametrize("fingerprint", [None, 1234567890])
async def test_get_private_key_missing_key(
    root_path_populated_with_config: Path, get_temp_keyring: Keychain, fingerprint: int | None
) -> None:
    root_path = root_path_populated_with_config
    keychain = get_temp_keyring  # empty keyring
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants, keychain)

    # Keyring is empty, so requesting a key by fingerprint or None should return None
    key = await node.get_key(fingerprint)

    assert key is None


@pytest.mark.anyio
async def test_get_private_key_missing_key_use_default(
    root_path_populated_with_config: Path, get_temp_keyring: Keychain
) -> None:
    root_path = root_path_populated_with_config
    keychain = get_temp_keyring
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants, keychain)
    sk = keychain.add_key(generate_mnemonic())
    fingerprint = sk.get_g1().get_fingerprint()

    # Stupid sanity check that the fingerprint we're going to use isn't actually in the keychain
    assert fingerprint != 1234567890

    # When fingerprint is provided and the key is missing, we should get the default (first) key
    key = await node.get_key(1234567890)

    assert key is not None
    assert isinstance(key, PrivateKey)
    assert key.get_g1().get_fingerprint() == fingerprint


@pytest.mark.anyio
async def test_get_public_key(root_path_populated_with_config: Path, get_temp_keyring: Keychain) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring
    config: dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants, keychain)
    pk: G1Element = keychain.add_key(
        "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
        None,
        private=False,
    )
    fingerprint: int = pk.get_fingerprint()

    key = await node.get_key(fingerprint, private=False)

    assert key is not None
    assert isinstance(key, G1Element)
    assert key.get_fingerprint() == fingerprint


@pytest.mark.anyio
async def test_get_public_key_default_key(root_path_populated_with_config: Path, get_temp_keyring: Keychain) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring
    config: dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants, keychain)
    pk: G1Element = keychain.add_key(
        "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
        None,
        private=False,
    )
    fingerprint: int = pk.get_fingerprint()

    # Add a couple more keys
    keychain.add_key(
        "83062a1b26d27820600eac4e31c1a890a6ba026b28bb96bb66454e9ce1033f4cba8824259dc17dc3b643ab1003e6b961",
        None,
        private=False,
    )
    keychain.add_key(
        "a272d5aaa6046e64bd7fd69bae288b9f9e5622c13058ec7d1b85e3d4d1acfa5d63d6542336c7b24d2fceab991919e989",
        None,
        private=False,
    )

    # When no fingerprint is provided, we should get the default (first) key
    key = await node.get_key(None, private=False)

    assert key is not None
    assert isinstance(key, G1Element)
    assert key.get_fingerprint() == fingerprint


@pytest.mark.anyio
@pytest.mark.parametrize("fingerprint", [None, 1234567890])
async def test_get_public_key_missing_key(
    root_path_populated_with_config: Path, get_temp_keyring: Keychain, fingerprint: int | None
) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring  # empty keyring
    config: dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants, keychain)

    # Keyring is empty, so requesting a key by fingerprint or None should return None
    key = await node.get_key(fingerprint, private=False)

    assert key is None


@pytest.mark.anyio
async def test_get_public_key_missing_key_use_default(
    root_path_populated_with_config: Path, get_temp_keyring: Keychain
) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring
    config: dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants, keychain)
    pk: G1Element = keychain.add_key(
        "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
        None,
        private=False,
    )
    fingerprint: int = pk.get_fingerprint()

    # Stupid sanity check that the fingerprint we're going to use isn't actually in the keychain
    assert fingerprint != 1234567890

    # When fingerprint is provided and the key is missing, we should get the default (first) key
    key = await node.get_key(1234567890, private=False)

    assert key is not None
    assert isinstance(key, G1Element)
    assert key.get_fingerprint() == fingerprint


def test_log_in(root_path_populated_with_config: Path, get_temp_keyring: Keychain) -> None:
    root_path = root_path_populated_with_config
    keychain = get_temp_keyring
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    sk = keychain.add_key(generate_mnemonic())
    fingerprint = sk.get_g1().get_fingerprint()

    node.log_in(fingerprint)

    assert node.logged_in is True
    assert node.logged_in_fingerprint == fingerprint
    assert node.get_last_used_fingerprint() == fingerprint


def test_log_in_failure_to_write_last_used_fingerprint(
    root_path_populated_with_config: Path, get_temp_keyring: Keychain, monkeypatch: pytest.MonkeyPatch
) -> None:
    called_update_last_used_fingerprint: bool = False

    def patched_update_last_used_fingerprint(self: Self) -> None:
        nonlocal called_update_last_used_fingerprint
        called_update_last_used_fingerprint = True
        raise Exception("Generic write failure")

    with monkeypatch.context() as m:
        m.setattr(WalletNode, "update_last_used_fingerprint", patched_update_last_used_fingerprint)
        root_path = root_path_populated_with_config
        keychain = get_temp_keyring
        config = load_config(root_path, "config.yaml", "wallet")
        node = WalletNode(config, root_path, test_constants)
        sk = keychain.add_key(generate_mnemonic())
        fingerprint = sk.get_g1().get_fingerprint()

        # Expect log_in to succeed, even though we can't write the last used fingerprint
        node.log_in(fingerprint)

        assert node.logged_in is True
        assert node.logged_in_fingerprint == fingerprint
        assert node.get_last_used_fingerprint() is None
        assert called_update_last_used_fingerprint is True


def test_log_out(root_path_populated_with_config: Path, get_temp_keyring: Keychain) -> None:
    root_path = root_path_populated_with_config
    keychain = get_temp_keyring
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    sk = keychain.add_key(generate_mnemonic())
    fingerprint = sk.get_g1().get_fingerprint()

    node.log_in(fingerprint)

    assert node.logged_in is True
    assert node.logged_in_fingerprint == fingerprint
    assert node.get_last_used_fingerprint() == fingerprint

    node.log_out()

    assert node.logged_in is False
    assert node.logged_in_fingerprint is None
    assert node.get_last_used_fingerprint() == fingerprint


def test_get_last_used_fingerprint_path(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    path = node.get_last_used_fingerprint_path()

    assert path == root_path / "wallet" / "db" / "last_used_fingerprint"


def test_get_last_used_fingerprint(root_path_populated_with_config: Path) -> None:
    path = root_path_populated_with_config / "wallet" / "db" / "last_used_fingerprint"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1234567890")

    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    last_used_fingerprint = node.get_last_used_fingerprint()

    assert last_used_fingerprint == 1234567890


def test_get_last_used_fingerprint_file_doesnt_exist(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    last_used_fingerprint = node.get_last_used_fingerprint()

    assert last_used_fingerprint is None


def test_get_last_used_fingerprint_file_cant_read_unix(root_path_populated_with_config: Path) -> None:
    if sys.platform in {"win32", "cygwin"}:
        pytest.skip("Setting UNIX file permissions doesn't apply to Windows")

    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    path = node.get_last_used_fingerprint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1234567890")

    assert node.get_last_used_fingerprint() == 1234567890

    # Make the file unreadable
    path.chmod(0o000)

    last_used_fingerprint = node.get_last_used_fingerprint()

    assert last_used_fingerprint is None

    # Verify that the file is unreadable
    with pytest.raises(PermissionError):
        path.read_text()

    # Calling get_last_used_fingerprint() should not throw an exception
    assert node.get_last_used_fingerprint() is None

    path.chmod(0o600)


def test_get_last_used_fingerprint_file_cant_read_win32(
    root_path_populated_with_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform not in {"win32", "cygwin"}:
        pytest.skip("Windows-specific test")

    called_read_text = False

    def patched_pathlib_path_read_text(self: Self) -> str:
        nonlocal called_read_text
        called_read_text = True
        raise PermissionError("Permission denied")

    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    path = node.get_last_used_fingerprint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1234567890")

    assert node.get_last_used_fingerprint() == 1234567890

    # Make the file unreadable. Doing this with pywin32 is more trouble than it's worth. All we care about is that
    # get_last_used_fingerprint doesn't throw an exception.
    with monkeypatch.context() as m:
        from pathlib import WindowsPath

        m.setattr(WindowsPath, "read_text", patched_pathlib_path_read_text)

        # Calling get_last_used_fingerprint() should not throw an exception
        last_used_fingerprint: int | None = node.get_last_used_fingerprint()

        # Verify that the file is unreadable
        assert called_read_text is True
        assert last_used_fingerprint is None


def test_get_last_used_fingerprint_file_with_whitespace(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    path = node.get_last_used_fingerprint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\r\n \t1234567890\r\n\n")

    assert node.get_last_used_fingerprint() == 1234567890


def test_update_last_used_fingerprint_missing_fingerprint(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    node.logged_in_fingerprint = None

    with pytest.raises(AssertionError):
        node.update_last_used_fingerprint()


def test_update_last_used_fingerprint_create_intermediate_dirs(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    node.logged_in_fingerprint = 9876543210
    path = node.get_last_used_fingerprint_path()

    assert path.parent.exists() is False

    node.update_last_used_fingerprint()

    assert path.parent.exists() is True


def test_update_last_used_fingerprint(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml", "wallet")
    node = WalletNode(config, root_path, test_constants)
    node.logged_in_fingerprint = 9876543210
    path = node.get_last_used_fingerprint_path()

    node.update_last_used_fingerprint()

    assert path.exists() is True
    assert path.read_text() == "9876543210"


@pytest.mark.parametrize("testing", [True, False])
@pytest.mark.parametrize("offset", [0, 550, 650])
def test_timestamp_in_sync(root_path_populated_with_config: Path, testing: bool, offset: int) -> None:
    root_path = root_path_populated_with_config
    config = load_config(root_path, "config.yaml", "wallet")
    wallet_node = WalletNode(config, root_path, test_constants)
    now = time.time()
    wallet_node.config["testing"] = testing

    expected = testing or offset < 600
    assert wallet_node.is_timestamp_in_sync(uint64(now - offset)) == expected


@pytest.mark.anyio
@pytest.mark.standard_block_tools
# todo_v2_plots
# NOTE: HARD_FORK_3_0 can fail this log assertion because height 1-2 are non-tx,
# so earlier timestamp lookups backtrack to height 0 and cache _timestamps[0].
# clear_after_height(0) keeps height 0, so get_timestamp(1) returns early
# this test expects a certine chain state
@pytest.mark.limit_consensus_modes(
    allowed=[ConsensusMode.PLAIN, ConsensusMode.HARD_FORK_2_0], reason="doesn't work for 3.0 hard fork yet"
)
async def test_get_timestamp_for_height_from_peer(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str, caplog: pytest.LogCaptureFixture
) -> None:
    [full_node_api], [(wallet_node, wallet_server)], _ = simulator_and_wallet

    async def get_timestamp(height: int) -> uint64 | None:
        return await wallet_node.get_timestamp_for_height_from_peer(uint32(height), full_node_peer)

    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    wallet = wallet_node.wallet_state_manager.main_wallet
    await full_node_api.farm_blocks_to_wallet(2, wallet)
    full_node_peer = next(iter(wallet_server.all_connections.values()))
    # There should be no timestamp available for height 10
    assert await get_timestamp(10) is None
    # The timestamp at peak height should match the one from the full node block_store.
    peak = await wallet_node.wallet_state_manager.blockchain.get_peak_block()
    assert peak is not None
    timestamp_at_peak = await get_timestamp(peak.height)
    block_at_peak = (await full_node_api.full_node.block_store.get_full_blocks_at([peak.height]))[0]
    assert block_at_peak.foliage_transaction_block is not None
    assert timestamp_at_peak == block_at_peak.foliage_transaction_block.timestamp
    # Clear the cache and add the peak back with a modified timestamp
    cache = wallet_node.get_cache_for_peer(full_node_peer)
    cache.clear_after_height(0)
    modified_foliage_transaction_block = block_at_peak.foliage_transaction_block.replace(
        timestamp=uint64(timestamp_at_peak + 1)
    )
    modified_peak = peak.replace(foliage_transaction_block=modified_foliage_transaction_block)
    cache.add_to_blocks(modified_peak)
    # Now the call should make use of the cached, modified block
    assert await get_timestamp(peak.height) == timestamp_at_peak + 1
    # After the clearing the cache it should fetch the actual timestamp again
    cache.clear_after_height(0)
    assert await get_timestamp(peak.height) == timestamp_at_peak
    # Test block cache usage
    cache.clear_after_height(0)
    with caplog.at_level(logging.DEBUG):
        await get_timestamp(1)
    block_1 = cache.get_block(uint32(1))
    assert block_1 is not None
    assert f"get_timestamp_for_height_from_peer cache miss for height {1}" in caplog.text
    assert f"get_timestamp_for_height_from_peer add to cache for height {1}" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        await get_timestamp(1)
    assert f"get_timestamp_for_height_from_peer use cached block for height {0}" not in caplog.text
    assert f"get_timestamp_for_height_from_peer use cached block for height {1}" in caplog.text


@pytest.mark.anyio
async def test_get_timestamp_for_height_from_peer_backtracks_to_tx_block_deterministic(
    root_path_populated_with_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import chia.wallet.wallet_node as wallet_node_module

    config = load_config(root_path_populated_with_config, "config.yaml", "wallet")
    wallet_node = WalletNode(config, root_path_populated_with_config, test_constants)
    peer = MagicMock()
    peer.peer_node_id = bytes32(b"\xab" * 32)
    requested_ranges: list[tuple[int, int]] = []

    def make_header_block(height: int, *, is_transaction_block: bool, timestamp: int | None = None) -> Any:
        block = MagicMock()
        block.height = uint32(height)
        block.is_transaction_block = is_transaction_block
        if is_transaction_block:
            foliage_tx = MagicMock()
            foliage_tx.timestamp = uint64(timestamp if timestamp is not None else 0)
            block.foliage_transaction_block = foliage_tx
        else:
            block.foliage_transaction_block = None
        return block

    block_at_height_1 = make_header_block(1, is_transaction_block=False)
    block_at_height_0 = make_header_block(0, is_transaction_block=True, timestamp=123456789)

    async def fake_request_header_blocks(_peer: Any, start_height: uint32, end_height: uint32) -> list[Any]:
        requested_ranges.append((int(start_height), int(end_height)))
        if int(start_height) == 1:
            return [block_at_height_1]
        return [block_at_height_0]

    monkeypatch.setattr(wallet_node_module, "request_header_blocks", fake_request_header_blocks)

    timestamp = await wallet_node.get_timestamp_for_height_from_peer(uint32(1), peer)
    assert timestamp == uint64(123456789)
    assert requested_ranges == [(1, 1), (0, 0)]
    cache = wallet_node.get_cache_for_peer(peer)
    assert cache.get_block(uint32(1)) is block_at_height_1
    assert cache.get_height_timestamp(uint32(0)) == uint64(123456789)


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.anyio
async def test_unique_puzzle_hash_subscriptions(simulator_and_wallet: OldSimulatorsAndWallets) -> None:
    _, [(node, _)], _ = simulator_and_wallet
    puzzle_hashes = await node.get_puzzle_hashes_to_subscribe()
    assert len(puzzle_hashes) > 1
    assert len(set(puzzle_hashes)) == len(puzzle_hashes)


def make_backtrack_test_node(height: int, *, has_peak: bool = False) -> WalletNode:
    node = WalletNode(
        config={"trusted_peers": {}},
        root_path=Path(".chia_wallet_node_tests_root"),
        constants=test_constants,
    )
    mock_chain = MagicMock()
    mock_chain.contains_block = MagicMock(return_value=False)
    if has_peak:
        peak_block = MagicMock()
        peak_block.height = uint32(height)
        peak_block.weight = uint128(height * 1000)
        mock_chain.get_peak_block = AsyncMock(return_value=peak_block)
    else:
        mock_chain.get_peak_block = AsyncMock(return_value=None)
    mock_chain.get_finished_sync_up_to = AsyncMock(return_value=uint32(height))
    mock_chain.add_block = AsyncMock(return_value=(AddBlockResult.INVALID_BLOCK, "invalid test block"))
    mock_wsm = MagicMock()
    mock_wsm.blockchain = mock_chain
    mock_wsm.lock = asyncio.Lock()
    node._wallet_state_manager = mock_wsm
    setattr(node, "update_ui", AsyncMock())
    return node


def _test_hash_for_height(h: int) -> bytes32:
    return bytes32(h.to_bytes(32, "big"))


def make_backtrack_test_peer() -> Any:
    async def mock_call_api(_api_func: object, request: Any, **_kwargs: object) -> object:
        h = int(request.height)
        response = MagicMock(spec=wallet_protocol.RespondBlockHeader)
        hb = MagicMock()
        hb.height = uint32(h)
        hb.header_hash = _test_hash_for_height(h)
        hb.prev_header_hash = _test_hash_for_height(h - 1) if h > 0 else bytes32(b"\xff" * 32)
        hb.weight = uint128(h * 1000)
        hb.foliage_transaction_block = None
        response.header_block = hb
        return response

    peer = MagicMock()
    peer.call_api = AsyncMock(side_effect=mock_call_api)
    peer.close = AsyncMock()
    peer.peer_info = MagicMock()
    peer.peer_info.host = "attacker.example"
    return peer


def make_header(height: int, prev_hash: bytes32, header_hash: bytes32) -> Any:
    hb = MagicMock()
    hb.height = uint32(height)
    hb.prev_header_hash = prev_hash
    hb.header_hash = header_hash
    hb.weight = uint128(height * 1000)
    return hb


def patch_rollback(node: WalletNode) -> list[int]:
    calls: list[int] = []

    async def _capture(fork_height: int, cache: Any | None = None) -> None:
        calls.append(int(fork_height))

    setattr(node, "perform_atomic_rollback", _capture)
    return calls


@pytest.mark.anyio
@pytest.mark.parametrize(
    "node_height",
    [500, 750, 1500],
    ids=["just_over_threshold", "above_threshold", "well_above_threshold"],
)
async def test_wallet_short_sync_backtrack_cap_exceeded_returns_none(node_height: int) -> None:
    node = make_backtrack_test_node(height=node_height, has_peak=True)
    peer = make_backtrack_test_peer()
    rollback_calls = patch_rollback(node)
    header = make_header(node_height + 1, _test_hash_for_height(node_height), _test_hash_for_height(node_height + 1))

    result = await node.wallet_short_sync_backtrack(header, peer)
    assert result is None
    assert rollback_calls == []
    assert cast(Any, node.wallet_state_manager.blockchain.add_block).await_count == 0
    peer.close.assert_not_awaited()


@pytest.mark.anyio
async def test_wallet_short_sync_backtrack_stops_at_threshold() -> None:
    node = make_backtrack_test_node(height=500, has_peak=True)
    peer = make_backtrack_test_peer()
    header = make_header(501, _test_hash_for_height(500), _test_hash_for_height(501))
    await node.wallet_short_sync_backtrack(header, peer)
    assert peer.call_api.await_count == node.LONG_SYNC_THRESHOLD
    peer.close.assert_not_awaited()


@pytest.mark.anyio
async def test_wallet_short_sync_backtrack_initial_sync_no_cap() -> None:
    """Initial sync (peak is None) should backtrack to genesis without hitting the cap,
    since the chain is bounded by WEIGHT_PROOF_RECENT_BLOCKS and there is no existing
    state to protect."""
    node = make_backtrack_test_node(height=400, has_peak=False)
    rollback_calls = patch_rollback(node)
    setattr(node.wallet_state_manager.blockchain, "add_block", AsyncMock(return_value=(AddBlockResult.NEW_PEAK, None)))

    peer = make_backtrack_test_peer()
    header = make_header(401, _test_hash_for_height(400), _test_hash_for_height(401))

    result = await node.wallet_short_sync_backtrack(header, peer)
    assert result == 0
    assert rollback_calls == []
    assert peer.call_api.await_count == 401


@pytest.mark.anyio
async def test_wallet_short_sync_backtrack_short_chain_no_cap() -> None:
    """On a short chain (height < WEIGHT_PROOF_RECENT_BLOCKS) with existing state,
    backtrack beyond LONG_SYNC_THRESHOLD succeeds without hitting the cap.
    Chain height is the natural bound."""
    node = make_backtrack_test_node(height=400, has_peak=True)
    rollback_calls = patch_rollback(node)
    setattr(node.wallet_state_manager.blockchain, "add_block", AsyncMock(return_value=(AddBlockResult.NEW_PEAK, None)))

    peer = make_backtrack_test_peer()
    header = make_header(401, _test_hash_for_height(400), _test_hash_for_height(401))

    result = await node.wallet_short_sync_backtrack(header, peer)
    assert result == 0
    assert peer.call_api.await_count == 401
    assert peer.call_api.await_count > node.LONG_SYNC_THRESHOLD
    peer.close.assert_not_awaited()
    assert rollback_calls == [0]


@pytest.mark.anyio
async def test_wallet_short_sync_backtrack_rollback_when_peak_exists_and_reaches_genesis() -> None:
    """When the wallet has existing state (peak is not None) and backtrack reaches genesis
    without finding a known block, the wallet MUST roll back to genesis (fork_height=0).
    Regression test for bugbot finding: should_skip_rollback was unconditionally True
    at genesis, skipping rollback even when stale state existed."""
    node = make_backtrack_test_node(height=100, has_peak=True)
    rollback_calls = patch_rollback(node)
    setattr(
        node.wallet_state_manager.blockchain,
        "add_block",
        AsyncMock(return_value=(AddBlockResult.NEW_PEAK, None)),
    )

    peer = make_backtrack_test_peer()
    header = make_header(101, _test_hash_for_height(100), _test_hash_for_height(101))

    result = await node.wallet_short_sync_backtrack(header, peer)
    assert result == 0
    assert rollback_calls == [0], "Should roll back to genesis when peak exists but no known blocks found"


@pytest.mark.anyio
async def test_wallet_short_sync_backtrack_shutdown_before_backtrack() -> None:
    node = make_backtrack_test_node(height=50)
    peer = make_backtrack_test_peer()
    node._shut_down = True
    setattr(node, "perform_atomic_rollback", AsyncMock())
    header = make_header(51, _test_hash_for_height(50), _test_hash_for_height(51))

    with pytest.raises(RuntimeError, match="Shutdown requested during wallet backtrack sync"):
        await node.wallet_short_sync_backtrack(header, peer)
    assert cast(Any, node.perform_atomic_rollback).await_count == 0
    assert cast(Any, node.wallet_state_manager.blockchain.add_block).await_count == 0


@pytest.mark.anyio
async def test_wallet_short_sync_backtrack_rejects_discontinuous_chain() -> None:
    node = make_backtrack_test_node(height=10)
    rollback_calls = patch_rollback(node)

    requested_heights: list[int] = []
    known_prev = bytes32(b"\x10" * 32)
    bad_prev = bytes32(b"\x11" * 32)

    def contains_block(header_hash: bytes32) -> bool:
        return header_hash == known_prev

    setattr(node.wallet_state_manager.blockchain, "contains_block", MagicMock(side_effect=contains_block))

    async def mock_call_api(_api_func: object, request: Any, **_kwargs: object) -> object:
        requested_heights.append(int(request.height))
        response = MagicMock(spec=wallet_protocol.RespondBlockHeader)
        hb = MagicMock()
        hb.height = uint32(request.height)
        hb.header_hash = bytes32(b"\x12" * 32)
        hb.prev_header_hash = known_prev
        hb.weight = uint128(request.height * 1000)
        hb.foliage_transaction_block = None
        response.header_block = hb
        return response

    peer = MagicMock()
    peer.call_api = AsyncMock(side_effect=mock_call_api)
    peer.close = AsyncMock()
    peer.peer_info = MagicMock()
    peer.peer_info.host = "attacker.example"
    header = make_header(3, bad_prev, bytes32(b"\x13" * 32))

    result = await node.wallet_short_sync_backtrack(header, peer)
    assert result is None
    assert rollback_calls == []
    assert cast(Any, node.wallet_state_manager.blockchain.add_block).await_count == 0
    assert requested_heights == [2]
    peer.close.assert_awaited_once()


@pytest.mark.anyio
async def test_wallet_short_sync_backtrack_happy_path_connected_chain() -> None:
    node = make_backtrack_test_node(height=10)
    rollback_calls = patch_rollback(node)
    setattr(node.wallet_state_manager.blockchain, "add_block", AsyncMock(return_value=(AddBlockResult.NEW_PEAK, None)))

    h2_hash = bytes32(b"\x21" * 32)
    known_prev = bytes32(b"\x22" * 32)

    def contains_block(header_hash: bytes32) -> bool:
        return header_hash == known_prev

    setattr(node.wallet_state_manager.blockchain, "contains_block", MagicMock(side_effect=contains_block))

    async def mock_call_api(_api_func: object, request: Any, **_kwargs: object) -> object:
        response = MagicMock(spec=wallet_protocol.RespondBlockHeader)
        hb = MagicMock()
        hb.height = uint32(request.height)
        hb.header_hash = h2_hash
        hb.prev_header_hash = known_prev
        hb.weight = uint128(request.height * 1000)
        hb.foliage_transaction_block = None
        response.header_block = hb
        return response

    peer = MagicMock()
    peer.call_api = AsyncMock(side_effect=mock_call_api)
    peer.peer_info = MagicMock()
    peer.peer_info.host = "good.example"
    header = make_header(3, h2_hash, bytes32(b"\x23" * 32))

    result = await node.wallet_short_sync_backtrack(header, peer)
    assert result == 1
    assert rollback_calls == [1]
    assert cast(Any, node.wallet_state_manager.blockchain.add_block).await_count == 2


@pytest.mark.anyio
async def test_wallet_short_sync_backtrack_genesis_unanchored_skips_rollback() -> None:
    node = make_backtrack_test_node(height=20)
    rollback_calls = patch_rollback(node)
    setattr(node.wallet_state_manager.blockchain, "add_block", AsyncMock(return_value=(AddBlockResult.NEW_PEAK, None)))
    setattr(node.wallet_state_manager.blockchain, "contains_block", MagicMock(return_value=False))

    h1_hash = bytes32(b"\x31" * 32)
    h0_hash = bytes32(b"\x32" * 32)
    unknown_prev = bytes32(b"\x33" * 32)

    async def mock_call_api(_api_func: object, request: Any, **_kwargs: object) -> object:
        response = MagicMock(spec=wallet_protocol.RespondBlockHeader)
        hb = MagicMock()
        hb.height = uint32(request.height)
        hb.weight = uint128(request.height * 1000)
        hb.foliage_transaction_block = None
        if int(request.height) == 1:
            hb.header_hash = h1_hash
            hb.prev_header_hash = h0_hash
        else:
            hb.header_hash = h0_hash
            hb.prev_header_hash = unknown_prev
        response.header_block = hb
        return response

    peer = MagicMock()
    peer.call_api = AsyncMock(side_effect=mock_call_api)
    peer.peer_info = MagicMock()
    peer.peer_info.host = "genesis.example"
    header = make_header(2, h1_hash, bytes32(b"\x34" * 32))

    result = await node.wallet_short_sync_backtrack(header, peer)
    assert result == 0
    assert rollback_calls == []
    assert cast(Any, node.wallet_state_manager.blockchain.add_block).await_count == 3


@pytest.mark.anyio
async def test_sync_from_untrusted_close_to_peak_returns_false_on_backtrack_cap() -> None:
    """sync_from_untrusted_close_to_peak must return False when
    wallet_short_sync_backtrack returns None (cap exceeded), without
    proceeding to subscriptions or block processing."""
    node = make_backtrack_test_node(height=500, has_peak=True)
    peer = MagicMock()
    peer.peer_node_id = bytes32(b"\x66" * 32)
    peer.peer_info = MagicMock()
    peer.peer_info.host = "cap-test.example"

    new_peak_hb = MagicMock()
    new_peak_hb.height = uint32(505)
    new_peak_hb.weight = uint128(999_999)

    setattr(node, "wallet_short_sync_backtrack", AsyncMock(return_value=None))

    result = await node.sync_from_untrusted_close_to_peak(new_peak_hb, peer)
    assert result is False
    cast(Any, node.wallet_short_sync_backtrack).assert_awaited_once_with(new_peak_hb, peer)


@pytest.mark.anyio
async def test_new_peak_from_untrusted_synced_stale_weight_does_not_fallback() -> None:
    """When already synced and not far behind, if sync_from_untrusted_close_to_peak
    returns False due to stale/equal weight, we must NOT fall through to
    long_sync_from_untrusted.  Regression test for bugbot finding #4."""
    node = make_backtrack_test_node(height=1050, has_peak=True)
    peer = MagicMock()
    peer.peer_node_id = bytes32(b"\x77" * 32)
    peer.get_peer_info.return_value = "peer-info"
    peer.closed = False
    node.synced_peers.add(peer.peer_node_id)

    setattr(node, "sync_from_untrusted_close_to_peak", AsyncMock(return_value=False))
    setattr(node, "long_sync_from_untrusted", AsyncMock())

    new_peak_hb = MagicMock()
    new_peak_hb.height = uint32(1055)
    new_peak_hb.weight = uint128(5_000)

    result = await node.new_peak_from_untrusted(new_peak_hb, peer)
    assert result is False
    cast(Any, node.sync_from_untrusted_close_to_peak).assert_awaited_once_with(new_peak_hb, peer)
    cast(Any, node.long_sync_from_untrusted).assert_not_awaited()
    assert peer.peer_node_id in node.synced_peers


@pytest.mark.anyio
async def test_new_peak_from_untrusted_closed_peer_does_not_fallback() -> None:
    """When sync_from_untrusted_close_to_peak returns False because
    wallet_short_sync_backtrack closed the peer, new_peak_from_untrusted must
    return False immediately and NOT fall through to long_sync_from_untrusted
    with a dead connection."""
    node = make_backtrack_test_node(height=1050, has_peak=True)
    peak_block = cast(Any, node.wallet_state_manager.blockchain.get_peak_block).return_value
    peak_block.weight = uint128(1_000)

    peer = MagicMock()
    peer.peer_node_id = bytes32(b"\x99" * 32)
    peer.get_peer_info.return_value = "peer-info"
    peer.closed = True
    node.synced_peers.add(peer.peer_node_id)

    setattr(node, "sync_from_untrusted_close_to_peak", AsyncMock(return_value=False))
    setattr(node, "long_sync_from_untrusted", AsyncMock())

    new_peak_hb = MagicMock()
    new_peak_hb.height = uint32(1055)
    new_peak_hb.weight = uint128(50_000)

    result = await node.new_peak_from_untrusted(new_peak_hb, peer)
    assert result is False
    cast(Any, node.long_sync_from_untrusted).assert_not_awaited()


@pytest.mark.anyio
async def test_new_peak_from_untrusted_synced_fallback_removes_from_synced_peers() -> None:
    """When a synced peer's short sync fails (backtrack cap hit) but has higher
    weight, the peer must be removed from synced_peers before falling through
    to long_sync to prevent premature set_finished_sync_up_to."""
    node = make_backtrack_test_node(height=1050, has_peak=True)
    peak_block = cast(Any, node.wallet_state_manager.blockchain.get_peak_block).return_value
    peak_block.weight = uint128(1_000)

    peer = MagicMock()
    peer.peer_node_id = bytes32(b"\x88" * 32)
    peer.get_peer_info.return_value = "peer-info"
    peer.close = AsyncMock()
    peer.closed = False
    node.synced_peers.add(peer.peer_node_id)

    setattr(node, "sync_from_untrusted_close_to_peak", AsyncMock(return_value=False))
    setattr(node, "long_sync_from_untrusted", AsyncMock())

    new_peak_hb = MagicMock()
    new_peak_hb.height = uint32(1055)
    new_peak_hb.weight = uint128(50_000)

    result = await node.new_peak_from_untrusted(new_peak_hb, peer)
    assert result is True
    assert peer.peer_node_id not in node.synced_peers
    cast(Any, node.long_sync_from_untrusted).assert_awaited_once()


@pytest.mark.anyio
async def test_cap_hit_single_peer_triggers_primary_sync() -> None:
    """Single peer in synced_peers. Cap hit -> peer discarded -> synced_peers empty ->
    long_sync_from_untrusted called with syncing=True (primary sync mode)."""
    node = make_backtrack_test_node(height=1050, has_peak=True)
    peak_block = cast(Any, node.wallet_state_manager.blockchain.get_peak_block).return_value
    peak_block.weight = uint128(1_000)

    peer = MagicMock()
    peer.peer_node_id = bytes32(b"\xaa" * 32)
    peer.get_peer_info.return_value = "peer-info"
    peer.close = AsyncMock()
    peer.closed = False
    node.synced_peers.add(peer.peer_node_id)

    setattr(node, "sync_from_untrusted_close_to_peak", AsyncMock(return_value=False))
    setattr(node, "long_sync_from_untrusted", AsyncMock())

    new_peak_hb = MagicMock()
    new_peak_hb.height = uint32(1055)
    new_peak_hb.weight = uint128(50_000)

    result = await node.new_peak_from_untrusted(new_peak_hb, peer)
    assert result is True
    assert peer.peer_node_id not in node.synced_peers
    assert len(node.synced_peers) == 0
    cast(Any, node.long_sync_from_untrusted).assert_awaited_once_with(True, new_peak_hb, peer)


@pytest.mark.anyio
async def test_cap_hit_multi_peer_triggers_secondary_sync() -> None:
    """Two peers in synced_peers. Cap hit on one -> that peer discarded -> other peer
    remains -> long_sync_from_untrusted called with syncing=False (secondary sync mode)."""
    node = make_backtrack_test_node(height=1050, has_peak=True)
    peak_block = cast(Any, node.wallet_state_manager.blockchain.get_peak_block).return_value
    peak_block.weight = uint128(1_000)

    peer = MagicMock()
    peer.peer_node_id = bytes32(b"\xbb" * 32)
    peer.get_peer_info.return_value = "peer-info"
    peer.close = AsyncMock()
    peer.closed = False
    node.synced_peers.add(peer.peer_node_id)

    other_peer_id = bytes32(b"\xcc" * 32)
    node.synced_peers.add(other_peer_id)

    setattr(node, "sync_from_untrusted_close_to_peak", AsyncMock(return_value=False))
    setattr(node, "long_sync_from_untrusted", AsyncMock())

    new_peak_hb = MagicMock()
    new_peak_hb.height = uint32(1055)
    new_peak_hb.weight = uint128(50_000)

    result = await node.new_peak_from_untrusted(new_peak_hb, peer)
    assert result is True
    assert peer.peer_node_id not in node.synced_peers
    assert other_peer_id in node.synced_peers
    cast(Any, node.long_sync_from_untrusted).assert_awaited_once_with(False, new_peak_hb, peer)


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.anyio
@pytest.mark.standard_block_tools
async def test_get_balance(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str, default_1000_blocks: list[FullBlock]
) -> None:
    [full_node_api], [(wallet_node, wallet_server)], _bt = simulator_and_wallet
    full_node_server = full_node_api.full_node.server

    def wallet_synced() -> bool:
        return full_node_server.node_id in wallet_node.synced_peers

    async def restart_with_fingerprint(fingerprint: int | None) -> None:
        wallet_node._close()
        await wallet_node._await_closed(shutting_down=False)
        await wallet_node._start_with_fingerprint(fingerprint=fingerprint)

    wallet_id = uint32(1)
    initial_fingerprint = wallet_node.logged_in_fingerprint

    # TODO, there is a bug in wallet_short_sync_backtrack which leads to a rollback to 0 (-1 which is another a bug) and
    #       with that to a KeyError when applying the race cache if there are less than WEIGHT_PROOF_RECENT_BLOCKS
    #       blocks but we still have a peak stored in the DB. So we need to add enough blocks for a weight proof here to
    #       be able to restart the wallet in this test.
    await add_blocks_in_batches(default_1000_blocks[:600], full_node_api.full_node)
    # Initially there should be no sync and no balance
    assert not wallet_synced()
    assert await wallet_node.get_balance(wallet_id) == Balance()
    # Generate some funds, get the balance and make sure it's as expected
    await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await time_out_assert(30, wallet_synced)
    generated_funds = await full_node_api.farm_blocks_to_wallet(
        5, wallet_node.wallet_state_manager.main_wallet, timeout=60
    )
    expected_generated_balance = Balance(
        confirmed_wallet_balance=uint128(generated_funds),
        unconfirmed_wallet_balance=uint128(generated_funds),
        spendable_balance=uint128(generated_funds),
        max_send_amount=uint128(generated_funds),
        unspent_coin_count=uint32(10),
    )
    generated_balance = await wallet_node.get_balance(wallet_id)
    assert generated_balance == expected_generated_balance
    # Load another key without funds, make sure the balance is empty.
    other_key = KeyData.generate()
    assert wallet_node.local_keychain is not None
    wallet_node.local_keychain.add_key(other_key.mnemonic_str())
    await restart_with_fingerprint(other_key.fingerprint)
    assert await wallet_node.get_balance(wallet_id) == Balance()
    # Load the initial fingerprint again and make sure the balance is still what we generated earlier
    await restart_with_fingerprint(initial_fingerprint)
    assert await wallet_node.get_balance(wallet_id) == generated_balance
    # Connect and sync to the full node, generate more funds and test the balance caching
    # TODO, there is a bug in untrusted sync if we try to sync to the same peak as stored in the DB after restart
    #       which leads to a rollback to 0 (-1 which is another a bug) and then to a validation error because the
    #       downloaded weight proof will not be added to the blockchain properly because we still have a peak with the
    #       same weight stored in the DB but without chain data. The 1 block generation below can be dropped if we just
    #       also store the chain data or maybe adjust the weight proof consideration logic in new_valid_weight_proof.
    await full_node_api.farm_blocks_to_puzzlehash(1)
    assert not wallet_synced()
    await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await time_out_assert(30, wallet_synced)
    generated_funds += await full_node_api.farm_blocks_to_wallet(5, wallet_node.wallet_state_manager.main_wallet)
    expected_more_balance = Balance(
        confirmed_wallet_balance=uint128(generated_funds),
        unconfirmed_wallet_balance=uint128(generated_funds),
        spendable_balance=uint128(generated_funds),
        max_send_amount=uint128(generated_funds),
        unspent_coin_count=uint32(20),
    )
    async with wallet_node.wallet_state_manager.set_sync_mode(uint32(100)):
        # During sync the balance cache should not become updated, so it still should have the old balance here
        assert await wallet_node.get_balance(wallet_id) == expected_generated_balance
    # Now after the sync context the cache should become updated to the newly genertated balance
    assert await wallet_node.get_balance(wallet_id) == expected_more_balance
    # Restart one more time and make sure the balance is still correct after start
    await restart_with_fingerprint(initial_fingerprint)
    assert await wallet_node.get_balance(wallet_id) == expected_more_balance


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.anyio
async def test_add_states_from_peer_reorg_failure(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str, caplog: pytest.LogCaptureFixture
) -> None:
    [full_node_api], [(wallet_node, wallet_server)], _ = simulator_and_wallet
    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    wallet = wallet_node.wallet_state_manager.main_wallet
    await full_node_api.farm_rewards_to_wallet(1, wallet)
    coin_generator = CoinGenerator()
    coin_states = [CoinState(coin_generator.get().coin, None, None)]
    with caplog.at_level(logging.DEBUG):
        full_node_peer = next(iter(wallet_server.all_connections.values()))
        # Close the connection to trigger a state processing failure during reorged coin processing.
        await full_node_peer.close()
        assert not await wallet_node.add_states_from_peer(coin_states, full_node_peer)
        assert "Processing reorged states failed" in caplog.text


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.anyio
async def test_add_states_from_peer_untrusted_shutdown(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str, caplog: pytest.LogCaptureFixture
) -> None:
    [full_node_api], [(wallet_node, wallet_server)], _ = simulator_and_wallet
    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    wallet = wallet_node.wallet_state_manager.main_wallet
    await full_node_api.farm_rewards_to_wallet(1, wallet)
    # Close to trigger the shutdown
    wallet_node._close()
    coin_generator = CoinGenerator()
    # Generate enough coin states to fill up the max number validation/add tasks.
    coin_states = [CoinState(coin_generator.get().coin, uint32(i), uint32(i)) for i in range(3000)]
    with caplog.at_level(logging.INFO):
        assert not await wallet_node.add_states_from_peer(
            coin_states, next(iter(wallet_server.all_connections.values()))
        )
        assert "Terminating receipt and validation due to shut down request" in caplog.text


@pytest.mark.limit_consensus_modes(reason="consensus rules irrelevant")
@pytest.mark.anyio
async def test_transaction_send_cache(self_hostname: str, simulator_and_wallet: OldSimulatorsAndWallets) -> None:
    """
    The purpose of this test is to test that calling _resend_queue on the wallet node does not result in resending a
    spend to a peer that has already received that spend and is currently processing it. It also tests that once we
    have heard that the peer rejected the spend, we do NOT resend it to the same peer.
    """
    [full_node_api], [(wallet_node, wallet_server)], _ = simulator_and_wallet

    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    await time_out_assert(5, lambda: len(full_node_api.full_node.server.get_connections()) == 1)
    wallet = wallet_node.wallet_state_manager.main_wallet
    await full_node_api.farm_rewards_to_wallet(1, wallet)

    # Replacing the normal logic a full node has for processing transactions with a function that just logs what it gets
    logged_spends = []

    async def send_transaction(
        self: Self, request: wallet_protocol.SendTransaction, peer: WSChiaConnection, *, test: bool = False
    ) -> Message | None:
        logged_spends.append(request.transaction.name())
        return None

    assert full_node_api.full_node._server is not None
    with patch_request_handler(api=full_node_api.full_node._server.get_connections()[0].api, handler=send_transaction):
        # Generate the transaction
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction([uint64(0)], [bytes32.zeros], action_scope)
        [tx] = action_scope.side_effects.transactions

        # Make sure it is sent to the peer
        await wallet_node._resend_queue()

        def logged_spends_len() -> int:
            return len(logged_spends)

        await time_out_assert(5, logged_spends_len, 1)

        # Make sure queue processing again does not result in another spend
        await wallet_node._resend_queue()
        with pytest.raises(AssertionError):
            await time_out_assert(5, logged_spends_len, 2)

        # Tell the wallet that we received the spend (and it failed)
        msg = make_msg(
            ProtocolMessageTypes.transaction_ack,
            wallet_protocol.TransactionAck(
                tx.name, uint8(MempoolInclusionStatus.FAILED), Err.GENERATOR_RUNTIME_ERROR.name
            ),
        )
        assert simulator_and_wallet[1][0][0]._server is not None
        await simulator_and_wallet[1][0][0]._server.get_connections()[0].incoming_queue.put(msg)

        # Make sure the cache is emptied
        def check_wallet_cache_empty() -> bool:
            return wallet_node._tx_messages_in_progress == {}

        await time_out_assert(5, check_wallet_cache_empty, True)

        # Wait for the rejection to be persisted to sent_to before testing resend behavior
        async def check_sent_to_has_failed() -> bool:
            record = await wallet.wallet_state_manager.tx_store.get_transaction_record(tx.name)
            return record is not None and any(
                status == MempoolInclusionStatus.FAILED.value for _, status, _ in record.sent_to
            )

        await time_out_assert(10, check_sent_to_has_failed, True)

        # Re-process the queue — the peer already rejected it, so it should NOT be resent
        await wallet_node._resend_queue()
        with pytest.raises(AssertionError):
            await time_out_assert(5, logged_spends_len, 2)

    await time_out_assert(5, check_wallet_cache_empty, True)

    # Disconnect from the peer to make sure their entry in the cache is also deleted
    await simulator_and_wallet[1][0][0]._server.get_connections()[0].close(120)
    await time_out_assert(5, check_wallet_cache_empty, True)

    # --- Fee-failure retry on new transaction block ---
    # Reconnect and create a second transaction to test fee-failure retry behavior.
    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    await time_out_assert(5, lambda: len(full_node_api.full_node.server.get_connections()) == 1)
    logged_spends.clear()

    assert full_node_api.full_node._server is not None
    with patch_request_handler(api=full_node_api.full_node._server.get_connections()[0].api, handler=send_transaction):
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction([uint64(0)], [bytes32.zeros], action_scope)
        [tx2] = action_scope.side_effects.transactions

        await wallet_node._resend_queue()
        await time_out_assert(5, logged_spends_len, 1)

        # Ack with a fee error — this is a temporary rejection
        fee_ack = make_msg(
            ProtocolMessageTypes.transaction_ack,
            wallet_protocol.TransactionAck(
                tx2.name, uint8(MempoolInclusionStatus.FAILED), Err.INVALID_FEE_LOW_FEE.name
            ),
        )
        assert simulator_and_wallet[1][0][0]._server is not None
        await simulator_and_wallet[1][0][0]._server.get_connections()[0].incoming_queue.put(fee_ack)
        await time_out_assert(5, check_wallet_cache_empty, True)

        # _resend_queue should NOT resend (peer is in already_sent with FAILED status)
        await wallet_node._resend_queue()
        with pytest.raises(AssertionError):
            await time_out_assert(5, logged_spends_len, 2)

        # But _retry_fee_failed_transactions should resend to the same peer
        await wallet_node._retry_fee_failed_transactions()
        await time_out_assert(5, logged_spends_len, 2)

        # While the message is still in flight, a second retry should skip the peer
        await wallet_node._retry_fee_failed_transactions()
        with pytest.raises(AssertionError):
            await time_out_assert(5, logged_spends_len, 3)

        # When shutting down, _retry_fee_failed_transactions is a no-op
        wallet_node._shut_down = True
        await wallet_node._retry_fee_failed_transactions()
        with pytest.raises(AssertionError):
            await time_out_assert(5, logged_spends_len, 3)
        wallet_node._shut_down = False


@pytest.mark.limit_consensus_modes(reason="consensus rules irrelevant")
@pytest.mark.anyio
async def test_retry_fee_failed_skips_disconnected_and_in_flight(
    self_hostname: str, simulator_and_wallet: OldSimulatorsAndWallets
) -> None:
    """
    Covers the ``continue`` on wallet_node.py line 599 inside
    ``_retry_fee_failed_transactions``, which skips sending when the peer is
    unavailable.  It exercises both branches of the guard condition on line 598
    (``if peer is None or self._tx_message_in_flight(...)``):

    Case 1 — peer disconnected:
        A transaction is sent, receives a fee-error ack (INVALID_FEE_LOW_FEE),
        and then the peer disconnects.  When ``_retry_fee_failed_transactions``
        runs, ``peer_map.get(peer_node_id)`` returns ``None``, so the
        ``continue`` fires and no resend occurs.

    Case 2 — message already in flight:
        A fresh transaction gets a fee-error ack
        (INVALID_FEE_TOO_CLOSE_TO_ZERO), and then the message is manually
        marked as in-flight in ``_tx_messages_in_progress``.  When
        ``_retry_fee_failed_transactions`` runs, ``_tx_message_in_flight()``
        returns ``True``, so the ``continue`` fires and no resend occurs.
    """
    [full_node_api], [(wallet_node, wallet_server)], _ = simulator_and_wallet

    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    await time_out_assert(5, lambda: len(full_node_api.full_node.server.get_connections()) == 1)
    wallet = wallet_node.wallet_state_manager.main_wallet
    await full_node_api.farm_rewards_to_wallet(1, wallet)

    logged_spends: list[bytes32] = []

    async def send_transaction(
        self: Self, request: wallet_protocol.SendTransaction, peer: WSChiaConnection, *, test: bool = False
    ) -> Message | None:
        logged_spends.append(request.transaction.name())
        return None

    def check_wallet_cache_empty() -> bool:
        return wallet_node._tx_messages_in_progress == {}

    assert full_node_api.full_node._server is not None
    with patch_request_handler(api=full_node_api.full_node._server.get_connections()[0].api, handler=send_transaction):
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction([uint64(0)], [bytes32.zeros], action_scope)
        [tx] = action_scope.side_effects.transactions

        await wallet_node._resend_queue()
        await time_out_assert(5, lambda: len(logged_spends), 1)

        fee_ack = make_msg(
            ProtocolMessageTypes.transaction_ack,
            wallet_protocol.TransactionAck(tx.name, uint8(MempoolInclusionStatus.FAILED), Err.INVALID_FEE_LOW_FEE.name),
        )
        assert simulator_and_wallet[1][0][0]._server is not None
        wallet_conn = simulator_and_wallet[1][0][0]._server.get_connections()[0]
        await wallet_conn.incoming_queue.put(fee_ack)
        await time_out_assert(5, check_wallet_cache_empty, True)

        # --- Case 1: peer disconnected -----------------------------------------------
        # Disconnect and call _retry_fee_failed_transactions; the peer is no longer in
        # the connection list so peer_map.get() returns None → continue (line 599).
        await wallet_conn.close(120)
        await wallet_node._retry_fee_failed_transactions()
        with pytest.raises(AssertionError):
            await time_out_assert(5, lambda: len(logged_spends), 2)

    # --- Case 2: message already in flight ----------------------------------------
    # Reconnect, re-create the fee-failed state, then manually mark the message as
    # in-flight so _retry_fee_failed_transactions hits the second branch of line 598.
    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    await time_out_assert(5, lambda: len(full_node_api.full_node.server.get_connections()) == 1)
    logged_spends.clear()

    assert full_node_api.full_node._server is not None
    with patch_request_handler(api=full_node_api.full_node._server.get_connections()[0].api, handler=send_transaction):
        async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
            await wallet.generate_signed_transaction([uint64(0)], [bytes32.zeros], action_scope)
        [tx2] = action_scope.side_effects.transactions

        await wallet_node._resend_queue()
        await time_out_assert(5, lambda: len(logged_spends), 1)

        fee_ack2 = make_msg(
            ProtocolMessageTypes.transaction_ack,
            wallet_protocol.TransactionAck(
                tx2.name, uint8(MempoolInclusionStatus.FAILED), Err.INVALID_FEE_TOO_CLOSE_TO_ZERO.name
            ),
        )
        assert simulator_and_wallet[1][0][0]._server is not None
        wallet_conn2 = simulator_and_wallet[1][0][0]._server.get_connections()[0]
        await wallet_conn2.incoming_queue.put(fee_ack2)
        await time_out_assert(5, check_wallet_cache_empty, True)

        peer = full_node_api.full_node._server.get_connections()[0]
        sb = tx2.spend_bundle
        assert sb is not None
        msg = make_msg(ProtocolMessageTypes.send_transaction, wallet_protocol.SendTransaction(sb))
        msg_name = std_hash(msg.data)
        wallet_node._tx_messages_in_progress.setdefault(peer.peer_node_id, []).append(msg_name)

        await wallet_node._retry_fee_failed_transactions()
        with pytest.raises(AssertionError):
            await time_out_assert(5, lambda: len(logged_spends), 2)

        wallet_node._tx_messages_in_progress.clear()


@pytest.mark.parametrize(
    "wallet_environments",
    [
        {
            "num_environments": 1,
            "blocks_needed": [1],
        }
    ],
    indirect=True,
)
@pytest.mark.limit_consensus_modes(reason="consensus rules irrelevant")
@pytest.mark.anyio
async def test_transaction_ack_duplicate_without_resend_ignored(
    wallet_environments: WalletTestFramework, caplog: pytest.LogCaptureFixture
) -> None:
    env = wallet_environments.environments[0]
    full_node_api = wallet_environments.full_node
    wallet_node = env.node
    wallet = env.xch_wallet

    logged_spends = []

    async def send_transaction(
        self: Self, request: wallet_protocol.SendTransaction, peer: WSChiaConnection, *, test: bool = False
    ) -> Message | None:
        logged_spends.append(request.transaction.name())
        return None

    assert full_node_api.full_node._server is not None
    with patch_request_handler(api=full_node_api.full_node._server.get_connections()[0].api, handler=send_transaction):
        async with wallet.wallet_state_manager.new_action_scope(
            wallet.wallet_state_manager.tx_config, push=True
        ) as action_scope:
            await wallet.generate_signed_transaction([uint64(0)], [bytes32.zeros], action_scope)
        [tx] = action_scope.side_effects.transactions

        await wallet_node._resend_queue()
        await time_out_assert(5, lambda: len(logged_spends), 1)

        msg = make_msg(
            ProtocolMessageTypes.transaction_ack,
            wallet_protocol.TransactionAck(
                tx.name, uint8(MempoolInclusionStatus.FAILED), Err.GENERATOR_RUNTIME_ERROR.name
            ),
        )
        conn = env.peer_server.get_connections()[0]
        await conn.incoming_queue.put(msg)

        def check_wallet_cache_empty() -> bool:
            return wallet_node._tx_messages_in_progress == {}

        def incoming_queue_empty() -> bool:
            return conn.incoming_queue.qsize() == 0

        await time_out_assert(5, check_wallet_cache_empty, True)
        first_tx_record = await wallet_node.wallet_state_manager.get_transaction(tx.name)
        assert first_tx_record is not None
        first_sent = first_tx_record.sent
        first_sent_to = first_tx_record.sent_to.copy()
        first_confirmed = first_tx_record.confirmed

        # Duplicate acks without another send should all be ignored.
        with caplog.at_level(logging.DEBUG, logger="chia.wallet.wallet_node"):
            for _ in range(10):
                await conn.incoming_queue.put(msg)
                await time_out_assert(5, incoming_queue_empty, True)
                await time_out_assert(5, check_wallet_cache_empty, True)

        second_tx_record = await wallet_node.wallet_state_manager.get_transaction(tx.name)
        assert second_tx_record is not None
        assert second_tx_record.sent == first_sent
        assert second_tx_record.sent_to == first_sent_to
        assert second_tx_record.confirmed == first_confirmed
        assert sum("Ignoring unsolicited transaction ack" in record.getMessage() for record in caplog.records) >= 10


@pytest.mark.limit_consensus_modes(reason="consensus rules irrelevant")
@pytest.mark.anyio
async def test_wallet_node_bad_coin_state_ignore(
    self_hostname: str, simulator_and_wallet: OldSimulatorsAndWallets, monkeypatch: pytest.MonkeyPatch
) -> None:
    [full_node_api], [(wallet_node, wallet_server)], _ = simulator_and_wallet

    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    await time_out_assert(5, lambda: len(full_node_api.full_node.server.get_connections()) == 1)

    async def register_for_coin_updates(
        self: Self, request: wallet_protocol.RegisterForCoinUpdates, *, test: bool = False
    ) -> Message | None:
        return make_msg(
            ProtocolMessageTypes.respond_to_coin_updates,
            wallet_protocol.RespondToCoinUpdates(
                [], uint32(0), [CoinState(Coin(bytes32.zeros, bytes32.zeros, uint64(0)), uint32(0), uint32(0))]
            ),
        )

    async def validate_received_state_from_peer(*args: Any) -> bool:
        # It's an interesting case here where we don't hit this unless something is broken
        return True  # pragma: no cover

    assert full_node_api.full_node._server is not None
    with patch_request_handler(
        api=full_node_api.full_node._server.get_connections()[0].api, handler=register_for_coin_updates
    ):
        monkeypatch.setattr(
            wallet_node,
            "validate_received_state_from_peer",
            types.MethodType(validate_received_state_from_peer, wallet_node),
        )

        with pytest.raises(PeerRequestException):
            await wallet_node.get_coin_state([], wallet_node.get_full_node_peer())


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.anyio
@pytest.mark.standard_block_tools
async def test_start_with_multiple_key_types(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str, default_400_blocks: list[FullBlock]
) -> None:
    [_full_node_api], [(wallet_node, _wallet_server)], _bt = simulator_and_wallet

    async def restart_with_fingerprint(fingerprint: int | None) -> None:
        wallet_node._close()
        await wallet_node._await_closed(shutting_down=False)
        await wallet_node._start_with_fingerprint(fingerprint=fingerprint)

    initial_sk = wallet_node.wallet_state_manager.private_key

    pk: G1Element = await wallet_node.keychain_proxy.add_key(
        "c00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
        None,
        private=False,
    )
    fingerprint_pk: int = pk.get_fingerprint()

    await restart_with_fingerprint(fingerprint_pk)
    assert wallet_node.wallet_state_manager.private_key is None
    assert wallet_node.wallet_state_manager.root_pubkey == G1Element()

    await wallet_node.keychain_proxy.delete_key_by_fingerprint(fingerprint_pk)

    await restart_with_fingerprint(fingerprint_pk)
    assert wallet_node.wallet_state_manager.private_key == initial_sk


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.anyio
@pytest.mark.standard_block_tools
async def test_start_with_multiple_keys(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str, default_400_blocks: list[FullBlock]
) -> None:
    [_full_node_api], [(wallet_node, _wallet_server)], _bt = simulator_and_wallet

    async def restart_with_fingerprint(fingerprint: int | None) -> None:
        wallet_node._close()
        await wallet_node._await_closed(shutting_down=False)
        await wallet_node._start_with_fingerprint(fingerprint=fingerprint)

    initial_sk = wallet_node.wallet_state_manager.private_key

    sk_2: PrivateKey = await wallet_node.keychain_proxy.add_key(
        (
            "cup smoke miss park baby say island tomorrow segment lava bitter easily settle gift "
            "renew arrive kangaroo dilemma organ skin design salt history awesome"
        ),
        None,
        private=True,
    )
    fingerprint_2: int = sk_2.get_g1().get_fingerprint()

    await restart_with_fingerprint(fingerprint_2)
    assert wallet_node.wallet_state_manager.private_key == sk_2

    await wallet_node.keychain_proxy.delete_key_by_fingerprint(fingerprint_2)

    await restart_with_fingerprint(fingerprint_2)
    assert wallet_node.wallet_state_manager.private_key == initial_sk
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD


class HeaderBlockCase(enum.Enum):
    NoneResponse = 0
    WrongCount = 1
    WrongHeight = 2
    NonTx = 3
    ValidResponse = 4


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
@pytest.mark.parametrize(
    "header_block_case, expected_success, expected_closed",
    [
        (HeaderBlockCase.NoneResponse, False, False),
        (HeaderBlockCase.WrongCount, False, False),
        (HeaderBlockCase.WrongHeight, False, True),
        (HeaderBlockCase.NonTx, False, False),
        (HeaderBlockCase.ValidResponse, True, False),
    ],
)
@pytest.mark.anyio
async def test_request_and_validate_header_block(
    simulator_and_wallet: OldSimulatorsAndWallets,
    self_hostname: str,
    header_block_case: HeaderBlockCase,
    expected_success: bool,
    expected_closed: bool,
) -> None:
    """
    Covers the header block validation cases (`None` response, wrong count,
    wrong height, non transaction header block and finally a valid response)
    for request_and_validate_header_block.
    """
    [full_node_api], [(wallet_node, _)], _ = simulator_and_wallet
    server = full_node_api.full_node.server
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32.random()))
    peak = full_node_api.full_node.blockchain.get_peak()
    assert peak is not None
    correct_full_block = await full_node_api.full_node.block_store.get_full_block(peak.header_hash)
    assert correct_full_block is not None
    assert correct_full_block.foliage_transaction_block is not None
    correct_block_header = get_block_header(correct_full_block)
    all_blocks = await full_node_api.get_all_full_blocks()
    wrong_full_block = next(b for b in all_blocks if b.height != correct_full_block.height)
    wrong_height_block_header = get_block_header(wrong_full_block)
    no_tx_block_header = correct_block_header.replace(foliage_transaction_block=None)
    wsc, _ = await add_dummy_connection_wsc(server, self_hostname, 42, NodeType.WALLET, wait_for_peer_added=False)
    requested_height = correct_block_header.height
    calls: list[tuple[uint32, uint32]] = []

    async def request_block_headers(self: FullNodeAPI, request: wallet_protocol.RequestBlockHeaders) -> Message | None:
        calls.append((request.start_height, request.end_height))
        if header_block_case == HeaderBlockCase.NoneResponse:
            reject = wallet_protocol.RejectBlockHeaders(request.start_height, request.end_height)
            return make_msg(ProtocolMessageTypes.reject_block_headers, reject)
        headers = []
        if header_block_case == HeaderBlockCase.WrongCount:
            headers = [correct_block_header, wrong_height_block_header]
        elif header_block_case == HeaderBlockCase.WrongHeight:
            headers = [wrong_height_block_header]
        elif header_block_case == HeaderBlockCase.NonTx:
            headers = [no_tx_block_header]
        elif header_block_case == HeaderBlockCase.ValidResponse:
            headers = [correct_block_header]
        else:
            assert False  # pragma: no cover
        response = wallet_protocol.RespondBlockHeaders(request.start_height, request.end_height, headers)
        return make_msg(ProtocolMessageTypes.respond_block_headers, response)

    with patch_request_handler(api=server.api, handler=request_block_headers):
        result = await request_and_validate_header_block(wsc, requested_height, wallet_node.log)

    assert calls == [(requested_height, requested_height)]
    if expected_success:
        assert result == correct_block_header
    else:
        assert result is None
    if expected_closed:
        assert wsc.closed
    else:
        assert not wsc.closed


@pytest.mark.anyio
@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0], reason="irrelevant")
@pytest.mark.parametrize("created_cached_non_tx", [False, True])
@pytest.mark.parametrize("spent_cached_non_tx", [False, True])
async def test_validate_received_state_from_peer_cached_non_tx(
    simulator_and_wallet: OldSimulatorsAndWallets,
    self_hostname: str,
    created_cached_non_tx: bool,
    spent_cached_non_tx: bool,
) -> None:
    """
    Covers the scenarios where `validate_received_state_from_peer` is called
    with the peer request cache returning non transaction header blocks for the
    created and/or spent heights, to make sure the validation fails and the
    peer's connection stays intact.
    """
    [full_node_api], [(wallet_node, _)], _ = simulator_and_wallet
    server = full_node_api.full_node.server
    await full_node_api.farm_new_transaction_block(FarmNewBlockProtocol(bytes32.random()))
    blocks = await full_node_api.get_all_full_blocks()
    tx_blocks = [b for b in blocks if b.is_transaction_block()]
    assert len(tx_blocks) == 2
    created_tx_header = get_block_header(tx_blocks[-2])
    spent_tx_header = get_block_header(tx_blocks[-1])
    # Create non tx variants
    created_non_tx_block_header = created_tx_header.replace(foliage_transaction_block=None)
    spent_non_tx_block_header = spent_tx_header.replace(foliage_transaction_block=None)
    peer_request_cache = PeerRequestCache()
    coin = Coin(bytes32.random(), bytes32.random(), uint64(1))
    coin_state = CoinState(coin, spent_non_tx_block_header.height, created_tx_header.height)
    if created_cached_non_tx:
        peer_request_cache._blocks.put(created_non_tx_block_header.height, created_non_tx_block_header)
        coin_state = CoinState(coin, None, created_non_tx_block_header.height)
    if spent_cached_non_tx:
        peer_request_cache.add_to_blocks(created_tx_header)
        peer_request_cache._blocks.put(spent_non_tx_block_header.height, spent_non_tx_block_header)
    wsc, _ = await add_dummy_connection_wsc(server, self_hostname, 42, NodeType.WALLET, wait_for_peer_added=False)
    result = await wallet_node.validate_received_state_from_peer(
        coin_state=coin_state, peer=wsc, peer_request_cache=peer_request_cache, fork_height=None
    )
    assert result is False
    assert not wsc.closed
=======
>>>>>>> ee8e424 (build(deps): bump pytest-rerunfailures from 16.1 to 16.2)
=======
>>>>>>> d747b89 (build(deps): bump ruff from 0.15.8 to 0.15.13)
=======
>>>>>>> 8e73dd3 (build(deps): bump boto3 from 1.43.8 to 1.43.11)
=======
>>>>>>> 20feb6e (build(deps): bump lxml from 6.1.0 to 6.1.1)
