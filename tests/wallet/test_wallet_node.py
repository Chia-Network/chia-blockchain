from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from blspy import PrivateKey

from chia.simulator.block_tools import test_constants
from chia.simulator.setup_nodes import SimulatorsAndWallets
from chia.simulator.time_out_assert import time_out_assert
from chia.types.full_block import FullBlock
from chia.types.peer_info import PeerInfo
from chia.util.config import load_config
from chia.util.ints import uint16, uint32, uint128
from chia.util.keychain import Keychain, KeyData, generate_mnemonic
from chia.wallet.wallet_node import Balance, WalletNode


@pytest.mark.asyncio
async def test_get_private_key(root_path_populated_with_config: Path, get_temp_keyring: Keychain) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants, keychain)
    sk: PrivateKey = keychain.add_private_key(generate_mnemonic())
    fingerprint: int = sk.get_g1().get_fingerprint()

    key = await node.get_private_key(fingerprint)

    assert key is not None
    assert key.get_g1().get_fingerprint() == fingerprint


@pytest.mark.asyncio
async def test_get_private_key_default_key(root_path_populated_with_config: Path, get_temp_keyring: Keychain) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants, keychain)
    sk: PrivateKey = keychain.add_private_key(generate_mnemonic())
    fingerprint: int = sk.get_g1().get_fingerprint()

    # Add a couple more keys
    keychain.add_private_key(generate_mnemonic())
    keychain.add_private_key(generate_mnemonic())

    # When no fingerprint is provided, we should get the default (first) key
    key = await node.get_private_key(None)

    assert key is not None
    assert key.get_g1().get_fingerprint() == fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize("fingerprint", [None, 1234567890])
async def test_get_private_key_missing_key(
    root_path_populated_with_config: Path, get_temp_keyring: Keychain, fingerprint: Optional[int]
) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring  # empty keyring
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants, keychain)

    # Keyring is empty, so requesting a key by fingerprint or None should return None
    key = await node.get_private_key(fingerprint)

    assert key is None


@pytest.mark.asyncio
async def test_get_private_key_missing_key_use_default(
    root_path_populated_with_config: Path, get_temp_keyring: Keychain
) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants, keychain)
    sk: PrivateKey = keychain.add_private_key(generate_mnemonic())
    fingerprint: int = sk.get_g1().get_fingerprint()

    # Stupid sanity check that the fingerprint we're going to use isn't actually in the keychain
    assert fingerprint != 1234567890

    # When fingerprint is provided and the key is missing, we should get the default (first) key
    key = await node.get_private_key(1234567890)

    assert key is not None
    assert key.get_g1().get_fingerprint() == fingerprint


def test_log_in(root_path_populated_with_config: Path, get_temp_keyring: Keychain) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    sk: PrivateKey = keychain.add_private_key(generate_mnemonic())
    fingerprint: int = sk.get_g1().get_fingerprint()

    node.log_in(sk)

    assert node.logged_in is True
    assert node.logged_in_fingerprint == fingerprint
    assert node.get_last_used_fingerprint() == fingerprint


def test_log_in_failure_to_write_last_used_fingerprint(
    root_path_populated_with_config: Path, get_temp_keyring: Keychain, monkeypatch: Any
) -> None:
    called_update_last_used_fingerprint: bool = False

    def patched_update_last_used_fingerprint(self: Any) -> None:
        nonlocal called_update_last_used_fingerprint
        called_update_last_used_fingerprint = True
        raise Exception("Generic write failure")

    with monkeypatch.context() as m:
        m.setattr(WalletNode, "update_last_used_fingerprint", patched_update_last_used_fingerprint)
        root_path: Path = root_path_populated_with_config
        keychain: Keychain = get_temp_keyring
        config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
        node: WalletNode = WalletNode(config, root_path, test_constants)
        sk: PrivateKey = keychain.add_private_key(generate_mnemonic())
        fingerprint: int = sk.get_g1().get_fingerprint()

        # Expect log_in to succeed, even though we can't write the last used fingerprint
        node.log_in(sk)

        assert node.logged_in is True
        assert node.logged_in_fingerprint == fingerprint
        assert node.get_last_used_fingerprint() is None
        assert called_update_last_used_fingerprint is True


def test_log_out(root_path_populated_with_config: Path, get_temp_keyring: Keychain) -> None:
    root_path: Path = root_path_populated_with_config
    keychain: Keychain = get_temp_keyring
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    sk: PrivateKey = keychain.add_private_key(generate_mnemonic())
    fingerprint: int = sk.get_g1().get_fingerprint()

    node.log_in(sk)

    assert node.logged_in is True
    assert node.logged_in_fingerprint == fingerprint
    assert node.get_last_used_fingerprint() == fingerprint

    node.log_out()

    assert node.logged_in is False
    assert node.logged_in_fingerprint is None
    assert node.get_last_used_fingerprint() == fingerprint


