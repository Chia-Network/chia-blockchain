"""
In-process (and optional on-disk) cache for BLS HD child derivations in pytest.

Do not use this in production. Call install() from a session autouse fixture to
monkeypatch AugSchemeMPL.derive_child_sk / derive_child_sk_unhardened /
derive_child_pk_unhardened.

Disable with CHIA_TEST_DERIVATION_CACHE=0 (instrumentation still records time).
The pickle is local (next to test-plots) and is not checked in.
"""

from __future__ import annotations

import atexit
import logging
import os
import pickle  # ruff: ignore[suspicious-pickle-import]
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final, TypeVar

from chia_rs import AugSchemeMPL, G1Element, PrivateKey
from filelock import FileLock

log = logging.getLogger(__name__)

CACHE_FILENAME: Final = "derivation_cache.pickle"
CACHE_VERSION: Final = 1
ENV_VAR: Final = "CHIA_TEST_DERIVATION_CACHE"

_KIND_SK: Final = b"sk"
_KIND_SK_UNHARDENED: Final = b"sku"
_KIND_PK_UNHARDENED: Final = b"pku"

CacheKey = tuple[bytes, bytes, int]
_cache: dict[CacheKey, bytes] = {}

_orig_derive_child_sk = AugSchemeMPL.derive_child_sk
_orig_derive_child_sk_unhardened = AugSchemeMPL.derive_child_sk_unhardened
_orig_derive_child_pk_unhardened = AugSchemeMPL.derive_child_pk_unhardened

_installed: bool = False
_enabled: bool = True
_cache_path: Path | None = None
_hits: int = 0
_misses: int = 0
_miss_ns: int = 0

T = TypeVar("T", PrivateKey, G1Element)


def _env_enabled() -> bool:
    val = os.environ.get(ENV_VAR, "1").strip().lower()
    return val not in {"0", "false", "no", "off"}


def _load_from_disk(path: Path) -> dict[CacheKey, bytes]:
    if not path.exists():
        return {}
    try:
        data = pickle.loads(path.read_bytes())  # ruff: ignore[suspicious-pickle-usage]
        if isinstance(data, tuple) and len(data) == 2 and data[0] == CACHE_VERSION and isinstance(data[1], dict):
            return data[1]
    except Exception:
        log.exception("derivation_cache: failed to read existing cache for merge")
    return {}


def stats() -> dict[str, int | bool | str]:
    total = _hits + _misses
    return {
        "enabled": _enabled,
        "hits": _hits,
        "misses": _misses,
        "entries": len(_cache),
        "miss_ns": _miss_ns,
        "hit_rate": f"{_hits * 100 / total:.1f}%" if total > 0 else "n/a",
    }


def _format_summary() -> str:
    s = stats()
    miss_s = _miss_ns / 1e9
    return (
        f"derivation_cache: enabled={s['enabled']} hits={s['hits']} misses={s['misses']} "
        f"hit_rate={s['hit_rate']} miss_time={miss_s:.3f}s entries={s['entries']}"
    )


def _save() -> None:
    if _misses > 0 and _enabled and _cache_path is not None:
        try:
            with FileLock(str(_cache_path) + ".lock"):
                disk = _load_from_disk(_cache_path)
                disk.update(_cache)
                _cache_path.write_bytes(pickle.dumps((CACHE_VERSION, disk), protocol=pickle.HIGHEST_PROTOCOL))
                print(f"derivation_cache: saved {len(disk)} entries to {_cache_path}")
        except Exception:
            log.exception("derivation_cache: failed to save")
    if _hits + _misses > 0:
        print(_format_summary())


def load(cache_dir: Path) -> None:
    global _cache_path
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_path = cache_dir / CACHE_FILENAME
    if not _enabled:
        return
    try:
        with FileLock(str(_cache_path) + ".lock"):
            disk = _load_from_disk(_cache_path)
    except Exception:
        log.exception("derivation_cache: failed to acquire lock for loading")
        return
    _cache.update(disk)
    if disk:
        print(f"derivation_cache: loaded {len(disk)} entries from {_cache_path}")


def _cached(
    kind: bytes,
    orig: Callable[[T, int], T],
    from_bytes: Callable[[bytes], T],
    parent: T,
    index: int,
) -> T:
    global _hits, _misses, _miss_ns
    if not _enabled:
        t0 = time.perf_counter_ns()
        result = orig(parent, index)
        _miss_ns += time.perf_counter_ns() - t0
        _misses += 1
        return result

    key: CacheKey = (kind, bytes(parent), index)
    cached = _cache.get(key)
    if cached is not None:
        _hits += 1
        return from_bytes(cached)

    t0 = time.perf_counter_ns()
    result = orig(parent, index)
    _miss_ns += time.perf_counter_ns() - t0
    _cache[key] = bytes(result)
    _misses += 1
    return result


def cached_derive_child_sk(parent: PrivateKey, index: int) -> PrivateKey:
    return _cached(_KIND_SK, _orig_derive_child_sk, PrivateKey.from_bytes, parent, index)


def cached_derive_child_sk_unhardened(parent: PrivateKey, index: int) -> PrivateKey:
    return _cached(_KIND_SK_UNHARDENED, _orig_derive_child_sk_unhardened, PrivateKey.from_bytes, parent, index)


def cached_derive_child_pk_unhardened(parent: G1Element, index: int) -> G1Element:
    return _cached(_KIND_PK_UNHARDENED, _orig_derive_child_pk_unhardened, G1Element.from_bytes, parent, index)


def install(cache_dir: Path) -> None:
    global _installed, _enabled
    if _installed:
        return
    _installed = True
    _enabled = _env_enabled()
    load(cache_dir)

    AugSchemeMPL.derive_child_sk = staticmethod(cached_derive_child_sk)  # type: ignore[method-assign, assignment]
    AugSchemeMPL.derive_child_sk_unhardened = staticmethod(cached_derive_child_sk_unhardened)  # type: ignore[method-assign, assignment]
    AugSchemeMPL.derive_child_pk_unhardened = staticmethod(cached_derive_child_pk_unhardened)  # type: ignore[method-assign, assignment]

    atexit.register(_save)
