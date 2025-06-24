# Package: virtual_project_analysis

from __future__ import annotations

import ast
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Union

import click
import yaml

# This tool enforces digraph dependencies within a "virtual project structure".
# i.e. files grouped together forming a project are not allowed to have cyclical
# dependencies on other such groups.

# by default, all files are considered part of the "chia-blockchain" project.

# To pull out a sub project, annotate its files with a comment (on the first
# line):
# Package: <name>

# if chia-blockchain depends on this new sub-project, the sub-project may not
# depend back on chia-blockchain.


@dataclass(frozen=True)
class Annotation:
    package: str
    is_annotated: bool

    @classmethod
    def parse(cls, file_string: str) -> Annotation:
        result = re.search(r"^# Package: (.+)$", file_string, re.MULTILINE)
        if result is None:
            return cls("chia-blockchain", False)

        return cls(result.group(1).strip(), True)


@dataclass(frozen=True)
class ChiaFile:
    path: Path
    annotations: Annotation

    @classmethod
    def parse(cls, file_path: Path) -> ChiaFile:
        # everything under chia/_tests belong to the "tests" subproject. It
        # (obviously) depends on everything, but no production code is allowed
        # to depend back on the tests.
        if list(file_path.parts[0:2]) == ["chia", "_tests"]:
            return cls(file_path, Annotation("tests", True))

        with open(file_path, encoding="utf-8", errors="ignore") as f:
            file_string = f.read().strip()
            return cls(file_path, Annotation.parse(file_string))


def build_dependency_graph(dir_params: DirectoryParameters) -> dict[Path, list[Path]]:
    dependency_graph: dict[Path, list[Path]] = {}
    for chia_file in dir_params.gather_non_empty_python_files():
        dependency_graph[chia_file.path] = []
        with open(chia_file.path, encoding="utf-8", errors="ignore") as f:
            filestring = f.read()
            tree = ast.parse(filestring, filename=chia_file.path)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module is not None and node.module.startswith(dir_params.dir_path.stem):
                        imported_path = os.path.join(dir_params.dir_path.parent, node.module.replace(".", "/") + ".py")
                        paths_to_search = [
                            imported_path,
                            *(os.path.join(imported_path[:-3], alias.name + ".py") for alias in node.names),
                        ]
                        for path_to_search in paths_to_search:
                            if os.path.exists(path_to_search):
                                dependency_graph[chia_file.path].append(Path(path_to_search))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith(dir_params.dir_path.stem):
                            imported_path = os.path.join(
                                dir_params.dir_path.parent, alias.name.replace(".", "/") + ".py"
                            )
                            if os.path.exists(imported_path):
                                dependency_graph[chia_file.path].append(Path(imported_path))
    return dependency_graph


def build_virtual_dependency_graph(
    dir_params: DirectoryParameters, *, existing_graph: Optional[dict[Path, list[Path]]] = None
) -> dict[str, list[str]]:
    if existing_graph is None:
        graph = build_dependency_graph(dir_params)
    else:
        graph = existing_graph

    virtual_graph: dict[str, list[str]] = {}
    for file, imports in graph.items():
        file_path = Path(file)
        root_file = ChiaFile.parse(file_path)
        if root_file.annotations is None:
            continue
        root = root_file.annotations.package
        virtual_graph.setdefault(root, [])

        dependency_files = [ChiaFile.parse(Path(imp)) for imp in imports]
        dependencies = [f.annotations.package for f in dependency_files if f.annotations is not None]

        virtual_graph[root].extend(dependencies)

    # Filter out self before returning the list
    return {k: list({v for v in vs if v != k}) for k, vs in virtual_graph.items()}


