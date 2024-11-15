from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Callable

import click
import pytest
import yaml
from click.testing import CliRunner

from chia.util.virtual_project_analysis import (
    Annotation,
    ChiaFile,
    Config,
    DirectoryParameters,
    File,
    Package,
    build_dependency_graph,
    build_virtual_dependency_graph,
    cli,
    config,
    find_cycles,
    parse_file_or_package,
)


@pytest.mark.parametrize(
    "file_string, expected, annotated",
    [
        ("# Package: example\n# Some other comment", "example", True),
        ("# Some comment\n# Some other comment", "chia-blockchain", False),
    ],
)
def test_parse_annotation(file_string: str, expected: str, annotated: bool) -> None:
    """
    Test that parse returns an Annotation instance for a valid annotation or
    raises ValueError for an invalid one.
    """
    annotation = Annotation.parse(file_string)
    assert isinstance(annotation, Annotation)
    assert annotation.package == expected
    assert annotation.is_annotated == annotated


# Temporary directory fixture to create test files
@pytest.fixture
def create_test_file(tmp_path: Path) -> Callable[[str, str], Path]:
    def _create_test_file(name: str, content: str) -> Path:
        file_path = tmp_path / name
        file_path.write_text(content, encoding="utf-8")
        return file_path

    return _create_test_file


def test_parse_with_annotation(create_test_file: Callable[[str, str], Path]) -> None:
    """Test parsing a file that contains a valid annotation."""
    file_content = "# Package: test_package\n# Some other comment"
    test_file = create_test_file("annotated_file.txt", file_content)

    parsed_file = ChiaFile.parse(test_file)

    assert parsed_file.path == test_file
    assert isinstance(parsed_file.annotations, Annotation)
    assert parsed_file.annotations.package == "test_package"


def test_parse_without_annotation(create_test_file: Callable[[str, str], Path]) -> None:
    """Test parsing a file that does not contain any annotations."""
    file_content = "# Some comment\n# Some other comment"
    test_file = create_test_file("non_annotated_file.txt", file_content)

    parsed_file = ChiaFile.parse(test_file)

    assert parsed_file.path == test_file
    assert not parsed_file.annotations.is_annotated


# This test is optional and can be adapted based on expected behavior for non-existent files
def test_parse_nonexistent_file() -> None:
    """Test attempting to parse a non-existent file."""
    with pytest.raises(FileNotFoundError):
        ChiaFile.parse(Path("/path/to/nonexistent/file.txt"))


# Helper function to create a non-empty Python file
def create_python_file(dir_path: Path, name: str, content: str) -> Path:
    file_path = dir_path / name
    file_path.write_text(content, encoding="utf-8")
    return file_path


# Helper function to create an empty Python file
def create_empty_python_file(dir_path: Path, name: str) -> Path:
    file_path = dir_path / name
    file_path.touch()
    return file_path


def test_gather_non_empty_python_files(tmp_path: Path) -> None:
    # Set up directory structure
    dir_path = tmp_path / "test_dir"
    dir_path.mkdir()
    excluded_dir = tmp_path / "excluded_dir"
    excluded_dir.mkdir()

    # Create test files
    non_empty_file = create_python_file(dir_path, "non_empty.py", "print('Hello World')")
    create_empty_python_file(dir_path, "empty.py")
    create_python_file(excluded_dir, "excluded.py", "print('Hello World')")

    # Initialize DirectoryParameters with excluded paths
    dir_params = DirectoryParameters(dir_path=dir_path, excluded_paths=[excluded_dir])

    # Perform the test
    python_files = dir_params.gather_non_empty_python_files()

    # Assertions
    assert len(python_files) == 1  # Only one non-empty Python file should be found
    assert python_files[0].path == non_empty_file  # The path of the gathered file should match the non-empty file


