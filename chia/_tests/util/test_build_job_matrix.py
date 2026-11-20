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
    assert "util 1/4" in names
    assert "util 2/4" in names
    assert "util 3/4" in names
    assert "util 4/4" in names
    assert "core.full_node 1/4" in names
    assert "core.full_node 2/4" in names
    assert "core.full_node 3/4" in names
    assert "core.full_node 4/4" in names
    assert "wallet.sync 1/2" in names
    assert "wallet.sync 2/2" in names
    assert "clvm+core.ssl+solver+tools" in names
    assert "rpc" not in names
    assert "clvm" not in names

    by_module = {entry["module_import_path"]: entry for entry in matrix}
    full_node = [entry for entry in matrix if entry["module_import_path"] == "core.full_node"]
    assert len(full_node) == 4
    split_rows = [
        entry for entry in full_node if "test_full_node.py::" in entry["test_files"] and "=" in entry["test_files"]
    ]
    assert len(split_rows) == 2
    assert all("-p chia._tests.matrix_shard" in entry["test_files"] for entry in split_rows)
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
    assert all("test_wallet_sync.py::" in entry["test_files"] for entry in wallet_sync)
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


def test_explicit_shards_put_unlisted_files_on_the_last_shard() -> None:
    from chia._tests.matrix_shard import TestFile, plan_explicit

    files = [
        TestFile("heavy.py", "pkg.heavy", "pkg/heavy.py"),
        TestFile("other.py", "pkg.other", "pkg/other.py"),
        TestFile("new.py", "pkg.new", "pkg/new.py"),
    ]
    shards = plan_explicit(files, [["heavy.py=0/2"], ["heavy.py=1/2"]])
    assert [piece.filename for piece in shards[0]] == ["heavy.py"]
    assert [piece.filename for piece in shards[1]] == ["heavy.py", "new.py", "other.py"]
    assert shards[1][0].part_index == 1


def test_explicit_function_shards_add_remainder_to_last_shard() -> None:
    from chia._tests.matrix_shard import TestFile, plan_explicit

    files = [
        TestFile("slow.py", "pkg.slow", "pkg/slow.py"),
        TestFile("other.py", "pkg.other", "pkg/other.py"),
        TestFile("new.py", "pkg.new", "pkg/new.py"),
    ]
    shards = plan_explicit(
        files,
        [
            ["slow.py::test_parser"],
            ["slow.py::test_header_block"],
            ["other.py"],
        ],
    )
    assert [piece.selector for piece in shards[0]] == ["test_parser"]
    assert [piece.selector for piece in shards[1]] == ["test_header_block"]
    assert {piece.filename for piece in shards[2]} == {"slow.py", "other.py", "new.py"}
    remainder = next(piece for piece in shards[2] if piece.filename == "slow.py")
    assert remainder.selector == "~test_parser,~test_header_block"
    assert remainder.whole
    assert all(piece.filename != "slow.py" or piece.selector is not None for piece in shards[2])


def test_explicit_function_shards_reject_duplicates_and_mixed_entries() -> None:
    from chia._tests.matrix_shard import TestFile, plan_explicit

    files = [TestFile("slow.py", "pkg.slow", "pkg/slow.py")]
    for shard_lists in (
        [["slow.py::test_parser"], ["slow.py::test_parser"]],
        [["slow.py::test_parser"], ["slow.py"]],
        [["slow.py::test_parser=0/2"], ["slow.py::test_parser=0/2"]],
        [["slow.py::test_parser"], ["slow.py=0/2"], ["slow.py=1/2"]],
    ):
        try:
            plan_explicit(files, shard_lists)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid function shards were accepted: {shard_lists}")


def test_explicit_sliced_remainder_plans_both_parts() -> None:
    from chia._tests.matrix_shard import TestFile, plan_explicit, render_test_files

    files = [
        TestFile("slow.py", "pkg.slow", "pkg/slow.py"),
        TestFile("other.py", "pkg.other", "pkg/other.py"),
    ]
    shards = plan_explicit(
        files,
        [
            ["slow.py::test_parser"],
            ["slow.py::~test_parser=0/2"],
            ["slow.py::~test_parser=1/2"],
        ],
    )
    assert [piece.selector for piece in shards[0]] == ["test_parser"]
    assert [(piece.part_index, piece.part_count) for piece in shards[1]] == [(0, 2)]
    assert [piece.selector for piece in shards[1]] == ["~test_parser"]
    slow_last = next(piece for piece in shards[2] if piece.filename == "slow.py")
    assert (slow_last.part_index, slow_last.part_count) == (1, 2)
    assert slow_last.selector == "~test_parser"
    slow_pieces = [piece for pieces in shards for piece in pieces if piece.filename == "slow.py"]
    assert len(slow_pieces) == 3
    assert [piece.selector for piece in slow_pieces].count("~test_parser") == 2
    assert "pkg/slow.py::~test_parser=0/2" in render_test_files(shards[1])
    assert "pkg/slow.py::~test_parser=1/2" in render_test_files(shards[2])


