from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from blspy import PrivateKey

from chia.util.config import load_config
from chia.util.keychain import Keychain, generate_mnemonic
from chia.wallet.wallet_node import WalletNode
from tests.setup_nodes import test_constants


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

    node.log_out()  # type: ignore

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
