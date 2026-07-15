from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner, Result

from chia.cmds.chia import cli
from chia.util.config import lock_and_load_config


def run_configure(root_path: Path, *args: str) -> Result:
    return CliRunner().invoke(
        cli,
        [
            "--root-path",
            str(root_path),
            "configure",
            *args,
        ],
    )


def test_configure_log_systemd(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config

    # Test enabling systemd logging
    result = run_configure(root_path, "--log-systemd", "true")
    assert result.exit_code == 0
    assert "Systemd logging enabled" in result.output

    with lock_and_load_config(root_path, "config.yaml") as config:
        assert config["logging"]["log_systemd"] is True
        # Verify it also updated services (like farmer)
        assert config["farmer"]["logging"]["log_systemd"] is True

    # Test disabling systemd logging
    result = run_configure(root_path, "--log-systemd", "false")
    assert result.exit_code == 0
    assert "Systemd logging disabled" in result.output

    with lock_and_load_config(root_path, "config.yaml") as config:
        assert config["logging"]["log_systemd"] is False

    # Test with 't' and 'f'
    result = run_configure(root_path, "--log-systemd", "t")
    assert result.exit_code == 0
    assert "Systemd logging enabled" in result.output

    result = run_configure(root_path, "--log-systemd", "f")
    assert result.exit_code == 0
    assert "Systemd logging disabled" in result.output

    # Test invalid choice
    result = run_configure(root_path, "--log-systemd", "invalid")
    assert result.exit_code != 0
    assert "is not one of 'true', 't', 'false', 'f'" in result.output


def test_configure_log_level(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config

    # Test setting log_level to INFO
    result = run_configure(root_path, "--log-level", "INFO")
    assert result.exit_code == 0
    assert "Logging level updated" in result.output

    with lock_and_load_config(root_path, "config.yaml") as config:
        assert config["logging"]["log_level"] == "INFO"
        # Since we updated the code to set it for all services, check one service too
        if "farmer" in config and "logging" in config["farmer"]:
            assert config["farmer"]["logging"]["log_level"] == "INFO"

    # Test setting log_level to ERROR
    result = run_configure(root_path, "--log-level", "ERROR")
    assert result.exit_code == 0
    assert "Logging level updated" in result.output

    with lock_and_load_config(root_path, "config.yaml") as config:
        assert config["logging"]["log_level"] == "ERROR"
        if "farmer" in config and "logging" in config["farmer"]:
            assert config["farmer"]["logging"]["log_level"] == "ERROR"


def test_configure_invalid_log_level(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config
    # Click Choice handles this, but this verifies the CLI behavior
    result = run_configure(root_path, "--log-level", "INVALID")
    assert result.exit_code != 0
    assert "is not one of 'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET'" in result.output