def test_assert_file_partition_accepts_sliced_remainder() -> None:
    from chia._tests.matrix_shard import TestFile, assert_file_partition, plan_explicit, render_test_files

    files = [
        TestFile("slow.py", "pkg.slow", "pkg/slow.py"),
        TestFile("other.py", "pkg.other", "pkg/other.py"),
    ]
    shards = plan_explicit(
        files,
        [
            ["slow.py::test_parser"],
            ["slow.py::~test_parser=0/2"],
            ["slow.py::~test_parser=1/2"],
        ],
    )
    rows = [render_test_files(pieces) for pieces in shards]
    assert_file_partition(["pkg/slow.py", "pkg/other.py"], rows)

    incomplete = [
        render_test_files([piece for piece in pieces if not (piece.filename == "slow.py" and piece.part_index == 1)])
        for pieces in shards
    ]
    try:
        assert_file_partition(["pkg/slow.py", "pkg/other.py"], incomplete)
    except AssertionError:
        pass
    else:
        raise AssertionError("incomplete sliced remainder was accepted")


def test_explicit_sliced_remainder_rejects_incomplete_or_mismatched_parts() -> None:
    from chia._tests.matrix_shard import Piece, TestFile, assert_file_partition, plan_explicit, render_test_files

    files = [TestFile("slow.py", "pkg.slow", "pkg/slow.py")]
    for shard_lists in (
        [["slow.py::~test_parser=0/2"]],
        [["slow.py::test_parser"], ["slow.py::~test_header_block=0/2"], ["slow.py::~test_header_block=1/2"]],
        [["slow.py::~test_parser=0/1"], ["slow.py::~test_header_block=0/1"]],
        [
            ["slow.py::test_parser"],
            ["slow.py::~test_parser,~test_header_block=0/2"],
            ["slow.py::~test_parser,~test_header_block=1/2"],
        ],
    ):
        try:
            plan_explicit(files, shard_lists)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid sliced remainder shards were accepted: {shard_lists}")

    over_broad_rows = [
        render_test_files([Piece("slow.py", "pkg.slow", "pkg/slow.py", 0, 1, "test_parser")]),
        render_test_files([Piece("slow.py", "pkg.slow", "pkg/slow.py", 0, 2, "~test_parser,~test_header_block")]),
        render_test_files([Piece("slow.py", "pkg.slow", "pkg/slow.py", 1, 2, "~test_parser,~test_header_block")]),
    ]
    try:
        assert_file_partition(["pkg/slow.py"], over_broad_rows)
    except AssertionError:
        pass
    else:
        raise AssertionError("over-broad remainder was accepted")


def test_filter_nodeids_sliced_remainder_covers_each_item_once() -> None:
    from chia._tests.matrix_shard import filter_nodeids

    path = "chia/_tests/util/test_slow.py"
    nodeids = [
        f"{path}::test_a",
        f"{path}::test_b[0]",
        f"{path}::test_b[1]",
        f"{path}::test_c[0]",
        f"{path}::test_d[0]",
        f"{path}::test_d[1]",
        f"{path}::test_d[2]",
    ]
    specs = [
        [f"{path}::test_a"],
        [f"{path}::~test_a=0/2"],
        [f"{path}::~test_a=1/2"],
    ]
    covered: list[str] = []
    for spec in specs:
        covered.extend(filter_nodeids(nodeids, spec))
    assert sorted(covered) == sorted(nodeids)
    assert len(set(covered)) == len(covered)


def test_only_packed_directory_stays_unpacked() -> None:
    matrix = json.loads(run(args=["--per", "directory", "--only", "clvm"]))
    assert [entry["name"] for entry in matrix] == ["clvm"]


def test_installed_nodeids_split_and_a_miss_raises() -> None:
    from chia._tests.matrix_shard import filter_nodeids

    prefix = ".venv/lib/python3.12/site-packages/"
    nodeids = [f"{prefix}chia/_tests/wallet/sync/test_wallet_sync.py::test_{index}" for index in range(4)]
    first = filter_nodeids(nodeids, ["chia/_tests/wallet/sync/test_wallet_sync.py=0/2"])
    second = filter_nodeids(nodeids, ["chia/_tests/wallet/sync/test_wallet_sync.py=1/2"])
    assert first + second == nodeids
    assert len(first) == 2
    try:
        filter_nodeids(nodeids, ["chia/_tests/wallet/sync/test_missing.py=0/2"])
    except ValueError as exc:
        assert "matched no collected tests" in str(exc)
    else:
        raise AssertionError("missing shard file did not fail")


