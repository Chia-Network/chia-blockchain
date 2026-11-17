from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

# Split a file across shards only when it is meaningfully heavier than the
# per-shard target. A file just over the target stays whole so it is not cut
# in half and then stacked onto the next-heaviest file.
SPLIT_RATIO = 1.5


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

    ``part_count == 1`` is the whole file. Otherwise the file is split into
    ``part_count`` contiguous collection-order chunks and this is ``part_index``
    (0-based).
    """

    filename: str
    module: str
    repo_path: str
    part_index: int
    part_count: int

    @property
    def whole(self) -> bool:
        return self.part_count == 1


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


def _piece(test_file: TestFile, part_index: int, part_count: int) -> Piece:
    return Piece(
        filename=test_file.filename,
        module=test_file.module,
        repo_path=test_file.repo_path,
        part_index=part_index,
        part_count=part_count,
    )


def plan_contiguous(files: Sequence[TestFile], shards: int) -> list[list[Piece]]:
    """Equal-count contiguous chunks of the sorted file list.

    When there are fewer files than shards, extra shards split files so the
    caller still gets ``shards`` non-empty rows (a one-file directory can be
    two shards).
    """
    if shards < 1:
        msg = f"shards must be positive, got {shards}"
        raise ValueError(msg)
    if shards == 1 or len(files) == 0:
        return [[_whole(test_file) for test_file in files]]
    if len(files) >= shards:
        chunks: list[list[Piece]] = []
        base, extra = divmod(len(files), shards)
        start = 0
        for shard in range(shards):
            size = base + (1 if shard < extra else 0)
            chunks.append([_whole(test_file) for test_file in files[start : start + size]])
            start += size
        return chunks

    part_counts = [1] * len(files)
    extra_parts = shards - len(files)
    cursor = 0
    while extra_parts:
        part_counts[cursor % len(files)] += 1
        extra_parts -= 1
        cursor += 1
    planned: list[list[Piece]] = []
    for test_file, part_count in zip(files, part_counts):
        for part_index in range(part_count):
            planned.append([_piece(test_file, part_index, part_count)])
    return planned


def plan_duration_balanced(
    files: Sequence[TestFile],
    shards: int,
    weights: Mapping[str, float],
) -> list[list[Piece]]:
    """Longest-processing-time pack. Heavy files split into contiguous parts.

    ``weights`` maps a filename to a relative duration (worker-minutes on the
    slowest OS). Filenames that are missing weigh 1, so a new test file is
    still scheduled and lands on the lightest shard.
    """
    if shards < 1:
        msg = f"shards must be positive, got {shards}"
        raise ValueError(msg)
    if shards == 1 or len(files) == 0:
        return [[_whole(test_file) for test_file in files]]

    weighted = [(test_file, float(weights.get(test_file.filename, 1.0))) for test_file in files]
    total = sum(weight for _, weight in weighted)
    if total <= 0:
        return plan_contiguous(files, shards)
    target = total / shards

    part_counts: list[tuple[TestFile, int, float]] = []
    for test_file, weight in weighted:
        if weight > target * SPLIT_RATIO:
            part_count = min(shards, max(2, math.ceil(weight / target)))
        else:
            part_count = 1
        part_counts.append((test_file, part_count, weight))

    def piece_total() -> int:
        return sum(part_count for _, part_count, _ in part_counts)

    while piece_total() < shards:
        growable = [index for index, (_, part_count, _) in enumerate(part_counts) if part_count < shards]
        if len(growable) == 0:
            break
        index = max(growable, key=lambda i: (part_counts[i][2] / part_counts[i][1], part_counts[i][2]))
        test_file, part_count, weight = part_counts[index]
        part_counts[index] = (test_file, part_count + 1, weight)

    expanded: list[tuple[Piece, float]] = []
    for test_file, part_count, weight in part_counts:
        for part_index in range(part_count):
            expanded.append((_piece(test_file, part_index, part_count), weight / part_count))
    expanded.sort(key=lambda item: (-item[1], item[0].repo_path, item[0].part_index))

    bins: list[list[Piece]] = [[] for _ in range(shards)]
    loads = [0.0] * shards
    members: list[set[str]] = [set() for _ in range(shards)]
    for piece, weight in expanded:
        candidates = [index for index in range(shards) if piece.repo_path not in members[index]]
        if len(candidates) == 0:
            candidates = list(range(shards))
        chosen = min(candidates, key=lambda index: (loads[index], index))
        bins[chosen].append(piece)
        loads[chosen] += weight
        members[chosen].add(piece.repo_path)

    if any(len(bin_) == 0 for bin_ in bins):
        msg = f"duration packing left an empty shard for {shards} shards"
        raise ValueError(msg)
    for bin_ in bins:
        bin_.sort(key=lambda piece: (piece.repo_path, piece.part_index))
    return bins


def plan_shards(
    files: Sequence[TestFile],
    shards: int,
    weights: Mapping[str, float] | None,
) -> list[list[Piece]]:
    if weights:
        return plan_duration_balanced(files, shards, weights)
    return plan_contiguous(files, shards)


def render_test_files(pieces: Sequence[Piece]) -> str:
    """Pytest arguments: optional ``--matrix-shard`` filters, then ``--pyargs``."""
    modules: list[str] = []
    specs: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        if piece.module not in seen:
            modules.append(piece.module)
            seen.add(piece.module)
        if not piece.whole:
            specs.append(f"{piece.repo_path}={piece.part_index}/{piece.part_count}")
    pyargs = "--pyargs " + " ".join(modules)
    if len(specs) == 0:
        return pyargs
    filters = " ".join(f"--matrix-shard {spec}" for spec in specs)
    return f"{filters} {pyargs}"


def parse_matrix_shard_spec(spec: str) -> tuple[str, int, int]:
    path, fraction = spec.split("=", 1)
    index_text, count_text = fraction.split("/", 1)
    return path, int(index_text), int(count_text)


def pieces_from_test_files(test_files: str) -> list[tuple[str, int, int]]:
    """Return ``(repo_path, part_index, part_count)`` for every file in a row.

    A ``--pyargs`` module with no ``--matrix-shard`` spec is the whole file.
    """
    specs: dict[str, tuple[int, int]] = {}
    modules: list[str] = []
    arguments = test_files.split()
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--matrix-shard":
            path, part_index, part_count = parse_matrix_shard_spec(arguments[index + 1])
            specs[path] = (part_index, part_count)
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
    covered: list[tuple[str, int, int]] = []
    for module in modules:
        repo_path = module.replace(".", "/") + ".py"
        part_index, part_count = specs.pop(repo_path, (0, 1))
        covered.append((repo_path, part_index, part_count))
    if len(specs) > 0:
        msg = f"--matrix-shard paths missing from --pyargs: {sorted(specs)}"
        raise ValueError(msg)
    return covered


def assert_file_partition(expected: Iterable[str], test_file_rows: Iterable[str], copies: int = 1) -> None:
    """Every expected test file is covered by a complete, non-overlapping part set.

    ``copies`` is the matrix ``--duplicates`` count: each part is scheduled that
    many times on purpose, and no more.
    """
    if copies < 1:
        msg = f"copies must be positive, got {copies}"
        raise ValueError(msg)
    expected_set = set(expected)
    seen: dict[str, list[tuple[int, int]]] = {}
    for test_files in test_file_rows:
        for repo_path, part_index, part_count in pieces_from_test_files(test_files):
            seen.setdefault(repo_path, []).append((part_index, part_count))
    missing = expected_set - set(seen)
    extra = set(seen) - expected_set
    if len(missing) > 0 or len(extra) > 0:
        msg = f"shard file set mismatch, missing={sorted(missing)} extra={sorted(extra)}"
        raise AssertionError(msg)
    for repo_path, parts in sorted(seen.items()):
        counts = {part_count for _, part_count in parts}
        if len(counts) != 1:
            msg = f"{repo_path} mixed part counts {sorted(counts)}"
            raise AssertionError(msg)
        part_count = counts.pop()
        indexes = sorted(part_index for part_index, _ in parts)
        expected_indexes = [part_index for part_index in range(part_count) for _ in range(copies)]
        if indexes != expected_indexes:
            msg = f"{repo_path} parts {indexes} are not 0..{part_count - 1} repeated {copies} time(s)"
            raise AssertionError(msg)


def filter_nodeids(nodeids: Sequence[str], specs: Sequence[str]) -> list[str]:
    """Keep every item whose file is whole, plus one contiguous slice of each split file."""
    if len(specs) == 0:
        return list(nodeids)
    parsed: dict[str, tuple[int, int]] = {}
    for spec in specs:
        path, part_index, part_count = parse_matrix_shard_spec(spec)
        parsed[path] = (part_index, part_count)
    grouped: dict[str, list[str]] = {path: [] for path in parsed}
    rest: list[str] = []
    for nodeid in nodeids:
        matched = False
        for path in parsed:
            if nodeid == path or nodeid.startswith(path + "::"):
                grouped[path].append(nodeid)
                matched = True
                break
        if not matched:
            rest.append(nodeid)
    keep: set[str] = set(rest)
    for path, (part_index, part_count) in parsed.items():
        group = grouped[path]
        start, end = shard_bounds(len(group), part_count, part_index)
        keep.update(group[start:end])
    return [nodeid for nodeid in nodeids if nodeid in keep]
