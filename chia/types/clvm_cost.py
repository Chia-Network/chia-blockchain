from __future__ import annotations

from typing import NewType

from chia.util.ints import uint64

"""
CLVM Cost is the cost to run a CLVM program on the CLVM.
It is similar to transaction bytes in the Bitcoin, but some operations
are charged a higher rate, depending on their arguments.
"""

CLVMCost = NewType("CLVMCost", uint64)
