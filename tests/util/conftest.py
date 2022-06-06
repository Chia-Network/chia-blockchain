import importlib.resources
import json
from typing import Any, Dict

import pytest
from typing_extensions import TypedDict

import tests.util
from tests.util.build_network_protocol_files import get_network_protocol_filename


class MessageDict(TypedDict):
    bytes: str
    json: Dict[str, Any]


AllOfIt = Dict[str, MessageDict]


@pytest.fixture
def protocol_messages_both() -> AllOfIt:
    protocol_messages = json.loads(
        importlib.resources.read_text(
            package=tests.util,
            resource=get_network_protocol_filename().name,
            encoding="utf-8",
        )
    )

    return {name: data for module, message in protocol_messages.items() for name, data in message.items()}


@pytest.fixture
def protocol_messages(protocol_messages_both: AllOfIt) -> Dict[str, Dict[str, Any]]:
    return {name: data["json"] for name, data in protocol_messages_both.items()}


@pytest.fixture
def protocol_messages_bytes(protocol_messages_both: AllOfIt) -> Dict[str, bytes]:
    return {name: bytes.fromhex(data["bytes"]) for name, data in protocol_messages_both.items()}
