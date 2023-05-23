from __future__ import annotations

from typing import Iterable, List, Set, Tuple

from chia.protocols.shared_protocol import Capability
from chia.util.ints import uint16

_capability_values = {int(capability) for capability in Capability}


def known_active_capabilities(values: Iterable[Tuple[uint16, str]]) -> List[Capability]:
    # NOTE: order is not guaranteed
    # TODO: what if there's a claim for both supporting and not?
    #       presently it considers it supported
    filtered: Set[uint16] = set()
    for value, state in values:
        if state != "1":
            continue

        if value not in _capability_values:
            continue

        filtered.add(value)

    # TODO: consider changing all uses to sets instead of lists
    return [Capability(value) for value in filtered]
