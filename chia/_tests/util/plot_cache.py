"""Cache expensive plot lookups used by dynamically generated test chains.

The shared plot_cache.pickle is loaded for reuse, but never amended on exit.
Each successful test replaces its own recording under plot_cache_tests/, keyed
by its full parametrized pytest node ID. Recordings include cache hits, misses,
and empty qualities across fixture setup, the test, and fixture teardown.
Persistent fixture-chain generation is excluded: its proofs are already saved
in the blockchain file and validation does not perform plot lookups.

Qualities are keyed by (plot or plot-group ID, challenge), V1 full proofs by
(plot_id, challenge, index), and solved V2 proofs by (partial_proof_bytes,
member_plot_id). Cached V2 qualities include each member's plot index.

After workers finish, pytest replaces the shared cache with the union of test
recordings, regardless of the session's exit status. Partial runs retain recordings
for tests that were not run. Fully collected files prune removed/renamed tests
before execution; failed or interrupted tests retain their previous recordings.
Keep plot_cache_tests/ alongside the shared cache between runs: entries from an
old cache without per-test recordings cannot be attributed to unrun tests and are
dropped on the first publication.
There is no process-exit publisher.
"""

from __future__ import annotations

import hashlib
import logging
import pickle  # ruff: ignore[suspicious-pickle-import]
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from chia_rs import PartialProof
from chia_rs import solve_proof as _orig_solve_proof
from chia_rs.sized_bytes import bytes32
from filelock import FileLock

from chia.plotting.prover import QualityProtocol, V1Prover, V1Quality, V2Prover, V2Quality

log = logging.getLogger(__name__)

CACHE_FILENAME = "plot_cache.pickle"
TEST_CACHE_DIRECTORY = "plot_cache_tests"
CacheData = tuple[dict[Any, Any], dict[Any, Any], dict[Any, Any]]


@contextmanager
def record_test() -> Iterator[CacheData]:
    global _test_lookups
    previous = _test_lookups
    lookups: CacheData = ({}, {}, {})
    _test_lookups = lookups
    try:
        yield lookups
    finally:
        _test_lookups = previous


@contextmanager
def ignore_recording() -> Iterator[None]:
    """Keep fixture-chain generation out of the enclosing test's recording."""
    global _test_lookups
    previous = _test_lookups
    _test_lookups = None
    try:
        yield
    finally:
        _test_lookups = previous


def _record_lookup(part: int, key: Any, value: Any) -> None:
    if _test_lookups is not None:
        _test_lookups[part][key] = value


def test_cache_path(directory: Path, nodeid: str) -> Path:
    return directory / (hashlib.sha256(nodeid.encode()).hexdigest() + ".pickle")


def _write_atomic(path: Path, data: Any) -> None:
    temporary = path.with_name(path.name + f".{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_test_cache(directory: Path, nodeid: str, lookups: CacheData) -> None:
    path = test_cache_path(directory, nodeid)
    # Tests that never use plots need no file. An empty rerun removes old entries.
    if not any(lookups) and not directory.exists():
        return
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory / ".lock")):
        if any(lookups):
            _write_atomic(path, (nodeid, lookups))
        else:
            path.unlink(missing_ok=True)


def _read_test_cache(path: Path) -> tuple[str, CacheData] | None:
    try:
        nodeid, data = pickle.loads(path.read_bytes())  # ruff: ignore[suspicious-pickle-usage]
        if (
            not isinstance(nodeid, str)
            or test_cache_path(path.parent, nodeid) != path
            or not isinstance(data, tuple)
            or len(data) != 3
            or not all(isinstance(part, dict) for part in data)
        ):
            raise ValueError("invalid test plot cache")
        return nodeid, data
    except (OSError, ValueError, TypeError, EOFError, pickle.UnpicklingError):
        log.warning("plot_cache: ignoring invalid test recording %s", path, exc_info=True)
        return None


def prune_test_caches(directory: Path, collected: set[str], root: Path, *, files: set[str]) -> None:
    """Only prune missing IDs in fully collected files, or deleted source files."""
    if not directory.exists():
        return
    with FileLock(str(directory / ".lock")):
        for path in directory.glob("*.pickle"):
            recording = _read_test_cache(path)
            if recording is None:
                continue
            nodeid, _ = recording
            source = nodeid.split("::", 1)[0]
            if not (root / source).exists() or (source in files and nodeid not in collected):
                path.unlink()


def merge_test_caches(directory: Path, destination: Path) -> None:
    """Replace the shared cache, without retaining any unrecorded disk entries."""
    if not directory.exists():
        return
    merged: CacheData = ({}, {}, {})
    with FileLock(str(directory / ".lock")):
        for path in sorted(directory.glob("*.pickle")):
            recording = _read_test_cache(path)
            if recording is None:
                continue
            for target, entries in zip(merged, recording[1]):
                target.update(entries)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(destination) + ".lock"):
            _write_atomic(destination, merged)
    print(f"plot_cache: published {sum(map(len, merged))} entries ({destination.stat().st_size / 1e6:.2f} MB)")


