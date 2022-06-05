import importlib.resources
import json
from typing import Any, Dict

import pytest

import tests.util


@pytest.fixture
def protocol_messages() -> Dict[str, Dict[str, Any]]:
    protocol_messages = json.loads(
        importlib.resources.read_text(
            package=tests.util,
            resource="network_protocol_messages.json",
            encoding="utf-8",
        )
    )

    return protocol_messages  # type: ignore[no-any-return]
