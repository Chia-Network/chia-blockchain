from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from tests.util.misc import TestId

# NOTE: When using this module do not import the attributes directly, rather import
#       something like `from tests import ether`.  Importing attributes direclty will
#       result in you likely getting the default `None` values since they are not
#       populated until tests are running.

# TODO: should we enforce checking every use for not None?
project_root: Path = None  # type: ignore[assignment]
record_property: Callable[[str, object], None] = None  # type: ignore[assignment]
test_id: TestId = None  # type: ignore[assignment]