@dataclass(frozen=True)
class Cycle:
    dependent_path: Path
    dependent_package: str
    provider_path: Path
    provider_package: str
    packages_after_provider: list[str]

    def __repr__(self) -> str:
        return "".join(
            (
                f"{self.dependent_path} ({self.dependent_package}) -> ",
                f"{self.provider_path} ({self.provider_package}) -> ",
                *(f"({extra}) -> " for extra in self.packages_after_provider),
            )
        )[:-4]

    def possible_edge_interpretations(self) -> list[tuple[FileOrPackage, FileOrPackage]]:
        edges_after_initial_files = []
        provider = self.packages_after_provider[0]
        for next_provider in self.packages_after_provider[1:]:
            edges_after_initial_files.append((Package(next_provider), Package(provider)))
            provider = next_provider

        return [
            # Dependent -> Provider
            (File(self.provider_path), File(self.dependent_path)),
            (Package(self.provider_package), File(self.dependent_path)),
            (File(self.provider_path), Package(self.dependent_package)),
            (Package(self.provider_package), Package(self.dependent_package)),
            # Provider -> Dependent/Other Packages
            (Package(self.packages_after_provider[0]), File(self.provider_path)),
            (Package(self.packages_after_provider[0]), Package(self.provider_package)),
            # the rest
            *edges_after_initial_files,
        ]


def find_all_dependency_paths(dependency_graph: dict[str, list[str]], start: str, end: str) -> list[list[str]]:
    all_paths = []
    visited = set()

    def dfs(current: str, target: str, path: list[str]) -> None:
        if current in visited:
            return
        if current == target and len(path) > 0:
            all_paths.append([*path[1:], current])
            return
        visited.add(current)
        for provider in sorted(dependency_graph.get(current, [])):
            dfs(provider, target, [*path, current])

    dfs(start, end, [])
    return all_paths


def find_cycles(
    graph: dict[Path, list[Path]],
    virtual_graph: dict[str, list[str]],
    excluded_paths: list[Path],
    ignore_cycles_in: list[str],
    ignore_specific_files: list[Path],
    ignore_specific_edges: list[tuple[FileOrPackage, FileOrPackage]],
) -> list[Cycle]:
    # Initialize an accumulator for paths that are part of cycles.
    path_accumulator = []
    # Iterate over each package (parent) in the graph.
    for dependent in sorted(graph):
        if dependent in excluded_paths:
            continue
        # Parse the parent package file.
        dependent_file = ChiaFile.parse(dependent)
        # Skip this package if it has no annotations or should be ignored in cycle detection.
        if (
            dependent_file.annotations is None
            or dependent_file.annotations.package in ignore_cycles_in
            or dependent in ignore_specific_files
        ):
            continue

        for provider in sorted(graph[dependent]):
            if provider in excluded_paths:
                continue
            provider_file = ChiaFile.parse(provider)
            if (
                provider_file.annotations is None
                or provider_file.annotations.package == dependent_file.annotations.package
            ):
                continue

            dependency_paths = find_all_dependency_paths(
                virtual_graph, provider_file.annotations.package, dependent_file.annotations.package
            )
            if dependency_paths is None:
                continue

            for dependency_path in dependency_paths:
                possible_cycle = Cycle(
                    dependent_file.path,
                    dependent_file.annotations.package,
                    provider_file.path,
                    provider_file.annotations.package,
                    dependency_path,
                )

                for edge in possible_cycle.possible_edge_interpretations():
                    if edge in ignore_specific_edges:
                        break
                else:
                    path_accumulator.append(possible_cycle)

    # Format and return the accumulated paths as strings showing the cycles.
    return path_accumulator


def print_graph(graph: Union[dict[str, list[str]], dict[Path, list[Path]]]) -> None:
    print(json.dumps({str(k): list(str(v) for v in vs) for k, vs in graph.items()}, indent=4))


@click.group(help="A utility for grouping different parts of the repo into separate projects")
def cli() -> None:
    pass


@dataclass(frozen=True)
class DirectoryParameters:
    dir_path: Path
    excluded_paths: list[Path] = field(default_factory=list)

    def gather_non_empty_python_files(self) -> list[ChiaFile]:
        """
        Gathers non-empty Python files in the specified directory while
        ignoring files and directories in the excluded paths.

        Returns:
            A list of paths to non-empty Python files.
        """
        python_files = []
        for root, dirs, files in os.walk(self.dir_path, topdown=True):
            # Modify dirs in-place to remove excluded directories from search
            dirs[:] = [d for d in dirs if Path(os.path.join(root, d)) not in self.excluded_paths]

            for file in files:
                file_path = Path(os.path.join(root, file))
                # Check if the file is a Python file and not in the excluded paths
                if file_path.suffix == ".py" and file_path not in self.excluded_paths:
                    # Check if the file is non-empty
                    if os.path.getsize(file_path) > 0:
                        python_files.append(ChiaFile.parse(file_path))

        return python_files


