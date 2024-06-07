from __future__ import annotations

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

try:
    from keyrings.cryptfile.cryptfile import CryptFileKeyring
except ImportError:
    if sys.platform == "linux":
        raise

from chia.legacy.keyring import create_legacy_keyring, generate_and_add, get_keys, legacy_keyring


def show() -> Result:
    return CliRunner().invoke(legacy_keyring, ["show"])


def clear(input_str: str) -> Result:
    return CliRunner().invoke(legacy_keyring, ["clear"], input=f"{input_str}\n")


@pytest.mark.skipif(sys.platform == "win32" or sys.platform == "darwin", reason="Tests the linux legacy keyring format")
def test_legacy_keyring_format(tmp_dir: Path) -> None:
    keyring = CryptFileKeyring()
    keyring.keyring_key = "your keyring password"
    # Create the legacy keyring file with the old format
    keyring.file_path = tmp_dir / "keyring"
    keyring.filename = keyring.file_path.name
    keyring_data = """
    [chia_2Duser_2Dchia_2D1_2E8]
    wallet_2duser_2dchia_2d1_2e8_2d0 =
            eyJzYWx0IjogIi9NY3J3UG9iQjdiclpQMGRHclZiU1E9PSIsICJkYXRhIjogIjBnMEROUzRDSGdJ
            NU4yVEFYUVVhaExFY2RzN0NFR05rNnpKSmNLcWY5VmdOb2h6SkdxcUlOZzNKaTBEa3NIOGh3aHlM
            cG1GeFZVYWRcbmRtMTVWMDlsU3I1b3dNZDZHY3JGQTJHckZtZGszUmFmY0ZicmhlMmlRMjMzRW1P
            c28zQUxNbG5CcGtWTlR0cHZYYjlzbEp4VE5yVVVcbm8xUE0wNytTa1lJTHVzcmlNUStkUjBIQkxZ
            WXF3VjBUVndETHVKZmdtNWdyd1hrUkdkUjdvU0VyVTJUcnRnPT0iLCAibWFjIjogInA4MWJFTXhJ
            ay83bm1iMDMxR0NpZnc9PSIsICJub25jZSI6ICJzcUhoTUhOMkZQeTQxR3U4em40MXhBPT0ifQ==
    wallet_2duser_2dchia_2d1_2e8_2d1 =
            eyJzYWx0IjogIjNhWkFCQXBCcXUxdzI5WHpJcXBzS3c9PSIsICJkYXRhIjogImZwU05ZYk5WMmJM
            Vms5MjB6cGYzdzYrK2ZMc2w4b3Y4OU9uTWdHNlo4OXhzenRoc0tFZjdieHVKVGRyT3JmYmtBUmgv
            TzhzY3R1R2ZcblR1REVIOHJHNVA3RGpOWWQ3dFhxd2xabkg1VTVnV2VCNzZPaXdmVDQxQytxWlVX
            RXQ5L1dnMTQybHdqMy8vR2pJZ0w2d2Q0QXQyWjBcbmtQQVNOMnVnVmZpa0RiZGFaN21oeFRxNnRK
            TEszQWtLU3VPVmJyWEplbjZ2OGhXcGNMVU1HN3RIZENWNU5nPT0iLCAibWFjIjogIitPS3h1ZjZQ
            RzArdTA2Z2Qzb2dSNGc9PSIsICJub25jZSI6ICIxdWR2N1JIajhWaER2UWpVSjRJLzZnPT0ifQ==
    """
    with open(str(keyring.file_path), "w") as keyring_file:
        keyring_file.write(keyring_data)
    # Make sure the loaded keys match the file content
    keys = get_keys(keyring)
    assert len(keys) == 2
    assert keys[0].fingerprint == 1925978301
    assert keys[1].fingerprint == 2990446712


def test_legacy_keyring_cli() -> None:
    keyring = create_legacy_keyring()
    result = show()
    assert result.exit_code == 1
    assert "No keys found in the legacy keyring." in result.output
    keys = []
    for i in range(5):
        keys.append(generate_and_add(keyring))
        result = show()
        assert result.exit_code == 0
        for key in keys:
            assert key.mnemonic_str() in result.output

    # Should abort if the prompt gets a `n`
    result = clear("n")
    assert result.exit_code == 1
    assert "Aborted" in result.output

    # And succeed if the prompt gets a `y`
    result = clear("y")
    assert result.exit_code == 0
    for key in keys:
        assert key.mnemonic_str() in result.output
    assert f"{len(keys)} keys removed" in result.output