def test_gather_with_nested_directories_and_exclusions(tmp_path: Path) -> None:
    # Set up directory structure
    base_dir = tmp_path / "base_dir"
    base_dir.mkdir()
    nested_dir = base_dir / "nested_dir"
    nested_dir.mkdir()
    excluded_dir = base_dir / "excluded_dir"
    excluded_dir.mkdir()

    # Create test files
    nested_file = create_python_file(nested_dir, "nested.py", "print('Hello World')")
    create_empty_python_file(nested_dir, "nested_empty.py")
    create_python_file(excluded_dir, "excluded.py", "print('Hello World')")

    # Initialize DirectoryParameters without excluded paths
    dir_params = DirectoryParameters(dir_path=base_dir, excluded_paths=[excluded_dir])

    # Perform the test
    python_files = dir_params.gather_non_empty_python_files()

    # Assertions
    assert len(python_files) == 1  # Only the non-empty Python file in the nested directory should be found
    assert python_files[0].path == nested_file  # The path of the gathered file should match the nested non-empty file


def test_find_missing_annotations(tmp_path: Path) -> None:
    # Set up directory structure
    dir_path = tmp_path / "test_dir"
    dir_path.mkdir()

    # Create test files
    create_python_file(dir_path, "non_empty.py", "print('Hello World')")

    # Run the command
    runner = CliRunner()
    result = runner.invoke(cli, ["find_missing_annotations", "--directory", str(dir_path)])
    assert result.output == f"{dir_path / 'non_empty.py'}\n"

    # Rewrite file to have annotation
    create_python_file(dir_path, "non_empty.py", "# Package: misc\n")

    # Run the command again with no results
    result = runner.invoke(cli, ["find_missing_annotations", "--directory", str(dir_path)])
    assert result.output == ""


def test_parse_file_or_package() -> None:
    assert parse_file_or_package("example.py") == File(Path("example.py"))
    assert parse_file_or_package("example.py (extra info)") == File(Path("example.py"))
    assert parse_file_or_package("(package_name)") == Package("package_name")
    assert parse_file_or_package("package_name") == Package("package_name")
    assert parse_file_or_package("package_name(") == Package("package_name(")
    assert parse_file_or_package("(package_name") == Package("(package_name")
    assert parse_file_or_package("package_name)") == Package("package_name)")


@pytest.fixture
def chia_package_structure(tmp_path: Path) -> Path:
    base_dir = tmp_path / "chia_project"
    base_dir.mkdir()
    chia_dir = base_dir / "chia"
    chia_dir.mkdir()

    # Create some files within the chia package
    create_python_file(chia_dir, "module1.py", "def func1(): pass")
    create_python_file(chia_dir, "module2.py", "def func2(): pass\nfrom chia.module1 import func1")
    create_python_file(chia_dir, "module3.py", "def func3(): pass\nimport chia.module2")

    return chia_dir


def test_build_dependency_graph(chia_package_structure: Path) -> None:
    chia_dir = chia_package_structure
    dir_params = DirectoryParameters(dir_path=chia_dir)
    graph = build_dependency_graph(dir_params)
    assert chia_dir / "module1.py" in graph
    assert chia_dir / "module2.py" in graph
    assert chia_dir / "module3.py" in graph
    assert chia_dir / "module1.py" in graph[chia_dir / "module2.py"]
    assert chia_dir / "module2.py" in graph[chia_dir / "module3.py"]


def test_print_dependency_graph(chia_package_structure: Path) -> None:
    # Run the command
    runner = CliRunner()
    result = runner.invoke(cli, ["print_dependency_graph", "--directory", str(chia_package_structure)])
    assert "module1.py" in result.output
    assert "module2.py" in result.output
    assert "module3.py" in result.output


# Mock the build_dependency_graph function to control its output
def mock_build_dependency_graph(dir_params: DirectoryParameters) -> dict[Path, list[Path]]:
    return {
        Path("/path/to/package1/module1.py"): [
            Path("/path/to/package2/module2.py"),
            Path("/path/to/package3/module3.py"),
        ],
        Path("/path/to/package2/module2.py"): [],
        Path("/path/to/package3/module3.py"): [Path("/path/to/package2/module2.py")],
    }


# Helper function to simulate ChiaFile.parse for testing
def mock_chia_file_parse(path: Path) -> ChiaFile:
    annotations_map = {
        Path("/path/to/package1/module1.py"): Annotation("Package1", True),
        Path("/path/to/package2/module2.py"): Annotation("Package2", True),
        Path("/path/to/package3/module3.py"): Annotation("Package3", True),
    }
    return ChiaFile(path=Path(path), annotations=annotations_map.get(path, Annotation("chia-blockchain", False)))


