from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class TestFile:
    filename: str
    module: str
    repo_path: str

    def whole(self) -> Piece:
        return Piece(
            filename=self.filename,
            module=self.module,
            repo_path=self.repo_path,
            part_index=0,
            part_count=1,
        )


@dataclass(frozen=True)
class Piece:
    """One shard's slice of a test file.

    ``part_count == 1`` is the whole file, or the whole selected set when
    ``selector`` is set. Otherwise the file or selector is split into
    ``part_count`` contiguous collection-order chunks and this is ``part_index``
    (0-based).

    ``selector`` is either a test function name (``test_parser``) or a comma
    separated remainder selector (``~test_parser,~test_header_block``).
    """

    filename: str
    module: str
    repo_path: str
    part_index: int
    part_count: int
    selector: str | None = None

    @property
    def whole(self) -> bool:
        return self.part_count == 1


@dataclass(frozen=True)
class ShardEntry:
    filename: str
    selector: str | None
    part_index: int | None
    part_count: int | None


@dataclass(frozen=True)
class ShardSpec:
    path: str
    selector: str | None
    part_index: int
    part_count: int


def shard_bounds(n_items: int, part_count: int, part_index: int) -> tuple[int, int]:
    """Contiguous [start, end) slice. Sizes differ by at most one."""
    if part_count < 1:
        msg = f"part_count must be positive, got {part_count}"
        raise ValueError(msg)
    if part_index < 0 or part_index >= part_count:
        msg = f"part_index {part_index} outside 0..{part_count - 1}"
        raise ValueError(msg)
    if n_items < 0:
        msg = f"n_items must be non-negative, got {n_items}"
        raise ValueError(msg)
    base, extra = divmod(n_items, part_count)
    start = 0
    for i in range(part_index):
        start += base + (1 if i < extra else 0)
    size = base + (1 if part_index < extra else 0)
    return start, start + size


def _whole(test_file: TestFile) -> Piece:
    return test_file.whole()


def _piece(test_file: TestFile, part_index: int, part_count: int, selector: str | None = None) -> Piece:
    return Piece(
        filename=test_file.filename,
        module=test_file.module,
        repo_path=test_file.repo_path,
        part_index=part_index,
        part_count=part_count,
        selector=selector,
    )


def parse_shard_entry(entry: str) -> ShardEntry:
    """``test_foo.py`` is the whole file. ``test_foo.py=0/2`` is one slice.

    ``test_foo.py::test_name`` selects one test function and
    ``test_foo.py::test_name=0/2`` slices that function's cases. A selector
    beginning with ``~`` is a remainder selector.
    """
    if "=" in entry:
        left, fraction = entry.split("=", 1)
        index_text, count_text = fraction.split("/", 1)
        part_index: int | None = int(index_text)
        part_count: int | None = int(count_text)
    else:
        left = entry
        part_index = None
        part_count = None
    if "::" in left:
        filename, selector = left.split("::", 1)
    else:
        filename, selector = left, None
    return ShardEntry(filename, selector, part_index, part_count)


def _function_names(selector: str) -> tuple[str, ...]:
    if selector.startswith("~"):
        return tuple(part[1:] for part in selector.split(",") if part.startswith("~"))
    return (selector,)


