import logging
import time
from typing import Any, Callable, List

import pytest
from blspy import G1Element
from Crypto.Random import get_random_bytes

from chia.plot_sync.receiver import Receiver
from chia.plot_sync.util import ErrorCodes, State
from chia.protocols.harvester_protocol import (
    PlotSyncDone,
    PlotSyncIdentifier,
    PlotSyncPathList,
    Plot,
    PlotSyncPlotList,
    PlotSyncResponse,
    PlotSyncStart,
)
from chia.server.ws_connection import NodeType
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64
from tests.plot_sync.util import get_dummy_connection

log = logging.getLogger(__name__)

next_message_id = uint64(0)


def assert_default_values(receiver: Receiver) -> None:
    assert receiver.state() == State.idle
    assert receiver.expected_sync_id() == 0
    assert receiver.expected_message_id() == 0
    assert receiver.last_sync_id() == 0
    assert receiver.last_sync_time() == 0
    assert receiver.plots() == {}
    assert receiver.invalid() == []
    assert receiver.keys_missing() == []
    assert receiver.duplicates() == []


async def dummy_callback(_, __) -> None:
    pass


class SyncStepData:
    state: State
    function: Any
    payload_type: Any
    args: Any

    def __init__(self, state: State, function: Callable, payload_type: Callable, *args) -> None:
        self.state = state
        self.function = function
        self.payload_type = payload_type
        self.args = args


def plot_sync_identifier(current_sync_id: uint64, message_id: uint64) -> PlotSyncIdentifier:
    return PlotSyncIdentifier(uint64(0), current_sync_id, message_id)


def create_payload(payload_type: Any, start: bool, *args) -> Any:
    global next_message_id
    if start:
        next_message_id = uint64(0)
    next_identifier = plot_sync_identifier(uint64(1), next_message_id)
    next_message_id = uint64(next_message_id + 1)
    return payload_type(next_identifier, *args)


def assert_error_response(plot_sync: Receiver, error_code: ErrorCodes) -> None:
    connection = plot_sync.connection()
    assert connection is not None
    message = connection.last_sent_message
    assert message is not None
    response: PlotSyncResponse = PlotSyncResponse.from_bytes(message.data)
    assert response.error is not None
    assert response.error.code == error_code


def pre_function_validate(receiver: Receiver, data, expected_state: State) -> None:
    if expected_state == State.loaded:
        for plot_info in data:
            assert plot_info.filename not in receiver.plots()
    elif expected_state == State.removed:
        for path in data:
            assert path in receiver.plots()
    elif expected_state == State.invalid:
        for path in data:
            assert path not in receiver.invalid()
    elif expected_state == State.keys_missing:
        for path in data:
            assert path not in receiver.keys_missing()
    elif expected_state == State.duplicates:
        for path in data:
            assert path not in receiver.duplicates()


def post_function_validate(receiver: Receiver, data, expected_state: State) -> None:
    if expected_state == State.loaded:
        for plot_info in data:
            assert plot_info.filename in receiver._delta.valid.additions
    elif expected_state == State.removed:
        for path in data:
            assert path in receiver._delta.valid.removals
    elif expected_state == State.invalid:
        for path in data:
            assert path in receiver._delta.invalid.additions
    elif expected_state == State.keys_missing:
        for path in data:
            assert path in receiver._delta.keys_missing.additions
    elif expected_state == State.duplicates:
        for path in data:
            assert path in receiver._delta.duplicates.additions


@pytest.mark.asyncio
async def run_sync_step(receiver: Receiver, sync_step: SyncStepData, expected_state: State) -> None:
    assert receiver.state() == expected_state
    last_sync_time_before = receiver._last_sync_time
    # For the the list types invoke the trigger function in batches
    if sync_step.payload_type == PlotSyncPlotList or sync_step.payload_type == PlotSyncPathList:
        step_data, _ = sync_step.args
        assert len(step_data) == 10
        # Invoke batches of: 1, 2, 3, 4 items and validate the data against plot store before and after
        indexes = [0, 1, 3, 6, 10]
        for i in range(0, len(indexes) - 1):
            invoke_data = step_data[indexes[i] : indexes[i + 1]]
            pre_function_validate(receiver, invoke_data, expected_state)
            await sync_step.function(
                create_payload(sync_step.payload_type, False, invoke_data, i == (len(indexes) - 2))
            )
            post_function_validate(receiver, invoke_data, expected_state)
    else:
        # For Start/Done just invoke it..
        await sync_step.function(create_payload(sync_step.payload_type, sync_step.state == State.idle, *sync_step.args))
    # Make sure we moved to the next state
    assert receiver.state() != expected_state
    if sync_step.payload_type == PlotSyncDone:
        assert receiver._last_sync_time != last_sync_time_before
    else:
        assert receiver._last_sync_time == last_sync_time_before


