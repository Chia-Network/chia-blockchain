from __future__ import annotations

import pytest

from chia.util.setproctitle import setproctitle

pytestmark = pytest.mark.skip(
    reason="this test ends up hanging frequently and needs to be rewritten with a subprocess and a title check",
)


def test_does_not_crash() -> None:
    setproctitle("chia test title")
