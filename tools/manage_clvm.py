from __future__ import annotations

import dataclasses
import hashlib
import json
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
cache_path = root.joinpath(".chia_cache", "manage_clvm.json")

# This is a work-around for fixing imports so they get the appropriate top level
# packages instead of those of the same name in the same directory as this program.
# This undoes the Python mis-feature meant to support 'scripts' that have not been
# installed by adding the script's directory to the import search path.  This is why
# it is simpler to just have all code get installed and all things you run be
# accessible via entry points.
sys.path = [path for path in sys.path if path != os.fspath(here)]

from clvm_tools_rs import compile_clvm  # noqa: E402

from chia.types.blockchain_format.serialized_program import SerializedProgram  # noqa: E402

clvm_suffix = ".clvm"
clsp_suffix = ".clsp"
hex_suffix = ".clsp.hex"
all_suffixes = {"clsp": clsp_suffix, "hex": hex_suffix, "clvm": clvm_suffix}
# TODO: these could be cli options
top_levels = {"chia"}
hashes_path = pathlib.Path("chia/wallet/puzzles/deployed_puzzle_hashes.json")

HASHES: typing.Dict[str, str] = json.loads(hashes_path.read_text()) if hashes_path.exists() else {}


class ManageClvmError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class LoadClvmPathError(Exception):
    missing_files: typing.List[str]


class CacheEntry(typing.TypedDict):
    clsp: str
    hex: str
    hash: str


CacheEntries = typing.Dict[str, CacheEntry]
CacheVersion = typing.List[int]
current_cache_version: CacheVersion = [1]


class CacheVersionError(ManageClvmError):
    pass


class NoCacheVersionError(CacheVersionError):
    def __init__(self) -> None:
        super().__init__("Cache must specify a version, none found")


class WrongCacheVersionError(CacheVersionError):
    def __init__(self, found_version: object, expected_version: CacheVersion) -> None:
        self.found_version = found_version
        self.expected_version = expected_version
        super().__init__(f"Cache has wrong version, expected {expected_version!r} got: {found_version!r}")


class Cache(typing.TypedDict):
    entries: CacheEntries
    version: CacheVersion


def create_empty_cache() -> Cache:
    return {
        "entries": {},
        "version": current_cache_version,
    }


def load_cache(file: typing.IO[str]) -> Cache:
    loaded_cache = typing.cast(Cache, json.load(file))
    try:
        loaded_version = loaded_cache["version"]
    except KeyError as e:
        raise NoCacheVersionError() from e

    if loaded_version != current_cache_version:
        raise WrongCacheVersionError(found_version=loaded_version, expected_version=current_cache_version)

    return loaded_cache


def dump_cache(cache: Cache, file: typing.IO[str]) -> None:
    json.dump(cache, file, indent=4)


def generate_hash_bytes(hex_bytes: bytes) -> bytes:
    cleaned_blob = bytes.fromhex(hex_bytes.decode("utf-8"))
    serialize_program = SerializedProgram.from_bytes(cleaned_blob)
    return serialize_program.get_tree_hash()


@typing_extensions.final
@dataclasses.dataclass(frozen=True)
class ClvmPaths:
    clvm: pathlib.Path
    hex: pathlib.Path
    hash: str

    @classmethod
    def from_clvm(cls, clvm: pathlib.Path, raise_on_missing: bool = True) -> ClvmPaths:
        hex_path = clvm.with_name(clvm.name[: -len(clsp_suffix)] + hex_suffix)
        stem_filename = clvm.with_name(clvm.name[: -len(clsp_suffix)]).stem
        missing_files = []
        if not hex_path.exists():
            missing_files.append(str(hex_path))
        if stem_filename not in HASHES:
            missing_files.append(f"{stem_filename} entry in {hashes_path}")
        if missing_files != [] and raise_on_missing:
            raise LoadClvmPathError(missing_files)
        return cls(
            clvm=clvm,
            hex=hex_path,
            hash=stem_filename,
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
            hash=bytes.fromhex(HASHES[paths.hash]),
        )

    @classmethod
    def from_hex_bytes(cls, hex_bytes: bytes) -> ClvmBytes:
        return cls(
            hex=hex_bytes,
            hash=generate_hash_bytes(hex_bytes=hex_bytes),
        )


