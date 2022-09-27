from __future__ import annotations

import dataclasses
import os
import pathlib
import sys
import tempfile
import traceback
import typing

import click
import typing_extensions

here = pathlib.Path(__file__).parent.resolve()
root = here.parent

# This is a work-around for fixing imports so they get the appropriate top level
# packages instead of those of the same name in the same directory as this program.
# This undoes the Python mis-feature meant to support 'scripts' that have not been
# installed by adding the script's directory to the import search path.  This is why
# it is simpler to just have all code get installed and all things you run be
# accessible via entry points.
sys.path = [path for path in sys.path if path != os.fspath(here)]

from clvm_tools_rs import compile_clvm  # noqa: E402

from chia.types.blockchain_format.program import SerializedProgram  # noqa: E402

clvm_suffix = ".clvm"
hex_suffix = ".clvm.hex"
hash_suffix = ".clvm.hex.sha256tree"
all_suffixes = {"clvm": clvm_suffix, "hex": hex_suffix, "hash": hash_suffix}
# TODO: could be cli options
top_levels = {"chia"}


def generate_hash_bytes(hex_bytes: bytes) -> bytes:
    cleaned_blob = bytes.fromhex(hex_bytes.decode("utf-8"))
    serialize_program = SerializedProgram.from_bytes(cleaned_blob)
    result = serialize_program.get_tree_hash().hex()
    return (result + "\n").encode("utf-8")


@typing_extensions.final
@dataclasses.dataclass(frozen=True)
class ClvmPaths:
    clvm: pathlib.Path
    hex: pathlib.Path
    hash: pathlib.Path

    @classmethod
    def from_clvm(cls, clvm: pathlib.Path) -> ClvmPaths:
        return cls(
            clvm=clvm,
            hex=clvm.with_name(clvm.name[: -len(clvm_suffix)] + hex_suffix),
            hash=clvm.with_name(clvm.name[: -len(clvm_suffix)] + hash_suffix),
        )


@typing_extensions.final
@dataclasses.dataclass(frozen=True)
class ClvmBytes:
    hex: bytes
    hash: bytes

    @classmethod
    def from_clvm_paths(cls, paths: ClvmPaths) -> ClvmBytes:
        return cls(
            hex=paths.hex.read_bytes(),
            hash=paths.hash.read_bytes(),
        )

    @classmethod
    def from_hex_bytes(cls, hex_bytes: bytes) -> ClvmBytes:
        return cls(
            hex=hex_bytes,
            hash=generate_hash_bytes(hex_bytes=hex_bytes),
        )


# These files have the wrong extension for now so we'll just manually exclude them
excludes = {"condition_codes.clvm", "create-lock-puzzlehash.clvm"}


def find_stems(
    top_levels: typing.Set[str],
    suffixes: typing.Mapping[str, str] = all_suffixes,
) -> typing.Dict[str, typing.Set[pathlib.Path]]:
    found_stems = {
        name: {
            path.with_name(path.name[: -len(suffix)])
            for top_level in top_levels
            for path in root.joinpath(top_level).rglob(f"**/*{suffix}")
        }
        for name, suffix in suffixes.items()
    }
    return found_stems


@click.group()
def main() -> None:
    pass


@main.command()
def check() -> int:
    used_excludes = set()
    overall_fail = False

    found_stems = find_stems(top_levels)
    for name in ["hex", "hash"]:
        found = found_stems[name]
        suffix = all_suffixes[name]
        extra = found - found_stems["clvm"]

        print()
        print(f"Extra {suffix} files:")

        if len(extra) == 0:
            print("    -")
        else:
            overall_fail = True
            for stem in extra:
                print(f"    {stem.with_name(stem.name + suffix)}")

    print()
    print("Checking that all existing .clvm files compile to .clvm.hex that match existing caches:")
    for stem_path in sorted(found_stems["clvm"]):
        clvm_path = stem_path.with_name(stem_path.name + clvm_suffix)
        if clvm_path.name in excludes:
            used_excludes.add(clvm_path.name)
            continue

        file_fail = False
        error = None

        try:
            reference_paths = ClvmPaths.from_clvm(clvm=clvm_path)
            reference_bytes = ClvmBytes.from_clvm_paths(paths=reference_paths)

            with tempfile.TemporaryDirectory() as temporary_directory:
                generated_paths = ClvmPaths.from_clvm(
                    clvm=pathlib.Path(temporary_directory).joinpath(f"generated{clvm_suffix}")
                )

                compile_clvm(
                    input_path=os.fspath(reference_paths.clvm),
                    output_path=os.fspath(generated_paths.hex),
                    search_paths=[os.fspath(reference_paths.clvm.parent)],
                )

                generated_bytes = ClvmBytes.from_hex_bytes(hex_bytes=generated_paths.hex.read_bytes())

            if generated_bytes != reference_bytes:
                file_fail = True
                error = f"        reference: {reference_bytes!r}\n"
                error += f"        generated: {generated_bytes!r}"
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

    unused_excludes = sorted(excludes - used_excludes)
    if len(unused_excludes) > 0:
        overall_fail = True
        print()
        print("Unused excludes:")

        for exclude in unused_excludes:
            print(f"    {exclude}")

    return 1 if overall_fail else 0


@main.command()
def build() -> int:
    overall_fail = False

    found_stems = find_stems(top_levels, suffixes={"clvm": clvm_suffix})

    print(f"Building all existing {clvm_suffix} files to {hex_suffix}:")
    for stem_path in sorted(found_stems["clvm"]):
        clvm_path = stem_path.with_name(stem_path.name + clvm_suffix)
        if clvm_path.name in excludes:
            continue

        file_fail = False
        error = None

        try:
            reference_paths = ClvmPaths.from_clvm(clvm=clvm_path)

            with tempfile.TemporaryDirectory() as temporary_directory:
                generated_paths = ClvmPaths.from_clvm(
                    clvm=pathlib.Path(temporary_directory).joinpath(f"generated{clvm_suffix}")
                )

                compile_clvm(
                    input_path=os.fspath(reference_paths.clvm),
                    output_path=os.fspath(generated_paths.hex),
                    search_paths=[os.fspath(reference_paths.clvm.parent)],
                )

                generated_bytes = ClvmBytes.from_hex_bytes(hex_bytes=generated_paths.hex.read_bytes())
                reference_paths.hex.write_bytes(generated_bytes.hex)
        except Exception:
            file_fail = True
            error = traceback.format_exc()

        if file_fail:
            print(f"FAIL     : {clvm_path}")
            if error is not None:
                print(error)
        else:
            print(f"    built: {clvm_path}")

        if file_fail:
            overall_fail = True

    return 1 if overall_fail else 0


sys.exit(main())
