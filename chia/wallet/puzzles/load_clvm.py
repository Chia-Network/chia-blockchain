import importlib
import inspect
import os

import tempfile
import pathlib

import pkg_resources
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.util.lock import Lockfile
from clvm_tools_rs import compile_clvm as compile_clvm_rust


compile_clvm_py = None


def translate_path(p_):
    p = str(p_)
    if os.path.isdir(p):
        return p
    else:
        module_object = importlib.import_module(p)
        return os.path.dirname(inspect.getfile(module_object))


# Handle optional use of python clvm_tools if available and requested
if "CLVM_TOOLS" in os.environ:
    try:
        from clvm_tools.clvmc import compile_clvm as compile_clvm_py_candidate

        compile_clvm_py = compile_clvm_py_candidate
    finally:
        pass


def compile_clvm_in_lock(full_path, output, search_paths):
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
            m.update(open(f).read().strip().encode("utf8"))
            return m.hexdigest()

        orig = "%s.orig" % output

        compile_clvm_py(full_path, orig, search_paths=search_paths)
        orig256 = sha256file(orig)
        rs256 = sha256file(output)

        if orig256 != rs256:
            print("Compiled original %s: %s vs rust %s\n" % (full_path, orig256, rs256))
            print("Aborting compilation due to mismatch with rust")
            assert orig256 == rs256
        else:
            print("Compilation match %s: %s\n" % (full_path, orig256))

    return res


def compile_clvm(full_path, output, search_paths=[]):
    with Lockfile.create(pathlib.Path(tempfile.gettempdir()) / "clvm_compile" / full_path.name):
        compile_clvm_in_lock(full_path, output, search_paths)


def load_serialized_clvm(clvm_filename, package_or_requirement=__name__) -> SerializedProgram:
    """
    This function takes a .clvm file in the given package and compiles it to a
    .clvm.hex file if the .hex file is missing or older than the .clvm file, then
    returns the contents of the .hex file as a `Program`.

    clvm_filename: file name
    package_or_requirement: usually `__name__` if the clvm file is in the same package
    """
    hex_filename = f"{clvm_filename}.hex"

    try:
        if pkg_resources.resource_exists(package_or_requirement, clvm_filename):
            # Establish whether the size is zero on entry
            full_path = pathlib.Path(pkg_resources.resource_filename(package_or_requirement, clvm_filename))
            output = full_path.parent / hex_filename
            compile_clvm(full_path, output, search_paths=[full_path.parent])

    except NotImplementedError:
        # pyinstaller doesn't support `pkg_resources.resource_exists`
        # so we just fall through to loading the hex clvm
        pass

    clvm_hex = pkg_resources.resource_string(package_or_requirement, hex_filename).decode("utf8")
    assert len(clvm_hex.strip()) != 0
    clvm_blob = bytes.fromhex(clvm_hex)
    return SerializedProgram.from_bytes(clvm_blob)


def load_clvm(clvm_filename, package_or_requirement=__name__) -> Program:
    return Program.from_bytes(bytes(load_serialized_clvm(clvm_filename, package_or_requirement=package_or_requirement)))
