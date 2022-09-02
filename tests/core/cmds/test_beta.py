import zipfile
from pathlib import Path
from typing import Callable, Optional

import pytest
from click.testing import CliRunner, Result

from chia.cmds.beta_funcs import default_beta_root_path
from chia.cmds.chia import cli
from chia.util.config import lock_and_load_config, save_config


def configure(root_path: Path, *args: str) -> Result:
    return CliRunner().invoke(
        cli,
        [
            "--root-path",
            str(root_path),
            "beta",
            "configure",
            *args,
        ],
    )


def configure_interactive(root_path: Path, user_input: Optional[str] = None) -> Result:
    return CliRunner().invoke(
        cli,
        [
            "--root-path",
            str(root_path),
            "beta",
            "configure",
        ],
        input=user_input,
    )


def enable(root_path: Path, *args: str) -> Result:
    return CliRunner().invoke(
        cli,
        [
            "--root-path",
            str(root_path),
            "beta",
            "enable",
            "--force",
            *args,
        ],
    )


def enable_interactive(root_path: Path, user_input: Optional[str] = None) -> Result:
    return CliRunner().invoke(
        cli,
        [
            "--root-path",
            str(root_path),
            "beta",
            "enable",
        ],
        input=user_input,
    )


def prepare_submission(root_path: Path, user_input: Optional[str] = None) -> Result:
    return CliRunner().invoke(
        cli,
        [
            "--root-path",
            str(root_path),
            "beta",
            "prepare_submission",
        ],
        input=user_input,
    )


def generate_example_submission_data(beta_root_path: Path, versions: int, logs: int) -> None:
    for version in range(versions):
        version_path = beta_root_path / str(version)
        version_path.mkdir()
        chia_blockchain_logs = version_path / "chia-blockchain"
        plotting_logs = version_path / "plotting"
        chia_blockchain_logs.mkdir()
        plotting_logs.mkdir()
        for i in range(logs):
            with open(chia_blockchain_logs / f"beta_{i}.log", "w"):
                pass
            with open(chia_blockchain_logs / f"beta_{i + 10}.gz", "w"):
                pass
            with open(plotting_logs / f"plot_{i}.log", "w"):
                pass


def generate_beta_config(root_path: Path, enabled: bool, beta_path: Path) -> None:
    with lock_and_load_config(root_path, "config.yaml") as config:
        config["beta"] = {
            "enabled": enabled,
            "path": str(beta_path),
        }
        save_config(root_path, "config.yaml", config)


@pytest.mark.parametrize("option", ["--path", "-p"])
def test_configure(root_path_populated_with_config: Path, option: str) -> None:
    root_path = root_path_populated_with_config
    beta_path = root_path / "beta"
    beta_path.mkdir()
    generate_beta_config(root_path, True, beta_path)

    result = configure(root_path, option, str(beta_path))
    assert result.exit_code == 0

    with lock_and_load_config(root_path, "config.yaml") as config:
        assert config["beta"] == {
            "enabled": True,
            "path": str(beta_path),
        }


