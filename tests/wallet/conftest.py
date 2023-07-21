from __future__ import annotations

import asyncio
from typing import Generator

import pytest


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    # This fixture allows us to use an event loop for async tests
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()
