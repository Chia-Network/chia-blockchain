from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

import chia._tests

build_job_matrix_path = pathlib.Path(chia._tests.__file__).with_name("build-job-matrix.py")


def run(args: list[str], script_path: pathlib.Path = build_job_matrix_path) -> str:
    completed_process = subprocess.run(
        [sys.executable, script_path, *args],
        check=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    )
    return completed_process.stdout


@pytest.mark.parametrize("per", ["directory", "file"])
@pytest.mark.parametrize("checkout_directory", ["work", "_work", ".work"])
def test_checkout_path(tmp_path: pathlib.Path, per: str, checkout_directory: str) -> None:
    test_root = tmp_path / checkout_directory / "chia" / "_tests"
    test_root.mkdir(parents=True)
    script_path = test_root / build_job_matrix_path.name
    shutil.copyfile(build_job_matrix_path, script_path)
    shutil.copyfile(build_job_matrix_path.with_name("testconfig.py"), test_root / "testconfig.py")
    shutil.copyfile(build_job_matrix_path.with_name("matrix_shard.py"), test_root / "matrix_shard.py")
    for directory in ["example", "_excluded", ".excluded"]:
        test_directory = test_root / directory
        test_directory.mkdir()
        (test_directory / "test_example.py").touch()

    matrix = json.loads(run(args=["--per", per], script_path=script_path))

    expected_name = "example" if per == "directory" else "example.test_example"
    assert [entry["name"] for entry in matrix] == [expected_name]


def test() -> None:
    timeouts: dict[int, dict[str, int]] = {}

    multipliers = [1, 2, 3]

    for multiplier in multipliers:
        timeouts[multiplier] = {}
        output = run(args=["--per", "directory", "--timeout-multiplier", str(multiplier)])
        matrix = json.loads(output)
        for entry in matrix:
            timeouts[multiplier][entry["name"]] = entry["job_timeout"]

    reference = timeouts[1]

    for multiplier in multipliers:
        if multiplier == 1:
            continue

        adjusted_reference = {key: value * multiplier for key, value in reference.items()}
        assert timeouts[multiplier] == adjusted_reference


def test_shard_and_pack_partition() -> None:
    """Every test file is in the matrix once. Split files contribute each part once."""
    from chia._tests.matrix_shard import assert_file_partition

    root = build_job_matrix_path.parent
    expected: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        relative = path.relative_to(root)
        if any(part.startswith(("_", ".")) and part != "_tests" for part in relative.parts):
            continue
        expected.append(path.relative_to(root.parent.parent).as_posix())

    matrix = json.loads(run(args=["--per", "directory"]))
    assert_file_partition(expected, [entry["test_files"] for entry in matrix])

    names = [entry["name"] for entry in matrix]
    assert len(names) == len(set(names))
    assert "util 1/3" in names
    assert "util 2/3" in names
    assert "util 3/3" in names
    assert "core.full_node 1/3" in names
    assert "wallet.sync 1/2" in names
    assert "wallet.sync 2/2" in names
    assert "clvm+core.ssl+solver+tools" in names
    assert "rpc" not in names
    assert "clvm" not in names

    by_module = {entry["module_import_path"]: entry for entry in matrix}
    full_node = [entry for entry in matrix if entry["module_import_path"] == "core.full_node"]
    assert len(full_node) == 3
    assert any("test_full_node.py=0/2" in entry["test_files"] for entry in full_node)
    assert any("test_full_node.py=1/2" in entry["test_files"] for entry in full_node)
    assert {entry["job_timeout"] for entry in full_node} == {110}
    assert all(entry["checkout_blocks_and_plots"] for entry in full_node)
    assert all(entry["install_timelord"] is False for entry in full_node)

    simulation = [entry for entry in matrix if entry["module_import_path"] == "simulation"]
    assert len(simulation) == 2
    assert all(entry["install_timelord"] is True for entry in simulation)
    assert all(entry["pytest_parallel_args"]["ubuntu"] == " -n 0" for entry in simulation)

    data_layer = [entry for entry in matrix if entry["module_import_path"] == "core.data_layer"]
    assert len(data_layer) == 2
    assert {entry["pytest_parallel_args"]["macos"] for entry in data_layer} == {" -n 4"}
    assert {entry["job_timeout"] for entry in data_layer} == {80}

    packed = by_module["clvm+core.ssl+solver+tools"]
    assert packed["job_timeout"] == 70
    assert packed["checkout_blocks_and_plots"] is True
    assert packed["install_timelord"] is False
    assert "chia._tests.solver." in packed["test_files"]
    assert "chia._tests.clvm." in packed["test_files"]

    wallet_sync = [entry for entry in matrix if entry["module_import_path"] == "wallet.sync"]
    assert len(wallet_sync) == 2
    assert all("test_wallet_sync.py=" in entry["test_files"] for entry in wallet_sync)
    assert {entry["job_timeout"] for entry in wallet_sync} == {60}