def plot_sync_setup():
    harvester_connection = get_dummy_connection(NodeType.HARVESTER)
    receiver = Receiver(harvester_connection, dummy_callback)

    # Create example plot data
    path_list = [str(x) for x in range(0, 40)]
    plot_info_list = [
        Plot(
            filename=str(x),
            size=uint8(0),
            plot_id=bytes32(get_random_bytes(32)),
            pool_contract_puzzle_hash=None,
            pool_public_key=None,
            plot_public_key=G1Element(),
            file_size=uint64(0),
            time_modified=uint64(0),
        )
        for x in path_list
    ]

    # Manually add the plots we want to remove in tests
    receiver._plots = {plot_info.filename: plot_info for plot_info in plot_info_list[0:10]}

    sync_steps: List[SyncStepData] = [
        SyncStepData(State.idle, receiver.sync_started, PlotSyncStart, False, uint64(0), uint32(len(plot_info_list))),
        SyncStepData(State.loaded, receiver.process_loaded, PlotSyncPlotList, plot_info_list[10:20], True),
        SyncStepData(State.removed, receiver.process_removed, PlotSyncPathList, path_list[0:10], True),
        SyncStepData(State.invalid, receiver.process_invalid, PlotSyncPathList, path_list[20:30], True),
        SyncStepData(State.keys_missing, receiver.process_keys_missing, PlotSyncPathList, path_list[30:40], True),
        SyncStepData(State.duplicates, receiver.process_duplicates, PlotSyncPathList, path_list[10:20], True),
        SyncStepData(State.done, receiver.sync_done, PlotSyncDone, uint64(0)),
    ]

    return receiver, sync_steps


def test_default_values() -> None:
    assert_default_values(Receiver(get_dummy_connection(NodeType.HARVESTER), dummy_callback))


@pytest.mark.asyncio
async def test_reset() -> None:
    receiver, sync_steps = plot_sync_setup()
    connection_before = receiver.connection()
    # Assign some dummy values
    receiver._sync_state = State.done
    receiver._expected_sync_id = uint64(1)
    receiver._expected_message_id = uint64(1)
    receiver._last_sync_id = uint64(1)
    receiver._last_sync_time = time.time()
    receiver._invalid = ["1"]
    receiver._keys_missing = ["1"]
    receiver._delta.valid.additions = receiver.plots().copy()
    receiver._delta.valid.removals = ["1"]
    receiver._delta.invalid.additions = ["1"]
    receiver._delta.invalid.removals = ["1"]
    receiver._delta.keys_missing.additions = ["1"]
    receiver._delta.keys_missing.removals = ["1"]
    # Call `reset` and make sure all expected values are set back to their defaults.
    receiver.reset()
    assert_default_values(receiver)
    assert receiver._delta.valid.additions == {}
    assert receiver._delta.valid.removals == []
    assert receiver._delta.invalid.additions == []
    assert receiver._delta.invalid.removals == []
    assert receiver._delta.keys_missing.additions == []
    assert receiver._delta.keys_missing.removals == []
    # Connection should remain
    assert receiver.connection() == connection_before


@pytest.mark.asyncio
async def test_to_dict() -> None:
    receiver, sync_steps = plot_sync_setup()
    plot_sync_dict_1 = receiver.to_dict()
    assert "plots" in plot_sync_dict_1 and len(plot_sync_dict_1["plots"]) == 10
    assert "failed_to_open_filenames" in plot_sync_dict_1 and len(plot_sync_dict_1["failed_to_open_filenames"]) == 0
    assert "no_key_filenames" in plot_sync_dict_1 and len(plot_sync_dict_1["no_key_filenames"]) == 0
    assert "last_sync_time" not in plot_sync_dict_1
    assert plot_sync_dict_1["connection"]["node_id"] == receiver.connection().peer_node_id
    assert plot_sync_dict_1["connection"]["host"] == receiver.connection().peer_host
    assert plot_sync_dict_1["connection"]["port"] == receiver.connection().peer_port

    # We should get equal dicts
    plot_sync_dict_2 = receiver.to_dict()
    assert plot_sync_dict_1 == plot_sync_dict_2

    dict_2_paths = [x.filename for x in plot_sync_dict_2["plots"]]
    for plot_info in sync_steps[State.loaded].args[0]:
        assert plot_info.filename not in dict_2_paths

    # Walk through all states from idle to done and run them with the test data
    for state in State:
        await run_sync_step(receiver, sync_steps[state], state)

    plot_sync_dict_3 = receiver.to_dict()
    dict_3_paths = [x.filename for x in plot_sync_dict_3["plots"]]
    for plot_info in sync_steps[State.loaded].args[0]:
        assert plot_info.filename in dict_3_paths

    for path in sync_steps[State.removed].args[0]:
        assert path not in plot_sync_dict_3["plots"]

    for path in sync_steps[State.invalid].args[0]:
        assert path in plot_sync_dict_3["failed_to_open_filenames"]

    for path in sync_steps[State.keys_missing].args[0]:
        assert path in plot_sync_dict_3["no_key_filenames"]

    assert plot_sync_dict_3["last_sync_time"] > 0


