from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple, Union


def validate_derivation_cache_entry(ob: List[Union[str, int, bool]]) -> Tuple[bytes, int, bool, bytes]:
    assert isinstance(ob, list), f"{ob} is not a list"
    assert len(ob) == 4, f"{ob} should have 4 entries"
    parent_key: str
    index: int
    hardened: bool
    child_key: str
    parent_key, index, hardened, child_key = ob
    assert isinstance(index, int), f"Index ({index}) should be an integer"
    assert index >= 0, f"Index ({index}) should be >= 0"
    assert isinstance(hardened, bool), f"Third entry ({hardened}) should be bool"
    assert len(parent_key) == 64, f"{parent_key} should be 64 characters long"
    assert len(child_key) == 64, f"{child_key} should be 64 characters long"
    # Invalid hex values will be caught here
    return bytes.fromhex(parent_key), index, hardened, bytes.fromhex(child_key)


def load_derivation_cache(path: Path) -> Dict[Tuple[bytes, int, bool], bytes]:
    derivation_cache: Dict[Tuple[bytes, int, bool], bytes] = {}
    try:
        with path.open(encoding="UTF-8") as cache_file:
            objects = json.load(cache_file)
            for ob in objects:
                parent_key, index, hardened, child_key = validate_derivation_cache_entry(ob)
                k = (parent_key, index, hardened)
                if k in derivation_cache and derivation_cache[k] != child_key:
                    raise RuntimeError(f"Conflicting entries found for {(parent_key.hex(), index, hardened)}")
                derivation_cache[k] = child_key
    except Exception as e:
        print(f"Unable to load derivation cache '{path}' used for test speedup: {e}")
    return derivation_cache
