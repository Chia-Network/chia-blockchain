import os
import sys
import tempfile
import traceback
from pathlib import Path

# TODO: can we make sure this matches the otherwise used copy?
from clvm_tools_rs import compile_clvm

here = Path(__file__).parent.resolve()
root = here.parent


def main() -> int:
    overall_fail = False

    print("Checking that all existing .clvm files compile to .clvm.hex that match existing caches:")
    print("")
    for clvm_path in root.rglob("*.clvm"):
        file_fail = False
        error = None

        try:
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

            if compiled_bytes != hex_bytes:
                file_fail = True
        except Exception:
            file_fail = True
            error = traceback.format_exc()

        if file_fail:
            print(f"FAIL    : {clvm_path}")
            if error is not None:
                print(error)
        else:
            print(f"    pass: {clvm_path}")

        if file_fail:
            overall_fail = True

    return 1 if overall_fail else 0


sys.exit(main())
