from __future__ import annotations

import logging
import sys
import time
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from chia_rs import G1Element, PrivateKey

from chia._tests.util.misc import CoinGenerator, add_blocks_in_batches
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets
from chia._tests.util.time_out_assert import time_out_assert
from chia.protocols import wallet_protocol
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.wallet_protocol import CoinState
from chia.server.outbound_message import Message, make_msg
from chia.simulator.block_tools import test_constants
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.peer_info import PeerInfo
from chia.util.api_decorators import Self, api_request
from chia.util.config import load_config
from chia.util.errors import Err
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.util.keychain import Keychain, KeyData, generate_mnemonic
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG
from chia.wallet.util.wallet_sync_utils import PeerRequestException
from chia.wallet.wallet_node import Balance, WalletNode


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
    root_path_populated_with_config: Path, get_temp_keyring: Keychain, fingerprint: Optional[int]
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
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
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
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
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
    root_path_populated_with_config: Path, get_temp_keyring: Keychain, fingerprint: Optional[int]
) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring  # empty keyring
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
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
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
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
    if sys.platform in ["win32", "cygwin"]:
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
    if sys.platform not in ["win32", "cygwin"]:
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
        last_used_fingerprint: Optional[int] = node.get_last_used_fingerprint()

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
async def test_get_timestamp_for_height_from_peer(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str, caplog: pytest.LogCaptureFixture
) -> None:
    [full_node_api], [(wallet_node, wallet_server)], _ = simulator_and_wallet

    async def get_timestamp(height: int) -> Optional[uint64]:
        return await wallet_node.get_timestamp_for_height_from_peer(uint32(height), full_node_peer)

    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    wallet = wallet_node.wallet_state_manager.main_wallet
    await full_node_api.farm_blocks_to_wallet(2, wallet)
    full_node_peer = list(wallet_server.all_connections.values())[0]
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
    for i in [0, 1]:
        block = cache.get_block(uint32(i))
        assert block is not None
        if i == 0:
            assert block.is_transaction_block
        else:
            assert not block.is_transaction_block
        assert f"get_timestamp_for_height_from_peer cache miss for height {i}" in caplog.text
        assert f"get_timestamp_for_height_from_peer add to cache for height {i}" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        await get_timestamp(1)
    assert f"get_timestamp_for_height_from_peer use cached block for height {0}" not in caplog.text
    assert f"get_timestamp_for_height_from_peer use cached block for height {1}" in caplog.text


@pytest.mark.anyio
async def test_unique_puzzle_hash_subscriptions(simulator_and_wallet: OldSimulatorsAndWallets) -> None:
    _, [(node, _)], _ = simulator_and_wallet
    puzzle_hashes = await node.get_puzzle_hashes_to_subscribe()
    assert len(puzzle_hashes) > 1
    assert len(set(puzzle_hashes)) == len(puzzle_hashes)


@pytest.mark.anyio
@pytest.mark.standard_block_tools
async def test_get_balance(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str, default_400_blocks: List[FullBlock]
) -> None:
    [full_node_api], [(wallet_node, wallet_server)], bt = simulator_and_wallet
    full_node_server = full_node_api.full_node.server

    def wallet_synced() -> bool:
        return full_node_server.node_id in wallet_node.synced_peers

    async def restart_with_fingerprint(fingerprint: Optional[int]) -> None:
        wallet_node._close()
        await wallet_node._await_closed(shutting_down=False)
        await wallet_node._start_with_fingerprint(fingerprint=fingerprint)

    wallet_id = uint32(1)
    initial_fingerprint = wallet_node.logged_in_fingerprint

    # TODO, there is a bug in wallet_short_sync_backtrack which leads to a rollback to 0 (-1 which is another a bug) and
    #       with that to a KeyError when applying the race cache if there are less than WEIGHT_PROOF_RECENT_BLOCKS
    #       blocks but we still have a peak stored in the DB. So we need to add enough blocks for a weight proof here to
    #       be able to restart the wallet in this test.
    await add_blocks_in_batches(default_400_blocks, full_node_api.full_node)
    # Initially there should be no sync and no balance
    assert not wallet_synced()
    assert await wallet_node.get_balance(wallet_id) == Balance()
    # Generate some funds, get the balance and make sure it's as expected
    await wallet_server.start_client(PeerInfo(self_hostname, full_node_server.get_port()), None)
    await time_out_assert(30, wallet_synced)
    generated_funds = await full_node_api.farm_blocks_to_wallet(5, wallet_node.wallet_state_manager.main_wallet)
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
        full_node_peer = list(wallet_server.all_connections.values())[0]
        # Close the connection to trigger a state processing failure during reorged coin processing.
        await full_node_peer.close()
        assert not await wallet_node.add_states_from_peer(coin_states, full_node_peer)
        assert "Processing reorged states failed" in caplog.text


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
        assert not await wallet_node.add_states_from_peer(coin_states, list(wallet_server.all_connections.values())[0])
        assert "Terminating receipt and validation due to shut down request" in caplog.text