@pytest.fixture
def prepare_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("chia.util.virtual_project_analysis.build_dependency_graph", mock_build_dependency_graph)
    monkeypatch.setattr("chia.util.virtual_project_analysis.ChiaFile.parse", mock_chia_file_parse)


def test_build_virtual_dependency_graph(prepare_mocks: None) -> None:
    dir_params = DirectoryParameters(dir_path=Path("/path/to/package1"))
    virtual_graph = build_virtual_dependency_graph(dir_params)

    assert "Package2" in virtual_graph["Package1"]
    assert "Package3" in virtual_graph["Package1"]
    assert virtual_graph["Package2"] == []
    assert "Package2" in virtual_graph["Package3"]


def test_print_virtual_dependency_graph(tmp_path: Path) -> None:
    chia_dir = tmp_path / "chia"
    chia_dir.mkdir()

    # Create some files within the chia package
    create_python_file(chia_dir, "module1.py", "# Package: one\ndef func1(): pass")
    create_python_file(chia_dir, "module2.py", "# Package: two\ndef func2(): pass\nfrom chia.module1 import func1")
    create_python_file(chia_dir, "module3.py", "# Package: three\ndef func3(): pass\nimport chia.module2")

    # Run the command
    runner = CliRunner()
    result = runner.invoke(cli, ["print_virtual_dependency_graph", "--directory", str(chia_dir)])
    assert "one" in result.output
    assert "two" in result.output
    assert "three" in result.output


# Helper function to simulate ChiaFile.parse for testing
def mock_chia_file_parse2(path: Path) -> ChiaFile:
    annotations_map = {
        Path("/path/to/package1/module1.py"): Annotation("Package1", True),
        Path("/path/to/package2/module2.py"): Annotation("Package2", True),
        Path("/path/to/package3/module3.py"): Annotation("Package1", True),
    }
    return ChiaFile(path=Path(path), annotations=annotations_map.get(path, Annotation("chia-blockchain", False)))


@pytest.fixture
def prepare_mocks2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("chia.util.virtual_project_analysis.ChiaFile.parse", mock_chia_file_parse2)


def test_cycle_detection(prepare_mocks2: None) -> None:
    # Example graph with a simple cycle
    graph: dict[Path, list[Path]] = {
        Path("/path/to/package1/module1.py"): [Path("/path/to/package2/module2.py")],
        Path("/path/to/package2/module2.py"): [Path("/path/to/package3/module3.py")],  # Cycle here
        Path("/path/to/package3/module3.py"): [],
    }
    cycles = find_cycles(
        graph,
        build_virtual_dependency_graph(DirectoryParameters(dir_path=Path("path")), existing_graph=graph),
        excluded_paths=[],
        ignore_cycles_in=[],
        ignore_specific_files=[],
        ignore_specific_edges=[],
    )
    # \path\to\package1\module1.py (Package1) -> \path\to\package2\module2.py (Package2) -> (Package1)
    # \path\to\package2\module2.py (Package2) -> \path\to\package3\module3.py (Package1) -> (Package2)
    assert len(cycles) == 2


def test_print_cycles(tmp_path: Path) -> None:
    chia_dir = tmp_path / "chia"
    chia_dir.mkdir()

    # Create some files within the chia package
    create_python_file(chia_dir, "module1.py", "# Package: one\ndef func1(): pass\nfrom chia.module2 import func2")
    create_python_file(chia_dir, "module2.py", "# Package: two\ndef func2(): pass\nfrom chia.module3 import func3")
    create_python_file(chia_dir, "module3.py", "# Package: one\ndef func3(): pass\n")

    # Run the command
    runner = CliRunner()
    result = runner.invoke(cli, ["print_cycles", "--directory", str(chia_dir)])
    assert "module1.py (one) -> " in result.output