# Mirrors the OS excludes in .github/workflows/test-single.yml. Python 3.12 is the
# only version in matrix_mode main/limited; mode all keeps 3.11, 3.12, 3.13, 3.14.
_OS_EXCLUDES = {
    "macos-intel": {"arch": "intel", "os": "macos-intel"},
    "macos-arm": {"arch": "arm", "os": "macos"},
    "ubuntu-intel": {"arch": "intel", "os": "ubuntu"},
    "ubuntu-arm": {"arch": "arm", "os": "ubuntu"},
    "windows": {"arch": "intel", "os": "windows"},
}


def _os_keeps(entry: dict[str, object], os_name: str) -> bool:
    spec = _OS_EXCLUDES[os_name]
    timelord = bool(entry["install_timelord"])
    if spec["arch"] == "arm" and timelord:
        return False
    if os_name == "windows" and timelord:
        return False
    if os_name == "macos-intel" and timelord:
        return False
    return not (os_name == "windows" and entry["module_import_path"] == "core.full_node")


def configuration_counts(matrix: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for os_name in _OS_EXCLUDES:
        configs = sum(1 for entry in matrix if _os_keeps(entry, os_name))
        counts[os_name] = {"configs": configs, "main": configs, "all": configs * 4}
    return counts


def test_configuration_counts_stay_under_matrix_limit() -> None:
    matrix = json.loads(run(args=["--per", "directory"]))
    counts = configuration_counts(matrix)
    for os_name, row in counts.items():
        assert row["configs"] <= 60, os_name
        assert row["all"] <= 256, os_name
        assert row["main"] == row["configs"]


def test_duration_balance_splits_heavy_file_across_shards() -> None:
    from chia._tests.matrix_shard import TestFile, plan_duration_balanced

    files = [
        TestFile("heavy.py", "pkg.heavy", "pkg/heavy.py"),
        TestFile("medium.py", "pkg.medium", "pkg/medium.py"),
        TestFile("light_a.py", "pkg.light_a", "pkg/light_a.py"),
        TestFile("light_b.py", "pkg.light_b", "pkg/light_b.py"),
        TestFile("light_c.py", "pkg.light_c", "pkg/light_c.py"),
        TestFile("light_d.py", "pkg.light_d", "pkg/light_d.py"),
    ]
    # total 320, target ~106.7. 200 is heavy enough to split in two, not three.
    weights = {
        "heavy.py": 200.0,
        "medium.py": 40.0,
        "light_a.py": 20.0,
        "light_b.py": 20.0,
        "light_c.py": 20.0,
        "light_d.py": 20.0,
    }
    shards = plan_duration_balanced(files, 3, weights)
    assert len(shards) == 3
    parts = [piece for shard in shards for piece in shard if piece.filename == "heavy.py"]
    assert sorted((piece.part_index, piece.part_count) for piece in parts) == [(0, 2), (1, 2)]
    assert sum(1 for shard in shards if any(piece.filename == "heavy.py" for piece in shard)) == 2


def test_filter_nodeids_covers_each_item_once() -> None:
    from chia._tests.matrix_shard import filter_nodeids, shard_bounds

    nodeids = [f"chia/_tests/wallet/sync/test_wallet_sync.py::test_{index}" for index in range(5)]
    nodeids.append("chia/_tests/wallet/sync/test_other.py::test_keep")
    specs = [
        ["chia/_tests/wallet/sync/test_wallet_sync.py=0/2"],
        ["chia/_tests/wallet/sync/test_wallet_sync.py=1/2"],
    ]
    covered: list[str] = []
    for spec in specs:
        covered.extend(filter_nodeids(nodeids, spec))
    assert sorted(covered) == sorted([*nodeids, "chia/_tests/wallet/sync/test_other.py::test_keep"])
    assert covered.count("chia/_tests/wallet/sync/test_other.py::test_keep") == 2

    for n_items in range(12):
        for part_count in range(1, 6):
            got: list[int] = []
            for part_index in range(part_count):
                start, end = shard_bounds(n_items, part_count, part_index)
                got.extend(range(start, end))
            assert got == list(range(n_items))
