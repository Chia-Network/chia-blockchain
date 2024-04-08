from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List

import pytest

from chia.util.virtual_project_analysis import (
    Annotation,
    ChiaFile,
    DirectoryParameters,
    build_dependency_graph,
    build_virtual_dependency_graph,
    find_cycles,
)


def test_is_annotated_true() -> None:
    """Test that is_annotated returns True for a correctly annotated string."""
    file_string = "# Package: example\n# Some other comment"
    assert Annotation.is_annotated(file_string)


def test_is_annotated_false() -> None:
    """Test that is_annotated returns False for a non-annotated string."""
    file_string = "# Some comment\n# Some other comment"
    assert not Annotation.is_annotated(file_string)


def test_parse_valid_annotation() -> None:
    """Test that parse returns an Annotation instance for a valid annotation."""
    file_string = "# Package: example\n# Some other comment"
    annotation = Annotation.parse(file_string)
    assert isinstance(annotation, Annotation)
    assert annotation.package == "example"


def test_parse_invalid_annotation() -> None:
    """Test that parse raises ValueError for a string without valid annotation."""
    file_string = "# Some comment\n# Some other comment"
    with pytest.raises(ValueError):
        Annotation.parse(file_string)


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
    assert parsed_file.annotations is None


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


# Mock the build_dependency_graph function to control its output
def mock_build_dependency_graph(dir_params: DirectoryParameters) -> Dict[Path, List[Path]]:
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
        Path("/path/to/package1/module1.py"): Annotation(package="Package1"),
        Path("/path/to/package2/module2.py"): Annotation(package="Package2"),
        Path("/path/to/package3/module3.py"): Annotation(package="Package3"),
    }
    return ChiaFile(path=Path(path), annotations=annotations_map.get(path))


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


# Helper function to simulate ChiaFile.parse for testing
def mock_chia_file_parse2(path: Path) -> ChiaFile:
    annotations_map = {
        Path("/path/to/package1/module1.py"): Annotation(package="Package1"),
        Path("/path/to/package2/module2.py"): Annotation(package="Package2"),
        Path("/path/to/package3/module3.py"): Annotation(package="Package1"),
    }
    return ChiaFile(path=Path(path), annotations=annotations_map.get(path))


@pytest.fixture
def prepare_mocks2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("chia.util.virtual_project_analysis.ChiaFile.parse", mock_chia_file_parse2)


def test_cycle_detection(prepare_mocks2: None) -> None:
    # Example graph with a simple cycle
    graph: Dict[Path, List[Path]] = {
        Path("/path/to/package1/module1.py"): [Path("/path/to/package2/module2.py")],
        Path("/path/to/package2/module2.py"): [Path("/path/to/package3/module3.py")],  # Cycle here
        Path("/path/to/package3/module3.py"): [],
    }
    cycles = find_cycles(
        graph, excluded_paths=[], ignore_cycles_in=[], ignore_specific_files=[], ignore_specific_edges=[]
    )
    assert len(cycles) == 1  # Expect one cycle to be detected


def test_excluded_paths_handling(prepare_mocks2: None) -> None:
    # Graph where module2.py is excluded
    graph = {
        Path("/path/to/package1/module1.py"): [Path("/path/to/package2/module2.py")],
        Path("/path/to/package2/module2.py"): [Path("/path/to/package1/module1.py")],
    }
    cycles = find_cycles(
        graph,
        excluded_paths=[Path("/path/to/package2/module2.py")],
        ignore_cycles_in=[],
        ignore_specific_files=[],
        ignore_specific_edges=[],
    )
    assert len(cycles) == 0  # No cycles due to exclusion


def test_ignore_cycles_in_specific_packages(prepare_mocks2: None) -> None:
    graph: Dict[Path, List[Path]] = {
        Path("/path/to/package1/module1.py"): [Path("/path/to/package2/module2.py")],
        Path("/path/to/package2/module2.py"): [Path("/path/to/package3/module3.py")],
        Path("/path/to/package3/module3.py"): [],
    }
    # Assuming module1.py and module3.py belong to Package1, which is ignored
    cycles = find_cycles(
        graph, excluded_paths=[], ignore_cycles_in=["Package1"], ignore_specific_files=[], ignore_specific_edges=[]
    )
    assert len(cycles) == 0  # Cycles in Package1 are ignored


def test_ignore_cycles_with_specific_edges(prepare_mocks2: None) -> None:
    graph = {
        Path("/path/to/package1/module1.py"): [Path("/path/to/package2/module2.py")],
        Path("/path/to/package2/module2.py"): [Path("/path/to/package3/module3.py")],  # Cycle here
    }
    # Assuming module1.py and module2.py belong to Package1, which is ignored
    cycles = find_cycles(
        graph,
        excluded_paths=[],
        ignore_cycles_in=[],
        ignore_specific_files=[],
        ignore_specific_edges=[(Path("/path/to/package3/module3.py"), Path("/path/to/package2/module2.py"))],
    )
    assert len(cycles) == 0


def test_ignore_cycles_with_specific_files(prepare_mocks2: None) -> None:
    graph = {
        Path("/path/to/package1/module1.py"): [Path("/path/to/package2/module2.py")],
        Path("/path/to/package2/module2.py"): [Path("/path/to/package3/module3.py")],  # Cycle here
    }
    # Assuming module1.py and module2.py belong to Package1, which is ignored
    cycles = find_cycles(
        graph,
        excluded_paths=[],
        ignore_cycles_in=[],
        ignore_specific_files=[Path("/path/to/package2/module2.py")],
        ignore_specific_edges=[],
    )
    assert len(cycles) == 0