def test_check_config(tmp_path: Path) -> None:
    chia_dir = tmp_path / "chia"
    chia_dir.mkdir()

    # Create some files within the chia package
    create_python_file(
        chia_dir,
        "module1.py",
        textwrap.dedent(
            """
            # Package: one
            def func1(): pass
            from chia.module2 import func2
            """
        ),
    )
    create_python_file(
        chia_dir,
        "module1b.py",
        textwrap.dedent(
            """
            # Package: one
            def func1b(): pass
            """
        ),
    )
    create_python_file(
        chia_dir,
        "module2.py",
        textwrap.dedent(
            """
            # Package: two
            def func2(): pass
            from chia.module3 import func3
            from chia.module1b import func1b
            """
        ),
    )
    create_python_file(
        chia_dir,
        "module3.py",
        textwrap.dedent(
            """
            # Package: three
            def func3(): pass
            """
        ),
    )

    # Run the command
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "check_config",
            "--directory",
            str(chia_dir),
            "--ignore-cycles-in",
            "three",
            "--ignore-specific-file",
            str(chia_dir / "module3.py"),
            "--ignore-specific-edge",
            str(chia_dir / "module2.py") + " -> " + str(chia_dir / "module3.py"),
            "--ignore-specific-edge",
            str(chia_dir / "module2.py") + " -> " + str(chia_dir / "module1b.py"),
        ],
    )
    assert "    module three ignored but no cycles were found" in result.output
    assert f"    file {chia_dir / 'module3.py'!s} ignored but no cycles were found" in result.output
    assert (
        f"edge {str(chia_dir / 'module2.py') + ' -> ' + str(chia_dir / 'module3.py')} ignored but no cycles were found"
        in result.output
    )
    assert (
        f"edge {str(chia_dir / 'module2.py') + ' -> ' + str(chia_dir / 'module1b.py')} ignored but no cycles were found"
        not in result.output
    )


def test_excluded_paths_handling(prepare_mocks2: None) -> None:
    # Graph where module2.py is excluded
    graph = {
        Path("/path/to/package1/module1.py"): [Path("/path/to/package2/module2.py")],
        Path("/path/to/package2/module2.py"): [Path("/path/to/package1/module1.py")],
    }
    cycles = find_cycles(
        graph,
        build_virtual_dependency_graph(DirectoryParameters(dir_path=Path("path")), existing_graph=graph),
        excluded_paths=[Path("/path/to/package2/module2.py")],
        ignore_cycles_in=[],
        ignore_specific_files=[],
        ignore_specific_edges=[],
    )
    assert len(cycles) == 0  # No cycles due to exclusion


def test_ignore_cycles_in_specific_packages(prepare_mocks2: None) -> None:
    graph: dict[Path, list[Path]] = {
        Path("/path/to/package1/module1.py"): [Path("/path/to/package2/module2.py")],
        Path("/path/to/package2/module2.py"): [Path("/path/to/package3/module3.py")],
        Path("/path/to/package3/module3.py"): [],
    }
    # Assuming module1.py and module3.py belong to Package1, which is ignored
    cycles = find_cycles(
        graph,
        build_virtual_dependency_graph(DirectoryParameters(dir_path=Path("path")), existing_graph=graph),
        excluded_paths=[],
        ignore_cycles_in=["Package1"],
        ignore_specific_files=[],
        ignore_specific_edges=[],
    )
    assert len(cycles) == 1  # Cycles in Package1 are ignored


def test_ignore_cycles_with_specific_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    def _mock_chia_file_parse(path: Path) -> ChiaFile:
        annotations_map = {
            Path("/path/to/package1/module1a.py"): Annotation("Package1", True),
            Path("/path/to/package2/module2.py"): Annotation("Package2", True),
            Path("/path/to/package3/module3.py"): Annotation("Package3", True),
            Path("/path/to/package1/module1b.py"): Annotation("Package1", True),
        }
        return ChiaFile(path=Path(path), annotations=annotations_map.get(path, Annotation("chia-blockchain", False)))

    monkeypatch.setattr("chia.util.virtual_project_analysis.ChiaFile.parse", _mock_chia_file_parse)

    graph = {
        Path("/path/to/package1/module1a.py"): [Path("/path/to/package2/module2.py")],
        Path("/path/to/package2/module2.py"): [Path("/path/to/package3/module3.py")],
        Path("/path/to/package3/module3.py"): [Path("/path/to/package1/module1b.py")],
        Path("/path/to/package1/module1b.py"): [],
    }
    virtual_graph = build_virtual_dependency_graph(DirectoryParameters(dir_path=Path("path")), existing_graph=graph)
    cycles = find_cycles(
        graph,
        virtual_graph,
        excluded_paths=[],
        ignore_cycles_in=[],
        ignore_specific_files=[],
        ignore_specific_edges=[
            (File(Path("/path/to/package3/module3.py")), File(Path("/path/to/package2/module2.py"))),
            (Package("Package3"), Package("Package2")),
        ],
    )
    assert len(cycles) == 0


