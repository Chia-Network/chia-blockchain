from __future__ import annotations

from typing import List, Tuple

import pytest

from chia.protocols.shared_protocol import Capability
from chia.server.capabilities import known_active_capabilities
from chia.util.ints import uint16


@pytest.mark.parametrize(
    argnames=["values", "expected"],
    argvalues=[
        # nothing, not even Chia mainnet...
        [[], []],
        # single valid
        [[(uint16(Capability.BASE), "1")], [Capability.BASE]],
        # all capabilities
        [[(uint16(capability), "1") for capability in Capability], list(Capability)],
        # all capabilities plus some invalid
        [
            [
                *[(uint16(capability), "1") for capability in Capability],
                *[(uint16(max(Capability) + n), "1") for n in range(1, 10)],
            ],
            list(Capability),
        ],
        # all possible values
        [
            [(uint16(n), "1") for n in range(2**16)],
            list(Capability),
        ],
        # all possible invalid values
        [
            [(uint16(n), "1") for n in set(range(2**16)) - set(Capability)],
            [],
        ],
        # single invalid
        [[(uint16(max(Capability) + 1), "1")], []],
        # a few invalid
        [[(uint16(max(Capability) + n), "1") for n in range(1, 10)], []],
    ],
)
@pytest.mark.parametrize(
    argnames="duplicated",
    argvalues=[False, True],
    ids=lambda value: "duplicated" if value else "as-is",
)
@pytest.mark.parametrize(
    argnames="disabled",
    argvalues=[False, True],
    ids=lambda value: "disabled" if value else "enabled",
)
def test_known_active_capabilities_filter(
    values: List[Tuple[uint16, str]],
    expected: List[Capability],
    duplicated: bool,
    disabled: bool,
) -> None:
    if duplicated:
        values = values * 2

    if disabled:
        values = [(value, "0") for value, state in values]
        expected = []

    assert known_active_capabilities(values=values) == expected
