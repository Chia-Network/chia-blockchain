"""
Persistent cache for expensive plot operations: get_qualities_for_challenge(),
get_full_proof(), and solve_proof().

The cache is stored in the plots directory as `.plot_cache.pickle` and is keyed
by (plot_id, challenge) for qualities and full proofs, and by
(partial_proof_bytes, plot_id) for solve_proof.

Call install() to monkeypatch the prover classes and solve_proof. The cache is
loaded from disk on first install and saved on process exit.
"""

from __future__ import annotations

import atexit
import logging
import pickle  # noqa: S403
from pathlib import Path
from typing import Any

from chia_rs import PartialProof
from chia_rs import solve_proof as _orig_solve_proof
from chia_rs.sized_bytes import bytes32
from filelock import FileLock

from chia.plotting.prover import QualityProtocol, V1Prover, V1Quality, V2Prover, V2Quality

log = logging.getLogger(__name__)

CACHE_FILENAME = ".plot_cache.pickle"

# (plot_id, challenge) -> list of serialized quality data
# V1: each entry is 32 bytes (quality bytes32)
# V2: each entry is serialized PartialProof bytes
_qualities: dict[tuple[bytes, bytes], list[bytes]] = {}

# (plot_id, challenge, index) -> proof bytes
_full_proofs: dict[tuple[bytes, bytes, int], bytes] = {}

# (partial_proof_bytes, plot_id) -> proof bytes
_solve_proofs: dict[tuple[bytes, bytes], bytes] = {}

_installed: bool = False
_cache_path: Path | None = None
_hits: int = 0
_misses: int = 0


def _load_from_disk(path: Path) -> tuple[dict[Any, Any], dict[Any, Any], dict[Any, Any]]:
    if not path.exists():
        return {}, {}, {}
    try:
        data = pickle.loads(path.read_bytes())  # noqa: S301
        if isinstance(data, tuple) and len(data) == 3:
            return data[0], data[1], data[2]
    except Exception:
        log.exception("plot_cache: failed to read existing cache for merge")
    return {}, {}, {}


def _save() -> None:
    total_lookups = _hits + _misses
    hit_pct = f"{_hits * 100 / total_lookups:.1f}%" if total_lookups > 0 else "n/a"
    if _misses > 0 and _cache_path is not None:
        try:
            with FileLock(str(_cache_path) + ".lock"):
                disk_q, disk_fp, disk_sp = _load_from_disk(_cache_path)
                disk_q.update(_qualities)
                disk_fp.update(_full_proofs)
                disk_sp.update(_solve_proofs)
                data = (disk_q, disk_fp, disk_sp)
                _cache_path.write_bytes(pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL))
                total = len(disk_q) + len(disk_fp) + len(disk_sp)
            print(f"plot_cache: saved {total} entries to {_cache_path}")
        except Exception:
            log.exception("plot_cache: failed to save")
    if total_lookups > 0:
        print(f"plot_cache: hits={_hits} misses={_misses} hit_rate={hit_pct}")


def load(plot_dir: Path) -> None:
    global _cache_path
    cache_path = plot_dir / CACHE_FILENAME
    if not plot_dir.exists():
        return
    _cache_path = cache_path
    try:
        with FileLock(str(_cache_path) + ".lock"):
            disk_q, disk_fp, disk_sp = _load_from_disk(_cache_path)
    except Exception:
        log.exception("plot_cache: failed to acquire lock for loading")
        return
    _qualities.update(disk_q)
    _full_proofs.update(disk_fp)
    _solve_proofs.update(disk_sp)
    total = len(_qualities) + len(_full_proofs) + len(_solve_proofs)
    if total > 0:
        print(f"plot_cache: loaded {total} entries from {_cache_path}")


def cached_solve_proof(partial_proof: PartialProof, plot_id: bytes32, strength: int, k: int) -> bytes:
    global _hits, _misses
    key = (partial_proof.to_bytes(), bytes(plot_id))
    cached = _solve_proofs.get(key)
    if cached is not None:
        _hits += 1
        return cached
    result = _orig_solve_proof(partial_proof, plot_id, strength, k)
    _solve_proofs[key] = result
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
            _hits += 1
            return [V1Quality(bytes32(q)) for q in cached]
        result = orig_v1_quals(self, challenge)
        _qualities[key] = [bytes(q.get_string()) for q in result]
        _misses += 1
        return result

    def v2_qualities(self: V2Prover, challenge: bytes32) -> list[QualityProtocol]:
        global _hits, _misses
        key = (bytes(self.get_id()), bytes(challenge))
        cached = _qualities.get(key)
        if cached is not None:
            _hits += 1
            return [V2Quality(PartialProof.from_bytes(q), self.get_strength()) for q in cached]
        result = orig_v2_quals(self, challenge)
        _qualities[key] = [q.get_partial_proof().to_bytes() for q in result]  # type: ignore[attr-defined]
        _misses += 1
        return result

    def v1_full_proof(self: V1Prover, challenge: bytes32, index: int, parallel_read: bool = True) -> bytes:
        global _hits, _misses
        key = (bytes(self.get_id()), bytes(challenge), index)
        cached = _full_proofs.get(key)
        if cached is not None:
            _hits += 1
            return cached
        result = orig_v1_proof(self, challenge, index, parallel_read)
        _full_proofs[key] = result
        _misses += 1
        return result

    V1Prover.get_qualities_for_challenge = v1_qualities  # type: ignore[method-assign]
    V2Prover.get_qualities_for_challenge = v2_qualities  # type: ignore[method-assign]
    V1Prover.get_full_proof = v1_full_proof  # type: ignore[method-assign]

    setattr(__import__("chia.simulator.block_tools", fromlist=["solve_proof"]), "solve_proof", cached_solve_proof)
    setattr(__import__("chia.solver.solver", fromlist=["solve_proof"]), "solve_proof", cached_solve_proof)

    atexit.register(_save)