def plan_explicit(files: Sequence[TestFile], shard_lists: Sequence[Sequence[str]]) -> list[list[Piece]]:
    """Place named files on the listed shards. Anything unnamed joins the last shard.

    A file named only by function selectors also gets a remainder piece on the
    last shard. That piece runs every test in the file whose function was not
    named, so function selectors never drop coverage.

    The last shard is the catch-all, so a new test file is still run and does
    not become its own setup-only job.
    """
    if len(shard_lists) == 0:
        msg = "matrix_shard_files must list at least one shard"
        raise ValueError(msg)
    by_name = {test_file.filename: test_file for test_file in files}
    mentioned: set[str] = set()
    whole_files: set[str] = set()
    file_parts: dict[str, list[tuple[int, int]]] = {}
    function_wholes: set[tuple[str, str]] = set()
    function_parts: dict[tuple[str, str], list[tuple[int, int]]] = {}
    function_order: dict[str, list[str]] = {}
    shards: list[list[Piece]] = []
    for shard in shard_lists:
        pieces: list[Piece] = []
        for entry in shard:
            parsed = parse_shard_entry(entry)
            filename = parsed.filename
            selector = parsed.selector
            test_file = by_name.get(filename)
            if test_file is None:
                msg = f"matrix_shard_files names missing file {filename}"
                raise ValueError(msg)
            if selector is None:
                if filename in whole_files or filename in function_wholes or filename in function_parts:
                    msg = f"{filename} mixes whole-file and function selectors"
                    raise ValueError(msg)
                if parsed.part_index is None or parsed.part_count is None:
                    if filename in mentioned:
                        msg = f"{filename} is listed more than once"
                        raise ValueError(msg)
                    mentioned.add(filename)
                    whole_files.add(filename)
                    pieces.append(_whole(test_file))
                    continue
                if filename in whole_files:
                    msg = f"{filename} is both a whole file and a split slice"
                    raise ValueError(msg)
                mentioned.add(filename)
                file_parts.setdefault(filename, []).append((parsed.part_index, parsed.part_count))
                pieces.append(_piece(test_file, parsed.part_index, parsed.part_count))
                continue
            if filename in whole_files or filename in file_parts:
                msg = f"{filename} mixes whole-file and function selectors"
                raise ValueError(msg)
            mentioned.add(filename)
            key = (filename, selector)
            if selector.startswith("~"):
                if parsed.part_index is not None or parsed.part_count is not None:
                    msg = f"{filename}::{selector} cannot be sliced"
                    raise ValueError(msg)
                if key in function_wholes:
                    msg = f"{filename}::{selector} is listed more than once"
                    raise ValueError(msg)
                function_wholes.add(key)
                pieces.append(_piece(test_file, 0, 1, selector))
                continue
            selectors = function_order.setdefault(filename, [])
            if selector not in selectors:
                selectors.append(selector)
            if parsed.part_index is None or parsed.part_count is None:
                if key in function_wholes or key in function_parts:
                    msg = f"{filename}::{selector} is listed more than once"
                    raise ValueError(msg)
                function_wholes.add(key)
                pieces.append(_piece(test_file, 0, 1, selector))
                continue
            if key in function_wholes:
                msg = f"{filename}::{selector} is both a whole selector and a split slice"
                raise ValueError(msg)
            function_parts.setdefault(key, []).append((parsed.part_index, parsed.part_count))
            pieces.append(_piece(test_file, parsed.part_index, parsed.part_count, selector))
        shards.append(pieces)
    for filename, parts in file_parts.items():
        counts = {part_count for _, part_count in parts}
        if len(counts) != 1:
            msg = f"{filename} uses more than one part count"
            raise ValueError(msg)
        part_count = counts.pop()
        indexes = sorted(part_index for part_index, _ in parts)
        if indexes != list(range(part_count)):
            msg = f"{filename} slices {indexes} are not 0..{part_count - 1} exactly once"
            raise ValueError(msg)
    for (filename, selector), parts in function_parts.items():
        counts = {part_count for _, part_count in parts}
        if len(counts) != 1:
            msg = f"{filename}::{selector} uses more than one part count"
            raise ValueError(msg)
        part_count = counts.pop()
        indexes = sorted(part_index for part_index, _ in parts)
        if indexes != list(range(part_count)):
            msg = f"{filename}::{selector} slices {indexes} are not 0..{part_count - 1} exactly once"
            raise ValueError(msg)
    remainder_shard = shards[-1]
    for filename, selectors in function_order.items():
        if any(fn == filename and sel.startswith("~") for fn, sel in function_wholes):
            continue
        remainder_selector = ",".join(f"~{selector}" for selector in dict.fromkeys(selectors))
        remainder_shard.append(_piece(by_name[filename], 0, 1, remainder_selector))
    catch_all = [_whole(test_file) for test_file in files if test_file.filename not in mentioned]
    shards[-1].extend(catch_all)
    if any(len(planned) == 0 for planned in shards):
        msg = "matrix_shard_files produced an empty shard"
        raise ValueError(msg)
    for planned in shards:
        planned.sort(key=lambda piece: (piece.repo_path, piece.part_index))
    return shards


