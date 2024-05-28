from __future__ import annotations

import functools
from typing import List, Optional, Sequence

from chia_rs import AugSchemeMPL, G1Element, G2Element, GTElement

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.lru_cache import LRUCache


def get_pairings(
    cache: LRUCache[bytes32, GTElement], pks: List[G1Element], msgs: Sequence[bytes], force_cache: bool
) -> List[GTElement]:
    pairings: List[Optional[GTElement]] = []
    missing_count: int = 0
    for pk, msg in zip(pks, msgs):
        aug_msg: bytes = bytes(pk) + msg
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

    ret: List[GTElement] = []
    for i, pairing in enumerate(pairings):
        if pairing is None:
            aug_msg = bytes(pks[i]) + msgs[i]
            aug_hash: G2Element = AugSchemeMPL.g2_from_message(aug_msg)
            pairing = aug_hash.pair(pks[i])
            h = std_hash(aug_msg)
            cache.put(h, pairing)
            ret.append(pairing)
        else:
            ret.append(pairing)
    return ret


# Increasing this number will increase RAM usage, but decrease BLS validation time for blocks and unfinished blocks.
LOCAL_CACHE: LRUCache[bytes32, GTElement] = LRUCache(50000)


def aggregate_verify(
    pks: List[G1Element],
    msgs: Sequence[bytes],
    sig: G2Element,
    force_cache: bool = False,
    cache: LRUCache[bytes32, GTElement] = LOCAL_CACHE,
) -> bool:
    pairings: List[GTElement] = get_pairings(cache, pks, msgs, force_cache)
    if len(pairings) == 0:
        # Using AugSchemeMPL.aggregate_verify, so it's safe to use from_bytes_unchecked
        return AugSchemeMPL.aggregate_verify(pks, msgs, sig)

    pairings_prod: GTElement = functools.reduce(GTElement.__mul__, pairings)
    res = pairings_prod == sig.pair(G1Element.generator())
    return res
