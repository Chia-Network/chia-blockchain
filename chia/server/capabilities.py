from __future__ import annotations

from typing import List, Set, Tuple
from collections.abc import Iterable

from chia.protocols.shared_protocol import Capability
from chia.util.ints import uint16


def known_active_capabilities(values: Iterable[tuple[uint16, str]]) -> list[Capability]:
    # NOTE: order is not guaranteed
    # TODO: what if there's a claim for both supporting and not?
    #       presently it considers it supported
    filtered: set[Capability] = set()
    for value, state in values:
        if state != "1":
            continue

        try:
            filtered.add(Capability(value))
        except ValueError:
            pass

    # TODO: consider changing all uses to sets instead of lists
    return list(filtered)