# These files have the wrong extension for now so we'll just manually exclude them
excludes: typing.Set[str] = set()


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


def create_cache_entry(reference_paths: ClvmPaths, reference_bytes: ClvmBytes) -> CacheEntry:
    source_bytes = reference_paths.clvm.read_bytes()

    clvm_hasher = hashlib.sha256()
    clvm_hasher.update(source_bytes)

    hex_hasher = hashlib.sha256()
    hex_hasher.update(reference_bytes.hex)

    hash_hasher = hashlib.sha256()
    hash_hasher.update(reference_bytes.hash)

    return {
        "clsp": clvm_hasher.hexdigest(),
        "hex": hex_hasher.hexdigest(),
        "hash": hash_hasher.hexdigest(),
    }


@click.group()
def main() -> None:
    pass


@main.command()
@click.option("--use-cache/--no-cache", default=True, show_default=True, envvar="USE_CACHE")
@click.option("--fix-hashfile-trailing-whitespace", default=True, show_default=True)
def check(use_cache: bool, fix_hashfile_trailing_whitespace: bool) -> int:
    used_excludes = set()
    overall_fail = False

    cache: Cache
    if not use_cache:
        cache = create_empty_cache()
    else:
        try:
            print(f"Attempting to load cache from: {cache_path}")
            with cache_path.open(mode="r") as file:
                cache = load_cache(file=file)
        except FileNotFoundError:
            print("Cache not found, starting fresh")
            cache = create_empty_cache()
        except NoCacheVersionError:
            print("Ignoring cache due to lack of version")
            cache = create_empty_cache()
        except WrongCacheVersionError as e:
            print(f"Ignoring cache due to incorrect version, expected {e.expected_version!r} got: {e.found_version!r}")
            cache = create_empty_cache()

    cache_entries = cache["entries"]
    cache_modified = False

    found_stems = find_stems(top_levels)
    found = found_stems["hex"]
    suffix = all_suffixes["hex"]
    extra = found - found_stems["clsp"]

    print()
    print(f"Extra {suffix} files:")

    if len(extra) == 0:
        print("    -")
    else:
        overall_fail = True
        for stem in extra:
            print(f"    {stem.with_name(stem.name + suffix)}")

    print()
    print("Checking that no .clvm files begin with `(mod`")
    for stem_path in sorted(found_stems["clvm"]):
        with open(stem_path.with_name(stem_path.name + clvm_suffix)) as file:
            file_lines = file.readlines()
            for line in file_lines:
                non_comment: str = line.split(";")[0]
                if "(" in non_comment:
                    paren_index: int = non_comment.find("(")
                    if len(non_comment) >= paren_index + 4 and non_comment[paren_index : paren_index + 4] == "(mod":
                        overall_fail = True
                        print(f"FAIL    : {stem_path.name + clvm_suffix} contains `(mod`")
                    break

    missing_files: typing.List[str] = []
    all_hash_stems: typing.List[str] = []

    print()
    print("Checking that all existing .clsp files compile to .clsp.hex that match existing caches:")
    for stem_path in sorted(found_stems["clsp"]):
        clvm_path = stem_path.with_name(stem_path.name + clsp_suffix)
        if clvm_path.name in excludes:
            used_excludes.add(clvm_path.name)
            continue

        file_fail = False
        error = None

        cache_key = str(stem_path)
        try:
            try:
                reference_paths = ClvmPaths.from_clvm(clvm=clvm_path)
            except LoadClvmPathError as e:
                missing_files.extend(e.missing_files)
                continue
            all_hash_stems.append(reference_paths.hash)
            reference_bytes = ClvmBytes.from_clvm_paths(paths=reference_paths)

            new_cache_entry = create_cache_entry(reference_paths=reference_paths, reference_bytes=reference_bytes)
            existing_cache_entry = cache_entries.get(cache_key)
            cache_hit = new_cache_entry == existing_cache_entry

            if not cache_hit:
                with tempfile.TemporaryDirectory() as temporary_directory:
                    generated_paths = ClvmPaths.from_clvm(
                        clvm=pathlib.Path(temporary_directory).joinpath(f"{reference_paths.clvm.name}"),
                        raise_on_missing=False,
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
                else:
                    cache_modified = True
                    cache_entries[cache_key] = new_cache_entry
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

    if missing_files != []:
        overall_fail = True
        print()
        print("Missing files (run tools/manage_clvm.py build to build them):")
        for filename in missing_files:
            print(f" - {filename}")

    unused_excludes = sorted(excludes - used_excludes)
    if len(unused_excludes) > 0:
        overall_fail = True
        print()
        print("Unused excludes:")

        for exclude in unused_excludes:
            print(f"    {exclude}")

    extra_hashes = [key for key in HASHES if key not in all_hash_stems]
    if extra_hashes != []:
        overall_fail = True
        print()
        print("Hashes without corresponding files:")
        for extra_hash in extra_hashes:
            print(f"    {extra_hash}")

    if use_cache and cache_modified:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open(mode="w") as file:
            dump_cache(cache=cache, file=file)

    if fix_hashfile_trailing_whitespace:
        print(f"Original File: {hashes_path.read_text()!r}")
        file_output = json.dumps(HASHES, indent=4, sort_keys=True) + '\n'
        print(f"New File: {file_output!r}")
        hashes_path.write_text(json.dumps(HASHES, indent=4, sort_keys=True) + "\n")

    return 1 if overall_fail else 0


@main.command()
def build() -> int:
    overall_fail = False

    found_stems = find_stems(top_levels, suffixes={"clsp": clsp_suffix})
    hash_stems = []
    new_hashes = HASHES.copy()

    print(f"Building all existing {clsp_suffix} files to {hex_suffix}:")
    for stem_path in sorted(found_stems["clsp"]):
        clvm_path = stem_path.with_name(stem_path.name + clsp_suffix)
        if clvm_path.name in excludes:
            continue

        file_fail = False
        error = None

        try:
            reference_paths = ClvmPaths.from_clvm(clvm=clvm_path, raise_on_missing=False)

            with tempfile.TemporaryDirectory() as temporary_directory:
                generated_paths = ClvmPaths.from_clvm(
                    clvm=pathlib.Path(temporary_directory).joinpath(f"{reference_paths.clvm.name}"),
                    raise_on_missing=False,
                )

                compile_clvm(
                    input_path=os.fspath(reference_paths.clvm),
                    output_path=os.fspath(generated_paths.hex),
                    search_paths=[os.fspath(reference_paths.clvm.parent)],
                )

                generated_bytes = ClvmBytes.from_hex_bytes(hex_bytes=generated_paths.hex.read_bytes())
                reference_paths.hex.write_bytes(generated_bytes.hex)

                # Only add hashes to json file if they didn't already exist in it
                hash_stems.append(reference_paths.hash)
                if reference_paths.hash not in new_hashes:
                    new_hashes[reference_paths.hash] = ClvmBytes.from_clvm_paths(reference_paths).hash.hex()
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

    hashes_path.write_text(
        json.dumps(
            {key: value for key, value in new_hashes.items() if key in hash_stems},  # filter out not found files
            indent=4,
            sort_keys=True,
        )
        + "\n"
    )

    return 1 if overall_fail else 0


sys.exit(main(auto_envvar_prefix="CHIA_MANAGE_CLVM"))