# (plot or plot-group ID, challenge) -> list of serialized quality data
# V1: each entry is 32 bytes (quality bytes32)
# V2: each entry is (plot_index, serialized PartialProof bytes)
_qualities: dict[tuple[bytes, bytes], list[Any]] = {}

# (plot_id, challenge, index) -> proof bytes
_full_proofs: dict[tuple[bytes, bytes, int], bytes] = {}

# (partial_proof_bytes, plot_id) -> proof bytes
_solve_proofs: dict[tuple[bytes, bytes], bytes] = {}

_test_lookups: CacheData | None = None
_installed: bool = False
_hits: int = 0
_misses: int = 0


def _load_from_disk(path: Path) -> tuple[dict[Any, Any], dict[Any, Any], dict[Any, Any]]:
    if not path.exists():
        return {}, {}, {}
    try:
        data = pickle.loads(path.read_bytes())  # ruff: ignore[suspicious-pickle-usage]
        if isinstance(data, tuple) and len(data) == 3:
            return data[0], data[1], data[2]
    except Exception:
        log.exception("plot_cache: failed to read existing cache for merge")
    return {}, {}, {}


def load(plot_dir: Path) -> None:
    cache_path = plot_dir / CACHE_FILENAME
    if not plot_dir.exists():
        return
    try:
        with FileLock(str(cache_path) + ".lock"):
            disk_q, disk_fp, disk_sp = _load_from_disk(cache_path)
    except Exception:
        log.exception("plot_cache: failed to acquire lock for loading")
        return
    _qualities.update(disk_q)
    _full_proofs.update(disk_fp)
    _solve_proofs.update(disk_sp)
    total = len(_qualities) + len(_full_proofs) + len(_solve_proofs)
    if total > 0:
        print(f"plot_cache: loaded {total} entries from {cache_path}")


def cached_solve_proof(partial_proof: PartialProof, plot_id: bytes32, strength: int, k: int) -> bytes:
    global _hits, _misses
    key = (partial_proof.to_bytes(), bytes(plot_id))
    cached = _solve_proofs.get(key)
    if cached is not None:
        _record_lookup(2, key, cached)
        _hits += 1
        return cached
    result = _orig_solve_proof(partial_proof, plot_id, strength, k)
    _solve_proofs[key] = result
    _record_lookup(2, key, result)
    _misses += 1
    return result


def install(plot_dir: Path) -> None:
    global _installed
    if _installed:
        return
    _installed = True

    load(plot_dir)

    orig_v1_quals = V1Prover.get_qualities_for_challenge
    orig_v2_quals = V2Prover.get_qualities_for_challenge
    orig_v1_proof = V1Prover.get_full_proof

    def v1_qualities(self: V1Prover, challenge: bytes32) -> list[QualityProtocol]:
        global _hits, _misses
        key = (bytes(self.get_id()), bytes(challenge))
        cached = _qualities.get(key)
        if cached is not None:
            _record_lookup(0, key, cached)
            _hits += 1
            return [V1Quality(bytes32(q)) for q in cached]
        result = orig_v1_quals(self, challenge)
        _qualities[key] = [bytes(q.get_string()) for q in result]
        _record_lookup(0, key, _qualities[key])
        _misses += 1
        return result

    def v2_qualities(self: V2Prover, challenge: bytes32) -> list[QualityProtocol]:
        global _hits, _misses
        key = (bytes(self.get_id()), bytes(challenge))
        cached = _qualities.get(key)
        if cached is not None and all(isinstance(q, tuple) and len(q) == 2 for q in cached):
            _record_lookup(0, key, cached)
            _hits += 1
            return [V2Quality(PartialProof.from_bytes(q[1]), q[0], self.get_strength()) for q in cached]
        result = orig_v2_quals(self, challenge)
        _qualities[key] = [
            (q.get_plot_index(), q.get_partial_proof().to_bytes()) for q in result if isinstance(q, V2Quality)
        ]
        _record_lookup(0, key, _qualities[key])
        _misses += 1
        return result

    def v1_full_proof(self: V1Prover, challenge: bytes32, index: int, parallel_read: bool = True) -> bytes:
        global _hits, _misses
        key = (bytes(self.get_id()), bytes(challenge), index)
        cached = _full_proofs.get(key)
        if cached is not None:
            _record_lookup(1, key, cached)
            _hits += 1
            return cached
        result = orig_v1_proof(self, challenge, index, parallel_read)
        _full_proofs[key] = result
        _record_lookup(1, key, result)
        _misses += 1
        return result

    V1Prover.get_qualities_for_challenge = v1_qualities  # type: ignore[method-assign]
    V2Prover.get_qualities_for_challenge = v2_qualities  # type: ignore[method-assign]
    V1Prover.get_full_proof = v1_full_proof  # type: ignore[method-assign]

    setattr(__import__("chia.simulator.block_tools", fromlist=["solve_proof"]), "solve_proof", cached_solve_proof)
    setattr(__import__("chia.solver.solver", fromlist=["solve_proof"]), "solve_proof", cached_solve_proof)
