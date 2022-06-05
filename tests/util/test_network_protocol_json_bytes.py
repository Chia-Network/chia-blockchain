import json
from typing import Any, Dict, Tuple

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest

from chia.util.streamable import Streamable
from tests.util.build_network_protocol_files import get_network_protocol_filename
from tests.util.network_protocol_data2 import name_to_instance


# TODO: CAMPid 09431708598989839831480984342780971034
@pytest.fixture(
    name="name_and_instance",
    params=[(name, instance) for name, instance in name_to_instance.items()],
    ids=list(name_to_instance.keys()),
)
def name_and_instance_fixture(request: SubRequest) -> Tuple[str, Streamable]:
    return request.param  # type: ignore[no-any-return]


@pytest.fixture(name="name")
def name_fixture(name_and_instance: Tuple[str, Streamable]) -> str:
    name, instance = name_and_instance
    return name  # type: ignore[no-any-return]


@pytest.fixture(name="instance")
def instance_fixture(name_and_instance: Tuple[str, Streamable]) -> Streamable:
    name, instance = name_and_instance
    return instance  # type: ignore[no-any-return]


@pytest.fixture(name="input_bytes")
def input_bytes_fixture() -> Dict[str, Any]:
    input_bytes_hex = json.loads(get_network_protocol_filename().read_text())
    input_bytes = {key: bytes.fromhex(value) for key, value in input_bytes_hex.items()}
    return input_bytes


def test_protocol_json_to_dict_str_matches(
    protocol_messages: Dict[str, Dict[str, Any]],
    name: str,
    instance: Streamable,
) -> None:
    assert str(protocol_messages[name]) == str(instance.to_json_dict())


def test_protocol_json_from_json_instance_matches(
    protocol_messages: Dict[str, Dict[str, Any]],
    name: str,
    instance: Streamable,
) -> None:
    assert type(instance).from_json_dict(protocol_messages[name]) == instance


def test_protocol_from_bytes_matches_instance(name: str, instance: Streamable, input_bytes: Dict[str, bytes]) -> None:
    message_bytes = input_bytes[name]
    message = type(instance).from_bytes(message_bytes)
    assert message == instance


def test_protocol_to_bytes_matches(name: str, instance: Streamable, input_bytes: Dict[str, bytes]) -> None:
    message_bytes = input_bytes[name]
    message = type(instance).from_bytes(message_bytes)
    assert bytes(message) == bytes(instance)
    # TODO: what about assert message_bytes == bytes(instance)?