def test_configure_no_beta_config(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config
    beta_path = root_path / "beta"
    beta_path.mkdir()
    with lock_and_load_config(root_path, "config.yaml") as config:
        assert "beta" not in config

    result = configure(root_path, "--path", str(beta_path))
    assert result.exit_code == 1
    assert "beta test mode is not enabled, enable it first with `chia beta enable`" in result.output


@pytest.mark.parametrize("accept_existing_path", [True, False])
def test_beta_configure_interactive(root_path_populated_with_config: Path, accept_existing_path: bool) -> None:
    root_path = root_path_populated_with_config
    beta_path = root_path / "beta"
    generate_beta_config(root_path, True, root_path_populated_with_config)

    result = configure_interactive(root_path, f"{'' if accept_existing_path else str(beta_path)}\ny\n")
    assert result.exit_code == 0
    assert "beta config updated" in result.output

    with lock_and_load_config(root_path, "config.yaml") as config:
        assert config["beta"] == {
            "enabled": True,
            "path": str(root_path_populated_with_config if accept_existing_path else beta_path),
        }


@pytest.mark.parametrize("option", ["--path", "-p"])
def test_beta_enable(root_path_populated_with_config: Path, option: str) -> None:
    root_path = root_path_populated_with_config
    beta_path = root_path / "beta"
    beta_path.mkdir()
    with lock_and_load_config(root_path, "config.yaml") as config:
        assert "beta" not in config

    result = enable(root_path, option, str(beta_path))
    assert result.exit_code == 0
    assert f"beta test mode enabled with path {str(beta_path)!r}" in result.output

    with lock_and_load_config(root_path, "config.yaml") as config:
        assert config["beta"] == {
            "enabled": True,
            "path": str(beta_path),
        }


@pytest.mark.parametrize("enabled", [True, False])
def test_beta_enable_preconfigured(root_path_populated_with_config: Path, enabled: bool) -> None:
    root_path = root_path_populated_with_config
    beta_path = root_path / "beta"
    beta_path.mkdir()
    generate_beta_config(root_path, enabled, beta_path)

    result = enable_interactive(root_path, "y\n")

    if enabled:
        assert result.exit_code == 1
        assert "beta test mode is already enabled" in result.output
    else:
        assert result.exit_code == 0
        assert f"beta test mode enabled with path {str(beta_path)!r}" in result.output

    with lock_and_load_config(root_path, "config.yaml") as config:
        assert config["beta"] == {
            "enabled": True,
            "path": str(beta_path),
        }


@pytest.mark.parametrize("accept_default_path", [True, False])
def test_beta_enable_interactive(root_path_populated_with_config: Path, accept_default_path: bool) -> None:
    root_path = root_path_populated_with_config
    beta_path = root_path / "beta"
    with lock_and_load_config(root_path, "config.yaml") as config:
        assert "beta" not in config

    result = enable_interactive(root_path, f"y\n{'' if accept_default_path else str(beta_path)}\ny\n")
    assert result.exit_code == 0
    assert (
        f"beta test mode enabled with path {str(default_beta_root_path() if accept_default_path else beta_path)!r}"
        in result.output
    )

    with lock_and_load_config(root_path, "config.yaml") as config:
        assert config["beta"] == {
            "enabled": True,
            "path": str(default_beta_root_path() if accept_default_path else beta_path),
        }


def test_beta_enable_interactive_decline_warning(root_path_populated_with_config: Path) -> None:
    root_path = root_path_populated_with_config
    with lock_and_load_config(root_path, "config.yaml") as config:
        assert "beta" not in config

    result = enable_interactive(root_path, "n\n")
    assert result.exit_code == 1
    assert result.output[-9:-1] == "Aborted!"


@pytest.mark.parametrize("write_test", [True, False])
@pytest.mark.parametrize("command", [configure, enable])
def test_beta_invalid_directories(
    root_path_populated_with_config: Path, write_test: bool, command: Callable[[Path, str, str], Result]
) -> None:
    root_path = root_path_populated_with_config
    beta_path = root_path / "beta"
    if write_test:
        (beta_path / ".write_test").mkdir(parents=True)  # `.write_test` is used in  validate_directory_writable
    if command == configure:
        generate_beta_config(root_path, True, root_path_populated_with_config)
    result = command(root_path, "--path", str(beta_path))
    assert result.exit_code == 1
    if write_test:
        assert f"Directory not writable: {str(beta_path)!r}" in result.output
    else:
        assert f"Directory doesn't exist: {str(beta_path)!r}" in result.output


@pytest.mark.parametrize("enabled", [True, False])
def test_beta_disable(root_path_populated_with_config: Path, enabled: bool) -> None:
    root_path = root_path_populated_with_config
    beta_path = root_path / "beta"
    generate_beta_config(root_path, enabled, beta_path)

    result = CliRunner().invoke(
        cli,
        [
            "--root-path",
            str(root_path),
            "beta",
            "disable",
        ],
    )
    if enabled:
        assert result.exit_code == 0
        assert "beta test mode disabled" in result.output
    else:
        assert result.exit_code == 1
        assert "beta test mode is not enabled" in result.output

    with lock_and_load_config(root_path, "config.yaml") as config:
        assert config["beta"] == {
            "enabled": False,
            "path": str(beta_path),
        }


@pytest.mark.parametrize(
    "versions, logs, choice, exit_code, output",
    [
        (0, 0, 1, 1, "No beta logs found"),
        (1, 0, 1, 1, "No logs files found"),
        (2, 10, 3, 1, "Invalid choice: 3"),
        (2, 10, 0, 1, "Invalid choice: 0"),
        (2, 10, -1, 1, "Invalid choice: -1"),
        (4, 3, 2, 0, "Done. You can find the prepared submission data"),
    ],
)
def test_prepare_submission(
    root_path_populated_with_config: Path, versions: int, logs: int, choice: int, exit_code: int, output: str
) -> None:
    root_path = root_path_populated_with_config
    beta_path = root_path / "beta"
    beta_path.mkdir()
    generate_beta_config(root_path, True, beta_path)

    generate_example_submission_data(beta_path, versions, logs)

    result = prepare_submission(root_path, f"{choice}\n")

    assert result.exit_code == exit_code
    assert output in result.output

    if exit_code == 0:
        submission_file = list(beta_path.rglob("*.zip"))[0]
        assert submission_file.name.startswith(f"submission_{choice - 1}")
        with zipfile.ZipFile(submission_file) as zip_file:
            all_files = [Path(info.filename) for info in zip_file.filelist]
            for version in range(versions):
                chia_blockchain_logs = Path("chia-blockchain")
                plotting_logs = Path("plotting")
                for i in range(logs):
                    assert chia_blockchain_logs / f"beta_{i}.log" in all_files
                    assert chia_blockchain_logs / f"beta_{i + 10}.gz" in all_files
                    assert plotting_logs / f"plot_{i}.log" in all_files


@pytest.mark.parametrize(
    "enabled, path",
    [
        (True, Path("path_1")),
        (False, Path("path_2")),
    ],
)
def test_beta_status(root_path_populated_with_config: Path, enabled: bool, path: Path) -> None:
    root_path = root_path_populated_with_config
    generate_beta_config(root_path, enabled, path)

    result = CliRunner().invoke(
        cli,
        [
            "--root-path",
            str(root_path),
            "beta",
            "status",
        ],
    )

    assert result.exit_code == 0
    assert f"enabled: {enabled}" in result.output
    assert f"path: {str(path)}" in result.output
