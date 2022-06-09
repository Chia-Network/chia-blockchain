import importlib.resources
import json
import types
from typing import Any, Dict, List, Tuple

import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.fixtures import SubRequest

import tests.util

# farmer_protocol,; full_node_protocol,; harvester_protocol,; introducer_protocol,; timelord_protocol,; wallet_protocol,
from chia.protocols import pool_protocol, shared_protocol
from chia.protocols.all_protocols import all_protocols
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.util.streamable import Streamable
from tests.util.build_network_protocol_files import SerializedProtocolData, get_network_protocol_filename
from tests.util.network_protocol_data import InstanceProtocolData, module_to_name_to_instance


@pytest.fixture(
    name="name_and_instance",
    params=[
        (name, instance)
        for module, name_to_instance in module_to_name_to_instance.items()
        for name, instance in name_to_instance.items()
    ],
    ids=lambda param: param[0],  # type: ignore[no-any-return]
)
def name_and_instance_fixture(request: SubRequest) -> Tuple[str, Streamable]:
    return request.param  # type: ignore[no-any-return]


@pytest.fixture(name="name")
def name_fixture(name_and_instance: Tuple[str, Streamable]) -> str:
    name, instance = name_and_instance
    return name


@pytest.fixture(name="instance")
def instance_fixture(name_and_instance: Tuple[str, Streamable]) -> Streamable:
    name, instance = name_and_instance
    return instance


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


def test_protocol_from_bytes_matches_instance(
    name: str, instance: Streamable, protocol_messages_bytes: Dict[str, bytes]
) -> None:
    message_bytes = protocol_messages_bytes[name]
    message = type(instance).from_bytes(message_bytes)
    assert message == instance


def test_protocol_to_bytes_matches(name: str, instance: Streamable, protocol_messages_bytes: Dict[str, bytes]) -> None:
    message_bytes = protocol_messages_bytes[name]
    assert message_bytes == bytes(instance)


ModuleProtocolData = List[types.ModuleType]


@pytest.fixture(name="all_protocol_modules")
def all_protocol_modules_fixture() -> ModuleProtocolData:
    # TODO: handle these instead of ignoring
    exclusions = {pool_protocol, shared_protocol}

    filtered_protocols = [module for module in all_protocols if module not in exclusions]

    return filtered_protocols


@pytest.fixture(name="all_protocol_instances")
def all_protocol_instances_fixture() -> InstanceProtocolData:
    return module_to_name_to_instance


@pytest.fixture(name="all_protocol_serializations")
def all_protocol_serializations_fixture() -> SerializedProtocolData:
    return json.loads(  # type: ignore[no-any-return]
        importlib.resources.read_text(
            package=tests.util,
            resource=get_network_protocol_filename().name,
            encoding="utf-8",
        )
    )


# TODO: this doesn't check the contents are proper, just the group names
def test_instances_match_module_names(
    all_protocol_modules: ModuleProtocolData,
    all_protocol_instances: InstanceProtocolData,
) -> None:
    module_names = sorted(module.__name__.rpartition(".")[2] for module in all_protocol_modules)
    instance_group_names = sorted(all_protocol_instances.keys())

    assert module_names == instance_group_names


# TODO: this doesn't check the contents are proper, just the group names
def test_serializations_match_module_names(
    all_protocol_modules: ModuleProtocolData,
    all_protocol_serializations: SerializedProtocolData,
) -> None:
    module_names = sorted(module.__name__.rpartition(".")[2] for module in all_protocol_modules)
    serializations_group_names = sorted(all_protocol_serializations.keys())

    assert module_names == serializations_group_names


# TODO: deal with todos inside and remove the xfail
@pytest.mark.xfail(strict=True)
def test_all_sources_match_message_names(
    all_protocol_modules: ModuleProtocolData,
    all_protocol_instances: InstanceProtocolData,
    all_protocol_serializations: SerializedProtocolData,
) -> None:
    module_names = {
        module.__name__.rpartition(".")[2]: {
            cls.__name__
            for cls in vars(module).values()
            if (isinstance(cls, type) and issubclass(cls, Streamable) and cls is not Streamable)
        }
        for module in all_protocol_modules
    }
    # TODO: handle shared_protocol instead of ignoring it
    del module_names["shared_protocol"]
    instance_names = {
        group: {*names_to_instances.keys()} for group, names_to_instances in all_protocol_instances.items()
    }
    serializations_names = {
        group: {*names_to_instances.keys()} for group, names_to_instances in all_protocol_serializations.items()
    }

    # TODO: deal with CamelCase from module names and snake_case for others
    assert module_names == instance_names == serializations_names


# TODO: provide testing of state machine messages
# https://github.com/Chia-Network/chia-blockchain/blob/8665e21fd71a4d0a15fae2f9f9c94f395597bc64/tests/util/test_network_protocol_test.py#L29-L40


@pytest.fixture(name="all_protocol_message_enumerators")
def all_protocol_message_enumerators_fixture() -> List[ProtocolMessageTypes]:
    # TODO: review and presumably handle exclusions
    exclusions = {
        ProtocolMessageTypes.farm_new_block,
        ProtocolMessageTypes.handshake,
        ProtocolMessageTypes.plot_sync_start,
        ProtocolMessageTypes.plot_sync_loaded,
        ProtocolMessageTypes.plot_sync_removed,
        ProtocolMessageTypes.plot_sync_invalid,
        ProtocolMessageTypes.plot_sync_keys_missing,
        ProtocolMessageTypes.plot_sync_duplicates,
        ProtocolMessageTypes.plot_sync_done,
        ProtocolMessageTypes.plot_sync_response,
    }

    return [type for type in ProtocolMessageTypes if type not in exclusions]


def test_message_types_match_instances(
    all_protocol_instances: SerializedProtocolData,
    all_protocol_message_enumerators: List[ProtocolMessageTypes],
) -> None:
    serialization_message_names = sorted(
        name for group_name, name_to_instance in all_protocol_instances.items() for name in name_to_instance.keys()
    )

    assert serialization_message_names == sorted(enumerator.name for enumerator in all_protocol_message_enumerators)


def test_message_types_match_serializations(
    all_protocol_serializations: SerializedProtocolData,
    all_protocol_message_enumerators: List[ProtocolMessageTypes],
) -> None:
    serialization_message_names = sorted(
        name
        for group_name, name_to_serialization in all_protocol_serializations.items()
        for name in name_to_serialization.keys()
    )

    assert serialization_message_names == sorted(enumerator.name for enumerator in all_protocol_message_enumerators)