@pytest.mark.limit_consensus_modes(reason="consensus rules irrelevant")
@pytest.mark.anyio
async def test_transaction_send_cache(
    self_hostname: str, simulator_and_wallet: OldSimulatorsAndWallets, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The purpose of this test is to test that calling _resend_queue on the wallet node does not result in resending a
    spend to a peer that has already recieved that spend and is currently processing it. It also tests that once we
    have heard that the peer is done processing the spend, we _do_ properly resend it.
    """
    [full_node_api], [(wallet_node, wallet_server)], _ = simulator_and_wallet

    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)
    wallet = wallet_node.wallet_state_manager.main_wallet
    await full_node_api.farm_rewards_to_wallet(1, wallet)

    # Replacing the normal logic a full node has for processing transactions with a function that just logs what it gets
    logged_spends = []

    @api_request()
    async def send_transaction(
        self: Self, request: wallet_protocol.SendTransaction, *, test: bool = False
    ) -> Optional[Message]:
        logged_spends.append(request.transaction.name())
        return None

    assert full_node_api.full_node._server is not None
    monkeypatch.setattr(
        full_node_api.full_node._server.get_connections()[0].api,
        "send_transaction",
        types.MethodType(send_transaction, full_node_api.full_node._server.get_connections()[0].api),
    )

    # Generate the transaction
    async with wallet.wallet_state_manager.new_action_scope(DEFAULT_TX_CONFIG, push=True) as action_scope:
        await wallet.generate_signed_transaction(uint64(0), bytes32([0] * 32), action_scope)
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

    # Tell the wallet that we recieved the spend (but failed to process it so it should send again)
    msg = make_msg(
        ProtocolMessageTypes.transaction_ack,
        wallet_protocol.TransactionAck(tx.name, uint8(MempoolInclusionStatus.FAILED), Err.GENERATOR_RUNTIME_ERROR.name),
    )
    assert simulator_and_wallet[1][0][0]._server is not None
    await simulator_and_wallet[1][0][0]._server.get_connections()[0].incoming_queue.put(msg)

    # Make sure the cache is emptied
    def check_wallet_cache_empty() -> bool:
        return wallet_node._tx_messages_in_progress == {}

    await time_out_assert(5, check_wallet_cache_empty, True)

    # Re-process the queue again and this time it should result in a resend
    await wallet_node._resend_queue()
    await time_out_assert(5, logged_spends_len, 2)
    assert logged_spends == [tx.name, tx.name]
    await time_out_assert(5, check_wallet_cache_empty, False)

    # Disconnect from the peer to make sure their entry in the cache is also deleted
    await simulator_and_wallet[1][0][0]._server.get_connections()[0].close(120)
    await time_out_assert(5, check_wallet_cache_empty, True)


@pytest.mark.limit_consensus_modes(reason="consensus rules irrelevant")
@pytest.mark.anyio
async def test_wallet_node_bad_coin_state_ignore(
    self_hostname: str, simulator_and_wallet: OldSimulatorsAndWallets, monkeypatch: pytest.MonkeyPatch
) -> None:
    [full_node_api], [(wallet_node, wallet_server)], _ = simulator_and_wallet

    await wallet_server.start_client(PeerInfo(self_hostname, full_node_api.server.get_port()), None)

    @api_request()
    async def register_interest_in_coin(
        self: Self, request: wallet_protocol.RegisterForCoinUpdates, *, test: bool = False
    ) -> Optional[Message]:
        return make_msg(
            ProtocolMessageTypes.respond_to_coin_update,
            wallet_protocol.RespondToCoinUpdates(
                [], uint32(0), [CoinState(Coin(bytes32([0] * 32), bytes32([0] * 32), uint64(0)), uint32(0), uint32(0))]
            ),
        )

    async def validate_received_state_from_peer(*args: Any) -> bool:
        # It's an interesting case here where we don't hit this unless something is broken
        return True  # pragma: no cover

    assert full_node_api.full_node._server is not None
    monkeypatch.setattr(
        full_node_api.full_node._server.get_connections()[0].api,
        "register_interest_in_coin",
        types.MethodType(register_interest_in_coin, full_node_api.full_node._server.get_connections()[0].api),
    )
    monkeypatch.setattr(
        wallet_node,
        "validate_received_state_from_peer",
        types.MethodType(validate_received_state_from_peer, wallet_node),
    )

    with pytest.raises(PeerRequestException):
        await wallet_node.get_coin_state([], wallet_node.get_full_node_peer())


@pytest.mark.anyio
@pytest.mark.standard_block_tools
async def test_start_with_multiple_key_types(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str, default_400_blocks: List[FullBlock]
) -> None:
    [full_node_api], [(wallet_node, wallet_server)], bt = simulator_and_wallet

    async def restart_with_fingerprint(fingerprint: Optional[int]) -> None:
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


@pytest.mark.anyio
@pytest.mark.standard_block_tools
async def test_start_with_multiple_keys(
    simulator_and_wallet: OldSimulatorsAndWallets, self_hostname: str, default_400_blocks: List[FullBlock]
) -> None:
    [full_node_api], [(wallet_node, wallet_server)], bt = simulator_and_wallet

    async def restart_with_fingerprint(fingerprint: Optional[int]) -> None:
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
