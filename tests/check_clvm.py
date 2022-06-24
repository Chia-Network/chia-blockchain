import os
import sys
import tempfile
from pathlib import Path

# TODO: can we make sure this matches the otherwise used copy?
from clvm_tools_rs import compile_clvm

here = Path(__file__).parent.resolve()
root = here.parent


def main() -> int:
    fail = False

    print("Checking that all existing .clvm files compile to .clvm.hex that match existing caches:")
    print("")
    for clvm_path in root.rglob("*.clvm"):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory).joinpath("hex")
            compile_clvm(
                input_path=os.fspath(clvm_path),
                output_path=os.fspath(path),
                search_paths=[os.fspath(clvm_path.parent)],
            )
            compiled_bytes = path.read_bytes()

        hex_path = clvm_path.with_name(f"{clvm_path.name}.hex")
        hex_bytes = hex_path.read_bytes()

        if compiled_bytes == hex_bytes:
            print(f"    pass: {clvm_path}")
        else:
            fail = True
            print(f"FAIL    : {clvm_path}")

    return 1 if fail else 0


sys.exit(main())
