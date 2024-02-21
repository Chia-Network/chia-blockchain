from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import click


@dataclass(frozen=True)
class Annotation:
    package: str

    @classmethod
    def is_annotated(cls, file_string: str) -> bool:
        return file_string.startswith("# Package: ")

    @classmethod
    def parse(cls, file_string: str) -> Annotation:
        result = re.search(r"^# Package: (.+)$", file_string, re.MULTILINE)
        if result is None:
            raise ValueError("Annotation not found")

        return cls(result.group(1))


@dataclass(frozen=True)
class ChiaFile:
    path: Path
    annotations: Annotation

    @classmethod
    def parse(cls, file_path: Path) -> ChiaFile:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            return cls(file_path, Annotation.parse(f.read()))


def is_empty(fp: Path) -> bool:
    with open(fp, encoding="utf-8", errors="ignore") as file:
        filestring = file.read()
        return filestring.strip() == ""


# Function to build a dependency graph
def build_dependency_graph(dir_path: Path) -> Dict[Path, List[Path]]:
    dependency_graph: Dict[Path, List[Path]] = {}
    for file_path in gather_non_empty_files(dir_path):
        dependency_graph[file_path] = []
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            filestring = f.read()
            tree = ast.parse(filestring, filename=file_path)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module is not None and node.module.startswith("chia."):
                        imported_path = os.path.join("./", node.module.replace(".", "/") + ".py")
                        paths_to_search = [
                            imported_path,
                            *(os.path.join(imported_path[:-3], alias.name + ".py") for alias in node.names),
                        ]
                        for path_to_search in paths_to_search:
                            if os.path.exists(path_to_search):
                                dependency_graph[file_path].append(Path(path_to_search))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("chia."):
                            imported_path = os.path.join("./", alias.name.replace(".", "/") + ".py")
                            if os.path.exists(imported_path):
                                dependency_graph[file_path].append(Path(imported_path))
    return dependency_graph


def build_virtual_dependency_graph(dir_path: Path) -> Dict[str, List[str]]:
    graph = build_dependency_graph(dir_path)
    virtual_graph: Dict[str, List[str]] = {}
    for file, imports in graph.items():
        parent = ChiaFile.parse(Path(file)).annotations.package
        virtual_graph.setdefault(parent, [])

        children = [ChiaFile.parse(Path(imp)).annotations.package for imp in imports]

        virtual_graph[parent].extend(children)

    return {k: list({v for v in vs if v != k}) for k, vs in virtual_graph.items()}


def find_cycles(graph: Dict[Path, List[Path]]) -> List[str]:
    def recursive_dependency_search(
        top_level_package: str, left_top_level: bool, dependency: Path, already_seen: List[Path]
    ) -> List[List[Tuple[str, Path]]]:
        if dependency in already_seen:
            return []
        already_seen.append(dependency)
        chia_file = ChiaFile.parse(dependency)
        if chia_file.annotations.package == top_level_package and left_top_level:
            return [[(chia_file.annotations.package, dependency)]]
        else:
            left_top_level = left_top_level or chia_file.annotations.package != top_level_package
            return [
                [(chia_file.annotations.package, dependency), *stack]
                for stack in [
                    _stack
                    for dep in graph[dependency]
                    for _stack in recursive_dependency_search(top_level_package, left_top_level, dep, already_seen)
                ]
            ]

    path_accumulator = []
    for parent in graph:
        chia_file = ChiaFile.parse(parent)
        path_accumulator.extend(recursive_dependency_search(chia_file.annotations.package, False, parent, []))

    return [" -> ".join([str(d) + f" ({p})" for p, d in stack]) for stack in path_accumulator]


def gather_non_empty_files(dir_path: Path) -> List[Path]:
    non_empty_files = []
    for root, _, files in os.walk(dir_path):
        for file in files:
            full_path = Path(os.path.join(root, file))
            if file.endswith(".py") and not is_empty(full_path):
                non_empty_files.append(full_path)

    return non_empty_files


@click.group(help="A utility for grouping different parts of the repo into separate projects")
def cli() -> None:
    pass


@click.command("find_missing_annotations", short_help="Search a directory for chia files without annotations")
@click.option("--directory", "-d", type=click.Path(), help="The directory to search in", required=True)
def find_missing_annotations(directory: Path) -> None:
    for path in gather_non_empty_files(directory):
        with open(path, encoding="utf-8", errors="ignore") as file:
            filestring = file.read()
            if not Annotation.is_annotated(filestring):
                print(path)


@click.command("print_dependency_graph", short_help="Output a dependency graph of all the files in a directory")
@click.option("--directory", "-d", type=click.Path(), help="The directory to search in", required=True)
def print_dependency_graph(directory: Path) -> None:
    print(json.dumps(build_dependency_graph(directory), indent=4))


@click.command(
    "print_virtual_dependency_graph", short_help="Output a dependency graph of all the packages in a directory"
)
@click.option("--directory", "-d", type=click.Path(), help="The directory to search in", required=True)
def print_virtual_dependency_graph(directory: Path) -> None:
    print(json.dumps(build_virtual_dependency_graph(directory), indent=4))


@click.command("print_cycles", short_help="Output cycles found in the virtual dependency graph")
@click.option("--directory", "-d", type=click.Path(), help="The directory to search in", required=True)
def print_cycles(directory: Path) -> None:
    for cycle in find_cycles(build_dependency_graph(directory)):
        print(cycle)


cli.add_command(find_missing_annotations)
cli.add_command(print_dependency_graph)
cli.add_command(print_virtual_dependency_graph)
cli.add_command(print_cycles)

if __name__ == "__main__":
    cli()