def render_test_files(pieces: Sequence[Piece]) -> str:
    """Pytest arguments: optional ``--matrix-shard`` filters, then ``--pyargs``."""
    modules: list[str] = []
    specs: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        if piece.module not in seen:
            modules.append(piece.module)
            seen.add(piece.module)
        if piece.selector is not None:
            spec = f"{piece.repo_path}::{piece.selector}"
            if not piece.whole:
                spec += f"={piece.part_index}/{piece.part_count}"
            specs.append(spec)
        elif not piece.whole:
            specs.append(f"{piece.repo_path}={piece.part_index}/{piece.part_count}")
    pyargs = "--pyargs " + " ".join(modules)
    if len(specs) == 0:
        return pyargs
    # -p loads this module before pytest parses --matrix-shard. CI moves chia/
    # aside, so the option cannot live only in chia/_tests/conftest.py.
    filters = " ".join(f"--matrix-shard {spec}" for spec in specs)
    return f"-p chia._tests.matrix_shard {filters} {pyargs}"


def parse_matrix_shard_spec(spec: str) -> ShardSpec:
    if "=" in spec:
        left, fraction = spec.split("=", 1)
        index_text, count_text = fraction.split("/", 1)
        part_index = int(index_text)
        part_count = int(count_text)
    else:
        left = spec
        part_index = 0
        part_count = 1
    if "::" in left:
        path, selector = left.split("::", 1)
    else:
        path, selector = left, None
    return ShardSpec(path, selector, part_index, part_count)


def pieces_from_test_files(test_files: str) -> list[ShardSpec]:
    """Return one spec for every file (or file selector) in a row.

    A ``--pyargs`` module with no ``--matrix-shard`` spec is the whole file.
    """
    specs: list[ShardSpec] = []
    modules: list[str] = []
    arguments = test_files.split()
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-p":
            index += 2
            continue
        if argument == "--matrix-shard":
            specs.append(parse_matrix_shard_spec(arguments[index + 1]))
            index += 2
            continue
        if argument == "--pyargs":
            index += 1
            while index < len(arguments) and not arguments[index].startswith("--"):
                modules.append(arguments[index])
                index += 1
            continue
        msg = f"unrecognized test_files argument {argument!r} in {test_files!r}"
        raise ValueError(msg)
    covered: list[ShardSpec] = []
    for module in modules:
        repo_path = module.replace(".", "/") + ".py"
        matched = [spec for spec in specs if spec.path == repo_path]
        specs = [spec for spec in specs if spec.path != repo_path]
        if len(matched) == 0:
            covered.append(ShardSpec(repo_path, None, 0, 1))
        else:
            covered.extend(matched)
    if len(specs) > 0:
        msg = f"--matrix-shard paths missing from --pyargs: {sorted({spec.path for spec in specs})}"
        raise ValueError(msg)
    return covered


