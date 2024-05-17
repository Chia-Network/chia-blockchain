from __future__ import annotations

import functools
from typing import List, Optional, Sequence, Tuple

from chia_rs import AugSchemeMPL, G1Element, G2Element, GTElement

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.lru_cache import LRUCache


class BLSCache:
    cache: LRUCache[bytes32, GTElement]

    def __init__(self, size: int = 50000):
        self.cache = LRUCache(size)

    def get_pairings(self, pks: List[G1Element], msgs: Sequence[bytes], force_cache: bool) -> List[GTElement]:
        pairings: List[Optional[GTElement]] = []
        missing_count: int = 0
        for pk, msg in zip(pks, msgs):
            aug_msg: bytes = bytes(pk) + msg
            h: bytes32 = std_hash(aug_msg)
            pairing: Optional[GTElement] = self.cache.get(h)
            if not force_cache and pairing is None:
                missing_count += 1
                # Heuristic to avoid more expensive sig validation with pairing
                # cache when it's empty and cached pairings won't be useful later
                # (e.g. while syncing)
                if missing_count > len(pks) // 2:
                    return []
            pairings.append(pairing)

        # G1Element.from_bytes can be expensive due to subgroup check, so we avoid recomputing it with this cache
        ret: List[GTElement] = []
        for i, pairing in enumerate(pairings):
            if pairing is None:
                aug_msg = bytes(pks[i]) + msgs[i]
                aug_hash: G2Element = AugSchemeMPL.g2_from_message(aug_msg)
                pairing = aug_hash.pair(pks[i])

                h = std_hash(aug_msg)
                self.cache.put(h, pairing)
                ret.append(pairing)
            else:
                ret.append(pairing)
        return ret

    def aggregate_verify(
        self,
        pks: List[G1Element],
        msgs: Sequence[bytes],
        sig: G2Element,
        force_cache: bool = False,
    ) -> bool:
        pairings: List[GTElement] = self.get_pairings(pks, msgs, force_cache)
        if len(pairings) == 0:
            res: bool = AugSchemeMPL.aggregate_verify(pks, msgs, sig)
            return res

        pairings_prod: GTElement = functools.reduce(GTElement.__mul__, pairings)
        res = pairings_prod == sig.pair(G1Element.generator())
        return res

    def update(self, other: List[Tuple[bytes32, bytes]]) -> None:
        for key, value in other:
            self.cache.put(key, GTElement.from_bytes_unchecked(value))

    def items(self) -> List[Tuple[bytes32, bytes]]:
        return [(key, value.to_bytes()) for key, value in self.cache.cache.items()]


# Increasing this number will increase RAM usage, but decrease BLS validation time for blocks and unfinished blocks.
LOCAL_CACHE = BLSCache(50000)