@dataclass(frozen=True)
class Config:
    directory_parameters: DirectoryParameters
    ignore_cycles_in: list[str]
    ignore_specific_files: list[Path]
    ignore_specific_edges: list[tuple[FileOrPackage, FileOrPackage]]  # (parent, child)


@dataclass(frozen=True)
class File:
    name: Path
    is_file: Literal[True] = True


@dataclass(frozen=True)
class Package:
    name: str
    is_file: Literal[False] = False


FileOrPackage = Union[File, Package]


def parse_file_or_package(identifier: str) -> FileOrPackage:
    if ".py" in identifier:
        if "(" not in identifier:
            return File(Path(identifier))
        else:
            return File(Path(identifier.split("(")[0].strip()))

    if ".py" not in identifier and identifier[0] == "(" and identifier[-1] == ")":
        return Package(identifier[1:-1])  # strip parens

    return Package(identifier)


def parse_edge(user_string: str) -> tuple[FileOrPackage, FileOrPackage]:
    split_string = user_string.split("->")
    dependent_side = split_string[0].strip()
    provider_side = split_string[1].strip()

    return parse_file_or_package(provider_side), parse_file_or_package(dependent_side)


def config(func: Callable[..., None]) -> Callable[..., None]:
    @click.option(
        "--directory",
        "include_dir",
        type=click.Path(exists=True, file_okay=False, dir_okay=True),
        required=True,
        help="The directory to include.",
    )
    @click.option(
        "--exclude-path",
        "excluded_paths",
        multiple=True,
        type=click.Path(exists=False, file_okay=True, dir_okay=True),
        help="Optional paths to exclude.",
    )
    @click.option(
        "--config",
        "config_path",
        type=click.Path(exists=True),
        required=False,
        default=None,
        help="Path to the YAML configuration file.",
    )
    def inner(config_path: Optional[str], *args: Any, **kwargs: Any) -> None:
        exclude_paths = []
        ignore_cycles_in: list[str] = []
        ignore_specific_files: list[str] = []
        ignore_specific_edges: list[str] = []
        if config_path is not None:
            # Reading from the YAML configuration file
            with open(config_path) as file:
                config_data = yaml.safe_load(file)

            # Extracting required configuration values
            exclude_paths = [Path(p) for p in config_data.get("exclude_paths") or []]
            ignore_cycles_in = config_data["ignore"].get("packages") or []
            ignore_specific_files = config_data["ignore"].get("files") or []
            ignore_specific_edges = config_data["ignore"].get("edges") or []

        # Instantiate DirectoryParameters with the provided options
        dir_params = DirectoryParameters(
            dir_path=Path(kwargs.pop("include_dir")),
            excluded_paths=[*(Path(p) for p in kwargs.pop("excluded_paths")), *exclude_paths],
        )

        # Make the ignored edge dictionary
        ignore_specific_edges_graph = []
        for ignore in (*kwargs.pop("ignore_specific_edges", []), *ignore_specific_edges):
            parent, child = parse_edge(ignore)
            ignore_specific_edges_graph.append((parent, child))

        # Instantiating the Config object
        config = Config(
            directory_parameters=dir_params,
            ignore_cycles_in=[*kwargs.pop("ignore_cycles_in", []), *ignore_cycles_in],
            ignore_specific_files=[Path(p) for p in (*kwargs.pop("ignore_specific_files", []), *ignore_specific_files)],
            ignore_specific_edges=ignore_specific_edges_graph,
        )

        # Calling the wrapped function with the Config object and other arguments
        return func(config, *args, **kwargs)

    return inner


@click.command("find_missing_annotations", short_help="Search a directory for chia files without annotations")
@config
def find_missing_annotations(config: Config) -> None:
    flag = False
    for file in config.directory_parameters.gather_non_empty_python_files():
        if not file.annotations.is_annotated:
            print(file.path)
            flag = True

    if flag:
        sys.exit(1)


@click.command("print_dependency_graph", short_help="Output a dependency graph of all the files in a directory")
@config
def print_dependency_graph(config: Config) -> None:
    print_graph(build_dependency_graph(config.directory_parameters))


