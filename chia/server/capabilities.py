from __future__ import annotations

from typing import Iterable, List, Set, Tuple

from chia.protocols.shared_protocol import Capability
from chia.util.ints import uint16


def known_active_capabilities(values: Iterable[Tuple[uint16, str]]) -> List[Capability]:
    # NOTE: order is not guaranteed
    # TODO: what if there's a claim for both supporting and not?
    #       presently it considers it supported
    filtered: Set[Capability] = set()
    for value, state in values:
        if state != "1":
            continue

        try:
            filtered.add(Capability(value))
        except ValueError:
            pass

    # TODO: consider changing all uses to sets instead of lists
    return list(filtered)
