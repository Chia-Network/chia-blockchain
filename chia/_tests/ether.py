from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from chia._tests.util.misc import TestId

# NOTE: Do not just put any useful thing here.  This is specifically for making
#       fixture values globally available during tests.  In _most_ cases fixtures
#       should be directly requested using normal mechanisms.  Very little should
#       be put here.

# NOTE: When using this module do not import the attributes directly.  Rather, import
#       something like `from chia._tests import ether`.  Importing attributes directly will
#       result in you likely getting the default `None` values since they are not
#       populated until tests are running.

record_property: Optional[Callable[[str, object], None]] = None
test_id: Optional[TestId] = None