def assert_file_partition(expected: Iterable[str], test_file_rows: Iterable[str], copies: int = 1) -> None:
    """Every expected test file is covered by a complete, non-overlapping part set.

    A file may be covered by named function selectors plus one remainder
    selector. That is a complete partition, not a duplicated whole file.

    ``copies`` is the matrix ``--duplicates`` count: each part is scheduled that
    many times on purpose, and no more.
    """
    if copies < 1:
        msg = f"copies must be positive, got {copies}"
        raise ValueError(msg)
    expected_set = set(expected)
    seen: dict[str, list[ShardSpec]] = {}
    for test_files in test_file_rows:
        for spec in pieces_from_test_files(test_files):
            seen.setdefault(spec.path, []).append(spec)
    missing = expected_set - set(seen)
    extra = set(seen) - expected_set
    if len(missing) > 0 or len(extra) > 0:
        msg = f"shard file set mismatch, missing={sorted(missing)} extra={sorted(extra)}"
        raise AssertionError(msg)
    for repo_path, specs in sorted(seen.items()):
        selectors = {spec.selector for spec in specs}
        if selectors == {None}:
            counts = {spec.part_count for spec in specs}
            if len(counts) != 1:
                msg = f"{repo_path} mixed part counts {sorted(counts)}"
                raise AssertionError(msg)
            part_count = counts.pop()
            indexes = sorted(spec.part_index for spec in specs)
            expected_indexes = [part_index for part_index in range(part_count) for _ in range(copies)]
            if indexes != expected_indexes:
                msg = f"{repo_path} parts {indexes} are not 0..{part_count - 1} repeated {copies} time(s)"
                raise AssertionError(msg)
            continue
        if None in selectors:
            msg = f"{repo_path} mixes whole-file and function selectors"
            raise AssertionError(msg)
        by_selector: dict[str, list[ShardSpec]] = {}
        for spec in specs:
            assert spec.selector is not None
            by_selector.setdefault(spec.selector, []).append(spec)
        positive_names: set[str] = set()
        remainder_selectors: list[str] = []
        for selector, selector_specs in by_selector.items():
            counts = {spec.part_count for spec in selector_specs}
            if len(counts) != 1:
                msg = f"{repo_path}::{selector} mixed part counts {sorted(counts)}"
                raise AssertionError(msg)
            part_count = counts.pop()
            indexes = sorted(spec.part_index for spec in selector_specs)
            expected_indexes = [part_index for part_index in range(part_count) for _ in range(copies)]
            if indexes != expected_indexes:
                msg = f"{repo_path}::{selector} parts {indexes} are not 0..{part_count - 1} repeated {copies} time(s)"
                raise AssertionError(msg)
            if selector.startswith("~"):
                if part_count != 1:
                    msg = f"{repo_path} remainder selector cannot be sliced"
                    raise AssertionError(msg)
                remainder_selectors.append(selector)
            else:
                positive_names.add(selector)
        if len(remainder_selectors) == 0:
            msg = f"{repo_path} function selectors have no remainder"
            raise AssertionError(msg)
        if len(remainder_selectors) > 1:
            msg = f"{repo_path} has more than one remainder selector"
            raise AssertionError(msg)
        remainder_names = set(_function_names(remainder_selectors[0]))
        if not positive_names.issubset(remainder_names):
            msg = f"{repo_path} remainder does not exclude named functions {sorted(positive_names - remainder_names)}"
            raise AssertionError(msg)


def _normalized(path: str) -> str:
    return path.replace("\\", "/")


def _nodeid_file_matches(nodeid: str, spec_path: str, file_path: str = "") -> bool:
    normalized_nodeid = _normalized(nodeid)
    normalized_spec = _normalized(spec_path)
    if normalized_nodeid == normalized_spec or normalized_nodeid.startswith(normalized_spec + "::"):
        return True
    marker = "/" + normalized_spec
    if normalized_nodeid.endswith(marker) or (marker + "::") in normalized_nodeid:
        return True
    normalized_file = _normalized(file_path)
    return normalized_file.endswith(("/" + normalized_spec, normalized_spec))


def _nodeid_function(nodeid: str) -> str | None:
    if "::" not in nodeid:
        return None
    remainder = nodeid.split("::", 1)[1]
    head = remainder.split("[", 1)[0]
    return head.split("::")[-1]


def nodeid_matches(nodeid: str, spec_path: str, file_path: str = "", selector: str | None = None) -> bool:
    """Match a source nodeid, an installed nodeid, or the file path.

    CI nodeids look like ``.venv/lib/python3.12/site-packages/chia/_tests/...py::test``.
    ``--pyargs`` outside the root can also report ``::test_0`` while ``item.path``
    still ends with the spec. A selector matches the test function name, with or
    without a parametrized ``[id]`` suffix. A remainder selector excludes names.
    """
    if not _nodeid_file_matches(nodeid, spec_path, file_path):
        return False
    if selector is None:
        return True
    function = _nodeid_function(nodeid)
    if selector.startswith("~"):
        return function not in _function_names(selector)
    return function == selector