def test_ignore_cycles_with_specific_files(prepare_mocks2: None) -> None:
    graph = {
        Path("/path/to/package1/module1.py"): [Path("/path/to/package2/module2.py")],
        Path("/path/to/package2/module2.py"): [Path("/path/to/package3/module3.py")],  # Cycle here
    }
    cycles = find_cycles(
        graph,
        build_virtual_dependency_graph(DirectoryParameters(dir_path=Path("path")), existing_graph=graph),
        excluded_paths=[],
        ignore_cycles_in=[],
        ignore_specific_files=[Path("/path/to/package1/module1.py"), Path("/path/to/package2/module2.py")],
        ignore_specific_edges=[],
    )
    assert len(cycles) == 0


# Sample function to use with the decorator for testing
@click.command("blah")
@config
def sample_function(config: Config) -> None:
    print(config)


# Helper function to create a temporary YAML configuration file
@pytest.fixture
def create_yaml_config(tmp_path: Path) -> Callable[[dict[str, Any]], Path]:
    def _create_yaml_config(content: dict[str, Any]) -> Path:
        path = tmp_path / "config.yaml"
        with open(path, "w") as f:
            yaml.dump(content, f)
        return path

    return _create_yaml_config


def test_config_with_yaml(create_yaml_config: Callable[[dict[str, Any]], Path]) -> None:
    # Create a temporary YAML configuration file
    yaml_config = {
        "exclude_paths": ["path/to/exclude"],
        "ignore": {
            "packages": ["ignored.package"],
            "files": ["ignored_file.py"],
            "edges": ["ignored_parent -> ignored_child"],
        },
    }
    config_path = create_yaml_config(yaml_config)

    runner = CliRunner()

    # Invoke the CLI with the --config option
    result = runner.invoke(sample_function, ["--directory", ".", "--config", str(config_path)])

    # Check if the command ran successfully
    assert result.exit_code == 0

    # Verify the config object created by the decorator
    config = result.output
    path_type = config_path.__class__.__name__
    assert config == (
        "Config("
        "directory_parameters=DirectoryParameters("
        f"dir_path={path_type}('.'), "
        f"excluded_paths=[{path_type}('path/to/exclude')]"
        "), "
        "ignore_cycles_in=['ignored.package'], "
        f"ignore_specific_files=[{path_type}('ignored_file.py')], "
        f"ignore_specific_edges=[(Package(name='ignored_child', is_file=False), "
        f"Package(name='ignored_parent', is_file=False))]"
        ")\n"
    )


def test_parse_edges(tmp_path: Path) -> None:
    chia_dir = tmp_path / "chia"
    chia_dir.mkdir()

    # Create some files within the chia package
    create_python_file(
        chia_dir,
        "module1.py",
        textwrap.dedent(
            """
            # Package: one
            def func1(): pass
            from chia.module2 import func2
            from chia.module3 import func3
            """
        ),
    )
    create_python_file(
        chia_dir,
        "module2.py",
        textwrap.dedent(
            """
            # Package: two
            def func2(): pass
            """
        ),
    )
    create_python_file(
        chia_dir,
        "module3.py",
        textwrap.dedent(
            """
            # Package: three
            def func3(): pass
            """
        ),
    )

    # Run the command
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "print_edges",
            "--directory",
            str(chia_dir),
            "--dependent-package",
            "one",
            "--provider-package",
            "two",
        ],
    )
    assert result.output.strip() == f"{chia_dir / 'module1.py'!s} (one) -> {chia_dir / 'module2.py'!s} (two)"
