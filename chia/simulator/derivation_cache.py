from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from chia_rs import PrivateKey


@dataclass(frozen=True)
class DerivationCacheKey:
    private_key: PrivateKey
    index: int
    hardened: bool


"""
Cache derivations during testing. This reduces the time spent in bls, and saves us about 12% of our time in pytest.
Do not use this cache in production. BlockTools should only be used for testing.
"""
DerivationCache = Dict[DerivationCacheKey, PrivateKey]


def load_derivation_cache(path: Path) -> DerivationCache:
    try:
        with path.open("wb") as f:
            return DerivationCache(pickle.load(f))
    except Exception as e:
        # Eat the exception so that tests can continue even on a failed cache load
        print(f"Unable to load derivation cache '{path}' used for test speedup: {e}")
        empty: DerivationCache = {}
        return empty


def save_derivation_cache(cache: DerivationCache, path: Path) -> None:
    with path.open("wb") as f:
        pickle.dump(cache, f)
