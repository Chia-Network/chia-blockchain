from __future__ import annotations

from typing import List


def clamp(n: int, smallest: int, largest: int) -> int:
    return max(smallest, min(n, largest))


def make_monotonically_decreasing(seq: List[float]) -> List[float]:
    out: List[float] = []
    if len(seq) > 0:
        min = seq[0]
        for n in seq:
            if n <= min:
                out.append(n)
                min = n
            else:
                out.append(min)
    return out