def test_get_last_used_fingerprint_path(root_path_populated_with_config: Path) -> None:
    root_path: Path = root_path_populated_with_config
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    path: Optional[Path] = node.get_last_used_fingerprint_path()

    assert path == root_path / "wallet" / "db" / "last_used_fingerprint"


def test_get_last_used_fingerprint(root_path_populated_with_config: Path) -> None:
    path: Path = root_path_populated_with_config / "wallet" / "db" / "last_used_fingerprint"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1234567890")

    root_path: Path = root_path_populated_with_config
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    last_used_fingerprint: Optional[int] = node.get_last_used_fingerprint()

    assert last_used_fingerprint == 1234567890


def test_get_last_used_fingerprint_file_doesnt_exist(root_path_populated_with_config: Path) -> None:
    root_path: Path = root_path_populated_with_config
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    last_used_fingerprint: Optional[int] = node.get_last_used_fingerprint()

    assert last_used_fingerprint is None


def test_get_last_used_fingerprint_file_cant_read_unix(root_path_populated_with_config: Path) -> None:
    if sys.platform in ["win32", "cygwin"]:
        pytest.skip("Setting UNIX file permissions doesn't apply to Windows")

    root_path: Path = root_path_populated_with_config
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    path: Path = node.get_last_used_fingerprint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1234567890")

    assert node.get_last_used_fingerprint() == 1234567890

    # Make the file unreadable
    path.chmod(0o000)

    last_used_fingerprint: Optional[int] = node.get_last_used_fingerprint()

    assert last_used_fingerprint is None

    # Verify that the file is unreadable
    with pytest.raises(PermissionError):
        path.read_text()

    # Calling get_last_used_fingerprint() should not throw an exception
    assert node.get_last_used_fingerprint() is None

    path.chmod(0o600)


def test_get_last_used_fingerprint_file_cant_read_win32(
    root_path_populated_with_config: Path, monkeypatch: Any
) -> None:
    if sys.platform not in ["win32", "cygwin"]:
        pytest.skip("Windows-specific test")

    called_read_text: bool = False

    def patched_pathlib_path_read_text(self: Any) -> str:
        nonlocal called_read_text
        called_read_text = True
        raise PermissionError("Permission denied")

    root_path: Path = root_path_populated_with_config
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    path: Path = node.get_last_used_fingerprint_path()
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
    root_path: Path = root_path_populated_with_config
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    path: Path = node.get_last_used_fingerprint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\r\n \t1234567890\r\n\n")

    assert node.get_last_used_fingerprint() == 1234567890


def test_update_last_used_fingerprint_missing_fingerprint(root_path_populated_with_config: Path) -> None:
    root_path: Path = root_path_populated_with_config
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    node.logged_in_fingerprint = None

    with pytest.raises(AssertionError):
        node.update_last_used_fingerprint()


def test_update_last_used_fingerprint_create_intermediate_dirs(root_path_populated_with_config: Path) -> None:
    root_path: Path = root_path_populated_with_config
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    node.logged_in_fingerprint = 9876543210
    path = node.get_last_used_fingerprint_path()

    assert path.parent.exists() is False

    node.update_last_used_fingerprint()

    assert path.parent.exists() is True


def test_update_last_used_fingerprint(root_path_populated_with_config: Path) -> None:
    root_path: Path = root_path_populated_with_config
    config: Dict[str, Any] = load_config(root_path, "config.yaml", "wallet")
    node: WalletNode = WalletNode(config, root_path, test_constants)
    node.logged_in_fingerprint = 9876543210
    path = node.get_last_used_fingerprint_path()

    node.update_last_used_fingerprint()

    assert path.exists() is True
    assert path.read_text() == "9876543210"


@pytest.mark.asyncio
async def test_unique_puzzle_hash_subscriptions(simulator_and_wallet: SimulatorsAndWallets) -> None:
    _, [(node, _)], bt = simulator_and_wallet
    puzzle_hashes = await node.get_puzzle_hashes_to_subscribe()
    assert len(puzzle_hashes) > 1
    assert len(set(puzzle_hashes)) == len(puzzle_hashes)


@pytest.mark.asyncio
async def test_get_balance(
    simulator_and_wallet: SimulatorsAndWallets, self_hostname: str, default_400_blocks: List[FullBlock]
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
    for block in default_400_blocks:
        await full_node_api.full_node.add_block(block)

    # Initially there should be no sync and no balance
    assert not wallet_synced()
    assert await wallet_node.get_balance(wallet_id) == Balance()
    # Generate some funds, get the balance and make sure it's as expected
    await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
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
    wallet_node.local_keychain.add_private_key(other_key.mnemonic_str())
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
    await wallet_server.start_client(PeerInfo(self_hostname, uint16(full_node_server._port)), None)
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
