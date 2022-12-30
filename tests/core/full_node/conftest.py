from __future__ import annotations

import asyncio
from typing import Iterator

import pytest


# This is an optimization to reduce runtime by reducing setup and teardown on the
# wallet nodes fixture below.
# https://github.com/pytest-dev/pytest-asyncio/blob/v0.18.1/pytest_asyncio/plugin.py#L479-L484
@pytest.fixture(scope="module")
def event_loop(request: "pytest.FixtureRequest") -> Iterator[asyncio.AbstractEventLoop]:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