def test_filter_nodeids_function_selectors_and_remainder() -> None:
    from chia._tests.matrix_shard import filter_nodeids

    prefix = ".venv/Lib/site-packages/"
    path = "chia/_tests/util/test_full_block_utils.py"
    nodeids = [
        f"{prefix}{path}::test_fast_0",
        f"{prefix}{path}::test_fast_1",
        f"{prefix}{path}::test_parser[0]",
        f"{prefix}{path}::test_parser[1]",
        f"{prefix}{path}::test_header_block[0]",
        f"{prefix}{path}::test_header_block[1]",
    ]
    parser = filter_nodeids(nodeids, [f"{path}::test_parser"])
    header = filter_nodeids(nodeids, [f"{path}::test_header_block"])
    remainder = filter_nodeids(nodeids, [f"{path}::~test_parser,~test_header_block"])
    assert parser == nodeids[2:4]
    assert header == nodeids[4:6]
    assert remainder == nodeids[0:2]
    combined = parser + header + remainder
    assert sorted(combined) == sorted(nodeids)
    assert len(set(combined)) == len(combined)

    bare = ["::test_fast", "::test_parser[0]", "::test_header_block[0]"]
    windows_path = "C:\\work\\" + path.replace("/", "\\")
    windows_paths = [windows_path] * len(bare)
    assert filter_nodeids(bare, [f"{path}::test_parser"], windows_paths) == ["::test_parser[0]"]
    assert filter_nodeids(bare, [f"{path}::~test_parser,~test_header_block"], windows_paths) == ["::test_fast"]

    try:
        filter_nodeids(nodeids, [f"{path}::test_missing"])
    except ValueError as exc:
        assert "matched no collected tests" in str(exc)
    else:
        raise AssertionError("missing function did not fail")


def test_matrix_shard_plugin_pyargs_function_selectors(tmp_path: pathlib.Path) -> None:
    import os
    import sys

    package_root = tmp_path / "site-packages"
    test_dir = package_root / "pkg"
    test_dir.mkdir(parents=True)
    (test_dir / "__init__.py").write_text("")
    (test_dir / "test_split.py").write_text(
        "import pytest\n\n"
        "@pytest.mark.parametrize('value', [0, 1])\n"
        "def test_parser(value):\n    assert True\n\n"
        "@pytest.mark.parametrize('value', [0, 1])\n"
        "def test_header_block(value):\n    assert True\n\n"
        "def test_fast_0():\n    assert True\n\n"
        "def test_fast_1():\n    assert True\n"
    )
    work = tmp_path / "work"
    work.mkdir()
    repo_root = build_job_matrix_path.parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(package_root), str(repo_root), env.get("PYTHONPATH", "")])
    specs = [
        "pkg/test_split.py::test_parser",
        "pkg/test_split.py::test_header_block",
        "pkg/test_split.py::~test_parser,~test_header_block",
    ]
    collected: list[set[str]] = []
    for spec in specs:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "chia._tests.matrix_shard",
                "--matrix-shard",
                spec,
                "--pyargs",
                "pkg.test_split",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                "-o",
                "addopts=",
            ],
            check=False,
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        collected.append({line.strip().split("::", 1)[1] for line in completed.stdout.splitlines() if "::" in line})
    all_nodeids = {"test_fast_0", "test_fast_1"}
    all_nodeids |= {f"test_parser[{value}]" for value in (0, 1)}
    all_nodeids |= {f"test_header_block[{value}]" for value in (0, 1)}
    assert collected[0] == {f"test_parser[{value}]" for value in (0, 1)}
    assert collected[1] == {f"test_header_block[{value}]" for value in (0, 1)}
    assert collected[2] == {f"test_fast_{value}" for value in (0, 1)}
    assert set().union(*collected) == all_nodeids
    assert sum(len(group) for group in collected) == len(all_nodeids)


def test_matrix_shard_plugin_pyargs_outside_source_tree(tmp_path: pathlib.Path) -> None:
    """CI collects installed tests with --pyargs after the source tree is moved aside."""
    import os
    import sys

    package_root = tmp_path / "site-packages"
    test_dir = package_root / "pkg"
    test_dir.mkdir(parents=True)
    (test_dir / "__init__.py").write_text("")
    (test_dir / "test_split.py").write_text(
        "def test_0():\n    assert True\n\ndef test_1():\n    assert True\n\n"
        "def test_2():\n    assert True\n\ndef test_3():\n    assert True\n"
    )
    work = tmp_path / "work"
    work.mkdir()
    repo_root = build_job_matrix_path.parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(package_root), str(repo_root), env.get("PYTHONPATH", "")])
    collected: list[str] = []
    for part in (0, 1):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "chia._tests.matrix_shard",
                "--matrix-shard",
                f"pkg/test_split.py={part}/2",
                "--pyargs",
                "pkg.test_split",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                "-o",
                "addopts=",
            ],
            check=False,
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        collected.append(completed.stdout)
    assert "test_0" in collected[0] and "test_1" in collected[0]
    assert "test_2" in collected[1] and "test_3" in collected[1]
    assert "test_2" not in collected[0]
    assert "test_0" not in collected[1]


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