def _spec_text(spec: ShardSpec) -> str:
    text = f"{spec.path}::{spec.selector}" if spec.selector is not None else spec.path
    if spec.part_count != 1:
        text += f"={spec.part_index}/{spec.part_count}"
    return text


def filter_nodeids(
    nodeids: Sequence[str],
    specs: Sequence[str],
    file_paths: Sequence[str] | None = None,
) -> list[str]:
    """Keep every item whose file is whole, plus one slice of each split file or selector.

    A positive selector that matches nothing raises. That is the installed-id
    failure mode: a prefix check would otherwise drop every item or, if
    unmatched ids were kept, run the whole file on every shard. A remainder
    selector may be empty when every test in the file was named.
    """
    if len(specs) == 0:
        return list(nodeids)
    parsed = [parse_matrix_shard_spec(spec) for spec in specs]
    paths = list(dict.fromkeys(spec.path for spec in parsed))
    locations = list(file_paths) if file_paths is not None else [""] * len(nodeids)
    grouped: dict[str, list[tuple[str, str]]] = {path: [] for path in paths}
    rest: list[str] = []
    for nodeid, file_path in zip(nodeids, locations, strict=True):
        matched = False
        for path in paths:
            if _nodeid_file_matches(nodeid, path, file_path):
                grouped[path].append((nodeid, file_path))
                matched = True
                break
        if not matched:
            rest.append(nodeid)
    keep: set[str] = set(rest)
    for spec in parsed:
        group = grouped[spec.path]
        if len(group) == 0:
            msg = f"--matrix-shard {_spec_text(spec)} matched no collected tests"
            raise ValueError(msg)
        if spec.selector is None:
            selected = [nodeid for nodeid, _ in group]
        else:
            selected = [
                nodeid for nodeid, file_path in group if nodeid_matches(nodeid, spec.path, file_path, spec.selector)
            ]
            if not spec.selector.startswith("~") and len(selected) == 0:
                msg = f"--matrix-shard {_spec_text(spec)} matched no collected tests"
                raise ValueError(msg)
        start, end = shard_bounds(len(selected), spec.part_count, spec.part_index)
        chosen = selected[start:end]
        if len(chosen) == 0:
            if spec.selector is not None and spec.selector.startswith("~"):
                continue
            msg = f"--matrix-shard {_spec_text(spec)} selected no tests"
            raise ValueError(msg)
        keep.update(chosen)
    if len(keep) == 0:
        msg = "--matrix-shard selected no tests"
        raise ValueError(msg)
    return [nodeid for nodeid in nodeids if nodeid in keep]


def pytest_addoption(parser: object) -> None:
    """Register ``--matrix-shard`` when this module is loaded with ``-p``.

    pytest parses arguments before it imports ``chia/_tests/conftest.py`` from
    an installed package, and CI has already moved the source tree aside.
    """
    group = parser.getgroup("chia")  # type: ignore[attr-defined]
    group.addoption(
        "--matrix-shard",
        action="append",
        default=None,
        help=(
            "Run one contiguous slice of a test file. Repeat for each split file. "
            "Format: chia/_tests/.../test_foo.py=INDEX/COUNT. Set by the CI matrix."
        ),
    )


def pytest_collection_modifyitems(config: object, items: list[object]) -> None:
    specs = list(config.getoption("--matrix-shard") or [])  # type: ignore[attr-defined]
    if len(specs) == 0:
        return
    nodeids = [item.nodeid for item in items]  # type: ignore[attr-defined]
    file_paths = [str(getattr(item, "path", "")) for item in items]
    try:
        kept = filter_nodeids(nodeids, specs, file_paths)
    except ValueError as exc:
        import pytest

        raise pytest.UsageError(str(exc)) from exc
    keep = set(kept)
    deselected = [item for item in items if item.nodeid not in keep]  # type: ignore[attr-defined]
    if len(deselected) > 0:
        config.hook.pytest_deselected(items=deselected)  # type: ignore[attr-defined]
        items[:] = [item for item in items if item.nodeid in keep]  # type: ignore[attr-defined]