@pytest.mark.asyncio
async def test_sync_flow() -> None:
    receiver, sync_steps = plot_sync_setup()

    for plot_info in sync_steps[State.loaded].args[0]:
        assert plot_info.filename not in receiver.plots()

    for path in sync_steps[State.removed].args[0]:
        assert path in receiver.plots()

    for path in sync_steps[State.invalid].args[0]:
        assert path not in receiver.invalid()

    for path in sync_steps[State.keys_missing].args[0]:
        assert path not in receiver.keys_missing()

    # Walk through all states from idle to done and run them with the test data
    for state in State:
        await run_sync_step(receiver, sync_steps[state], state)

    for plot_info in sync_steps[State.loaded].args[0]:
        assert plot_info.filename in receiver.plots()

    for path in sync_steps[State.removed].args[0]:
        assert path not in receiver.plots()

    for path in sync_steps[State.invalid].args[0]:
        assert path in receiver.invalid()

    for path in sync_steps[State.keys_missing].args[0]:
        assert path in receiver.keys_missing()

    # We should be in idle state again
    assert receiver.state() == State.idle


@pytest.mark.asyncio
async def test_invalid_ids() -> None:
    receiver, sync_steps = plot_sync_setup()
    for state in State:
        assert receiver.state() == state
        current_step = sync_steps[state]
        if receiver.state() == State.idle:
            # Set last_sync_id for the tests below
            receiver._last_sync_id = uint64(1)
            # Test "sync_started last doesn't match"
            invalid_last_sync_id_param = PlotSyncStart(
                plot_sync_identifier(uint64(0), uint64(0)), False, uint64(2), uint32(0)
            )
            await current_step.function(invalid_last_sync_id_param)
            assert_error_response(receiver, ErrorCodes.invalid_last_sync_id)
            # Test "last_sync_id == new_sync_id"
            invalid_sync_id_match_param = PlotSyncStart(
                plot_sync_identifier(uint64(1), uint64(0)), False, uint64(1), uint32(0)
            )
            await current_step.function(invalid_sync_id_match_param)
            assert_error_response(receiver, ErrorCodes.sync_ids_match)
            # Reset the last_sync_id to the default
            receiver._last_sync_id = uint64(0)
        else:
            # Test invalid sync_id
            invalid_sync_id_param = current_step.payload_type(
                plot_sync_identifier(uint64(10), uint64(receiver.expected_message_id())), *current_step.args
            )
            await current_step.function(invalid_sync_id_param)
            assert_error_response(receiver, ErrorCodes.invalid_identifier)
            # Test invalid message_id
            invalid_message_id_param = current_step.payload_type(
                plot_sync_identifier(receiver.expected_sync_id(), uint64(receiver.expected_message_id() + 1)),
                *current_step.args
            )
            await current_step.function(invalid_message_id_param)
            assert_error_response(receiver, ErrorCodes.invalid_identifier)
        payload = create_payload(current_step.payload_type, state == State.idle, *current_step.args)
        await current_step.function(payload)


@pytest.mark.parametrize(
    ["state_to_fail", "expected_error_code"],
    [
        pytest.param(State.loaded, ErrorCodes.plot_already_available, id="already available plots"),
        pytest.param(State.invalid, ErrorCodes.plot_already_available, id="already available paths"),
        pytest.param(State.removed, ErrorCodes.plot_not_available, id="not available"),
    ],
)
@pytest.mark.asyncio
async def test_plot_errors(state_to_fail: State, expected_error_code: ErrorCodes) -> None:
    receiver, sync_steps = plot_sync_setup()
    for state in State:
        assert receiver.state() == state
        current_step = sync_steps[state]
        if state == state_to_fail:
            plot_infos, _ = current_step.args
            await current_step.function(create_payload(current_step.payload_type, False, plot_infos, False))
            identifier = plot_sync_identifier(receiver.expected_sync_id(), receiver.expected_message_id())
            invalid_payload = current_step.payload_type(identifier, plot_infos, True)
            await current_step.function(invalid_payload)
            if state == state_to_fail:
                assert_error_response(receiver, expected_error_code)
                return
        else:
            await current_step.function(
                create_payload(current_step.payload_type, state == State.idle, *current_step.args)
            )
    assert False