@click.command(
    "print_virtual_dependency_graph", short_help="Output a dependency graph of all the packages in a directory"
)
@config
def print_virtual_dependency_graph(config: Config) -> None:
    print_graph(build_virtual_dependency_graph(config.directory_parameters))


@click.command("print_cycles", short_help="Output cycles found in the virtual dependency graph")
@click.option(
    "--ignore-cycles-in",
    "ignore_cycles_in",
    multiple=True,
    type=str,
    help="Ignore dependency cycles in a package",
)
@click.option(
    "--ignore-specific-file",
    "ignore_specific_files",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="Ignore cycles involving specific files",
)
@click.option(
    "--ignore-specific-edge",
    "ignore_specific_edges",
    multiple=True,
    type=str,
    help="Ignore specific problematic dependencies (format: path/to/file1 -> path/to/file2)",
)
@config
def print_cycles(config: Config) -> None:
    flag = False
    graph = build_dependency_graph(config.directory_parameters)
    for cycle in find_cycles(
        graph,
        build_virtual_dependency_graph(config.directory_parameters, existing_graph=graph),
        config.directory_parameters.excluded_paths,
        config.ignore_cycles_in,
        config.ignore_specific_files,
        config.ignore_specific_edges,
    ):
        print(cycle)
        flag = True

    if flag:
        sys.exit(1)


@click.command("check_config", short_help="Check the config is as specific as it can be")
@click.option(
    "--ignore-cycles-in",
    "ignore_cycles_in",
    multiple=True,
    type=str,
    help="Ignore dependency cycles in a package",
)
@click.option(
    "--ignore-specific-file",
    "ignore_specific_files",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="Ignore cycles involving specific files",
)
@click.option(
    "--ignore-specific-edge",
    "ignore_specific_edges",
    multiple=True,
    type=str,
    help="Ignore specific problematic dependencies (format: path/to/file1 -> path/to/file2)",
)
@config
def check_config(config: Config) -> None:
    graph = build_dependency_graph(config.directory_parameters)
    cycles = find_cycles(
        graph,
        build_virtual_dependency_graph(config.directory_parameters, existing_graph=graph),
        config.directory_parameters.excluded_paths,
        [],
        [],
        [],
    )
    modules_found = set()
    files_found = set()
    edges_found = set()
    for cycle in cycles:
        modules_found.add(cycle.dependent_package)
        files_found.add(cycle.dependent_path)
        edges_found.update(set(cycle.possible_edge_interpretations()))

    for module in config.ignore_cycles_in:
        if module not in modules_found:
            print(f"    module {module} ignored but no cycles were found")
    print()
    for file in config.ignore_specific_files:
        if file not in files_found:
            print(f"    file {file} ignored but no cycles were found")
    print()
    for edge in config.ignore_specific_edges:
        if edge not in edges_found:
            print(f"    edge {edge[1].name} -> {edge[0].name} ignored but no cycles were found")


@click.command("print_edges", short_help="Check for all of the ways a package immediately depends on another")
@click.option(
    "--dependent-package",
    "from_package",
    type=str,
    help="The package that depends on the other",
)
@click.option(
    "--provider-package",
    "to_package",
    type=str,
    help="The package that the dependent package imports from",
)
@config
def print_edges(config: Config, from_package: str, to_package: str) -> None:
    graph = build_dependency_graph(config.directory_parameters)
    for dependent, providers in graph.items():
        dependent_file = ChiaFile.parse(dependent)
        assert dependent_file.annotations is not None
        if dependent_file.annotations.package == from_package:
            for provider in providers:
                provider_file = ChiaFile.parse(provider)
                assert provider_file.annotations is not None
                if provider_file.annotations.package == to_package:
                    print(
                        f"{dependent} ({dependent_file.annotations.package}) -> "
                        f"{provider} ({provider_file.annotations.package})"
                    )


cli.add_command(find_missing_annotations)
cli.add_command(print_dependency_graph)
cli.add_command(print_virtual_dependency_graph)
cli.add_command(print_cycles)
cli.add_command(check_config)
cli.add_command(print_edges)

if __name__ == "__main__":
    cli()
