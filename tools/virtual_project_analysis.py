import ast
import os
from pathlib import Path
from collections import defaultdict

# Define the root directory of the chia project
root_dir = "./chia"  # Change this to the path of your chia project

# Function to check if a module imports from another chia module or is empty or annotated
def is_empty(fp):
    with open(fp, "r", encoding='utf-8', errors='ignore') as file:
        filestring = file.read()
        return filestring.strip() == ""

def is_annotated(fp):
    with open(fp, "r", encoding='utf-8', errors='ignore') as file:
        filestring = file.read()
        return filestring.startswith("# Package: ")

def imports_chia_module(fp):
    with open(fp, "r", encoding='utf-8', errors='ignore') as file:
        filestring = file.read()
        tree = ast.parse(filestring, filename=fp)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("chia."):
                        return True
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None and node.module.startswith("chia."):
                    return True
        return False

def imports_chia_module_or_is_empty_or_is_annotated(file_path):
    with open(file_path, "r", encoding='utf-8', errors='ignore') as file:
        filestring = file.read()
        if filestring.strip() == "" or filestring.startswith("# Package: "):
            return True
        tree = ast.parse(filestring, filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("chia."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None and node.module.startswith("chia."):
                return True
    return False

# Function to build a dependency graph
def build_dependency_graph(dir_path):
    dependency_graph = defaultdict(list)
    for root, _, files in os.walk(dir_path):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                dependency_graph[file_path] = []
                with open(file_path, "r", encoding='utf-8', errors='ignore') as f:
                    filestring = f.read()
                    tree = ast.parse(filestring, filename=file_path)
                    for node in ast.iter_child_nodes(tree):
                        if isinstance(node, ast.ImportFrom):
                            if node.module is not None and node.module.startswith("chia."):
                                imported_path = os.path.join("./", node.module.replace('.', '/') + ".py")
                                paths_to_search = [imported_path, *(os.path.join(imported_path[:-3], alias.name + ".py") for alias in node.names)]
                                for path_to_search in paths_to_search:
                                    if os.path.exists(path_to_search):
                                        dependency_graph[file_path].append(path_to_search)
                        elif isinstance(node, ast.Import):
                            for alias in node.names:
                                if alias.name.startswith("chia."):
                                    imported_path = os.path.join("./", alias.name.replace('.', '/') + ".py")
                                    if os.path.exists(imported_path):
                                        dependency_graph[file_path].append(imported_path)
    return dependency_graph

# Function to find files based on the new criteria
def find_files_based_on_new_criteria(dir_path):
    dependency_graph = build_dependency_graph(dir_path)
    filtered_files = []

    for file_path in dependency_graph:
        if imports_chia_module(Path(file_path)):
            if is_annotated(Path(file_path)):
                continue
            # Check if all dependencies of the file also do not import chia modules
            all_dependencies_pass = all(not is_empty(Path(dep)) and is_annotated(Path(dep)) for dep in dependency_graph[file_path])
            if all_dependencies_pass:
                filtered_files.append(file_path)
        elif not is_empty(Path(file_path)) and not is_annotated(Path(file_path)):
            filtered_files.append(file_path)

    return filtered_files

# Execute the search
filtered_files = find_files_based_on_new_criteria(root_dir)

# Print the results
print("Files that do not import from another chia module directly or through their dependencies:")
for file_path in filtered_files:
    print(file_path)
