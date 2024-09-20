from __future__ import annotations

import importlib
import inspect
import os
import pathlib
import sys
import tempfile
from typing import List

import importlib_resources
from clvm_tools_rs import compile_clvm as compile_clvm_rust

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.util.lock import Lockfile

compile_clvm_py = None

recompile_requested = (
    (os.environ.get("CHIA_DEV_COMPILE_CLVM_ON_IMPORT", "") != "") or ("pytest" in sys.modules)
) and os.environ.get("CHIA_DEV_COMPILE_CLVM_DISABLED", None) is None

here_name = __name__.rpartition(".")[0]


def translate_path(p_):
    p = str(p_)
    if os.path.isdir(p):
        return p
    else:
        module_object = importlib.import_module(p)
        return os.path.dirname(inspect.getfile(module_object))


# Handle optional use of python clvm_tools if available and requested
if "CLVM_TOOLS" in os.environ:
    from clvm_tools.clvmc import compile_clvm as compile_clvm_py_candidate

    compile_clvm_py = compile_clvm_py_candidate


def compile_clvm_in_lock(full_path: pathlib.Path, output: pathlib.Path, search_paths: List[pathlib.Path]):
    # Compile using rust (default)

    # Ensure path translation is done in the idiomatic way currently
    # expected.  It can use either a filesystem path or name a python
    # module.
    treated_include_paths = list(map(translate_path, search_paths))
    res = compile_clvm_rust(str(full_path), str(output), treated_include_paths)

    if "CLVM_TOOLS" in os.environ and os.environ["CLVM_TOOLS"] == "check" and compile_clvm_py is not None:
        # Simple helper to read the compiled output
        def sha256file(f):
            import hashlib

            m = hashlib.sha256()
            with open(f) as open_file:
                m.update(open_file.read().strip().encode("utf8"))
            return m.hexdigest()

        orig = f"{output}.orig"

        compile_clvm_py(full_path, orig, search_paths=search_paths)
        orig256 = sha256file(orig)
        rs256 = sha256file(output)

        if orig256 != rs256:
            print(f"Compiled original {full_path}: {orig256} vs rust {rs256}\n")
            print("Aborting compilation due to mismatch with rust")
            assert orig256 == rs256
        else:
            print(f"Compilation match {full_path}: {orig256}\n")

    return res


def compile_clvm(full_path: pathlib.Path, output: pathlib.Path, search_paths: List[pathlib.Path] = []):
    with Lockfile.create(pathlib.Path(tempfile.gettempdir()) / "clvm_compile" / full_path.name):
        compile_clvm_in_lock(full_path, output, search_paths)


def load_serialized_clvm(
    clvm_filename, package_or_requirement=here_name, include_standard_libraries: bool = True, recompile: bool = True
) -> SerializedProgram:
    """
    This function takes a .clsp file in the given package and compiles it to a
    .clsp.hex file if the .hex file is missing or older than the .clsp file, then
    returns the contents of the .hex file as a `Program`.

    clvm_filename: file name
    package_or_requirement: usually `__name__` if the clvm file is in the same package
    """
    hex_filename = f"{clvm_filename}.hex"

    # Set the CHIA_DEV_COMPILE_CLVM_ON_IMPORT environment variable to anything except
    # "" or "0" to trigger automatic recompilation of the Chialisp on load.
    resources = importlib_resources.files(package_or_requirement)
    if recompile and not getattr(sys, "frozen", False):
        full_path = resources.joinpath(clvm_filename)
        if full_path.exists():
            # Establish whether the size is zero on entry
            output = full_path.parent / hex_filename
            if not output.exists() or os.stat(full_path).st_mtime > os.stat(output).st_mtime:
                search_paths = [full_path.parent]
                if include_standard_libraries:
                    # we can't get the dir, but we can get a file then get its parent.
                    chia_puzzles_path = pathlib.Path(__file__).parent
                    search_paths.append(chia_puzzles_path)
                compile_clvm(full_path, output, search_paths=search_paths)

    clvm_path = resources.joinpath(hex_filename)
    clvm_hex = clvm_path.read_text(encoding="utf-8")
    assert len(clvm_hex.strip()) != 0
    clvm_blob = bytes.fromhex(clvm_hex)
    return SerializedProgram.from_bytes(clvm_blob)


def load_clvm(
    clvm_filename,
    package_or_requirement=here_name,
    include_standard_libraries: bool = True,
    recompile: bool = True,
) -> Program:
    return Program.from_bytes(
        bytes(
            load_serialized_clvm(
                clvm_filename,
                package_or_requirement=package_or_requirement,
                include_standard_libraries=include_standard_libraries,
                recompile=recompile,
            )
        )
    )


def load_clvm_maybe_recompile(
    clvm_filename,
    package_or_requirement=here_name,
    include_standard_libraries: bool = True,
    recompile: bool = recompile_requested,
) -> Program:
    return load_clvm(
        clvm_filename=clvm_filename,
        package_or_requirement=package_or_requirement,
        include_standard_libraries=include_standard_libraries,
        recompile=recompile,
    )


def load_serialized_clvm_maybe_recompile(
    clvm_filename,
    package_or_requirement=here_name,
    include_standard_libraries: bool = True,
    recompile: bool = recompile_requested,
) -> SerializedProgram:
    return load_serialized_clvm(
        clvm_filename=clvm_filename,
        package_or_requirement=package_or_requirement,
        include_standard_libraries=include_standard_libraries,
        recompile=recompile,
    )
