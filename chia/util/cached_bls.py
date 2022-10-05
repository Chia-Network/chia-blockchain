from __future__ import annotations

import functools
from typing import Dict, List, Optional, Sequence

from blspy import AugSchemeMPL, G1Element, G2Element, GTElement

from chia.types.blockchain_format.sized_bytes import bytes32, bytes48
from chia.util.hash import std_hash
from chia.util.lru_cache import LRUCache


def get_pairings(
    cache: LRUCache[bytes32, GTElement], pks: List[bytes48], msgs: Sequence[bytes], force_cache: bool
) -> List[GTElement]:
    pairings: List[Optional[GTElement]] = []
    missing_count: int = 0
    for pk, msg in zip(pks, msgs):
        aug_msg: bytes = pk + msg
        h: bytes32 = std_hash(aug_msg)
        pairing: Optional[GTElement] = cache.get(h)
        if not force_cache and pairing is None:
            missing_count += 1
            # Heuristic to avoid more expensive sig validation with pairing
            # cache when it's empty and cached pairings won't be useful later
            # (e.g. while syncing)
            if missing_count > len(pks) // 2:
                return []
        pairings.append(pairing)

    # G1Element.from_bytes can be expensive due to subgroup check, so we avoid recomputing it with this cache
    pk_bytes_to_g1: Dict[bytes48, G1Element] = {}
    for i, pairing in enumerate(pairings):
        if pairing is None:
            aug_msg = pks[i] + msgs[i]
            aug_hash: G2Element = AugSchemeMPL.g2_from_message(aug_msg)

            pk_parsed: Optional[G1Element] = pk_bytes_to_g1.get(pks[i])
            if pk_parsed is None:
                # In this case, we use from_bytes instead of from_bytes_unchecked, because we will not be using
                # the bls_signatures aggregate_verify method which performs the subgroup checks
                pk_parsed = G1Element.from_bytes(pks[i])
                pk_bytes_to_g1[pks[i]] = pk_parsed

            pairing = pk_parsed.pair(aug_hash)

            h = std_hash(aug_msg)
            cache.put(h, pairing)
            pairings[i] = pairing
    return pairings


# Increasing this number will increase RAM usage, but decrease BLS validation time for blocks and unfinished blocks.
LOCAL_CACHE: LRUCache[bytes32, GTElement] = LRUCache(50000)


def aggregate_verify(
    pks: List[bytes48],
    msgs: Sequence[bytes],
    sig: G2Element,
    force_cache: bool = False,
    cache: LRUCache[bytes32, GTElement] = LOCAL_CACHE,
) -> bool:
    pairings: List[GTElement] = get_pairings(cache, pks, msgs, force_cache)
    if len(pairings) == 0:
        # Using AugSchemeMPL.aggregate_verify, so it's safe to use from_bytes_unchecked
        pks_objects: List[G1Element] = [G1Element.from_bytes_unchecked(pk) for pk in pks]
        res: bool = AugSchemeMPL.aggregate_verify(pks_objects, msgs, sig)
        return res

    pairings_prod: GTElement = functools.reduce(GTElement.__mul__, pairings)
    res = pairings_prod == sig.pair(G1Element.generator())
    return res
