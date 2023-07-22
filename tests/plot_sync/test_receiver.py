from __future__ import annotations

import dataclasses
import logging
import random
import time
from secrets import token_bytes
from typing import Any, Callable, List, Tuple, Type, Union

import pytest
from blspy import G1Element

from chia.consensus.pos_quality import UI_ACTUAL_SPACE_CONSTANT_FACTOR, _expected_plot_size
from chia.plot_sync.delta import Delta
from chia.plot_sync.receiver import Receiver, Sync
from chia.plot_sync.util import ErrorCodes, State
from chia.plotting.util import HarvestingMode
from chia.protocols.harvester_protocol import (
    Plot,
    PlotSyncDone,
    PlotSyncIdentifier,
    PlotSyncPathList,
    PlotSyncPlotList,
    PlotSyncResponse,
    PlotSyncStart,
)
from chia.server.outbound_message import NodeType
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint8, uint32, uint64
from chia.util.misc import get_list_or_len
from chia.util.streamable import _T_Streamable
from tests.plot_sync.util import get_dummy_connection

log = logging.getLogger(__name__)

next_message_id = uint64(0)


def assert_default_values(receiver: Receiver) -> None:
    assert receiver.current_sync() == Sync()
    assert receiver.last_sync() == Sync()
    assert receiver.plots() == {}
    assert receiver.invalid() == []
    assert receiver.keys_missing() == []
    assert receiver.duplicates() == []
    assert receiver.total_plot_size() == 0
    assert receiver.total_effective_plot_size() == 0
    assert receiver.harvesting_mode() is None


async def dummy_callback(_: bytes32, __: Delta) -> None:
    pass


class SyncStepData:
    state: State
    function: Any
    payload_type: Any
    args: Any

    def __init__(
        self, state: State, function: Callable[[_T_Streamable], Any], payload_type: Type[_T_Streamable], *args: Any
    ) -> None:
        self.state = state
        self.function = function
        self.payload_type = payload_type
        self.args = args


def plot_sync_identifier(current_sync_id: uint64, message_id: uint64) -> PlotSyncIdentifier:
    return PlotSyncIdentifier(uint64(0), current_sync_id, message_id)


def create_payload(payload_type: Any, start: bool, *args: Any) -> Any:
    global next_message_id
    if start:
        next_message_id = uint64(0)
    next_identifier = plot_sync_identifier(uint64(1), next_message_id)
    next_message_id = uint64(next_message_id + 1)
    return payload_type(next_identifier, *args)


def assert_error_response(plot_sync: Receiver, error_code: ErrorCodes) -> None:
    connection = plot_sync.connection()
    assert connection is not None
    # WSChiaConnection doesn't have last_sent_message its part of the WSChiaConnectionDummy class used for testing
    message = connection.last_sent_message  # type: ignore[attr-defined]
    assert message is not None
    response: PlotSyncResponse = PlotSyncResponse.from_bytes(message.data)
    assert response.error is not None
    assert response.error.code == error_code.value


def pre_function_validate(receiver: Receiver, data: Union[List[Plot], List[str]], expected_state: State) -> None:
    if expected_state == State.loaded:
        for plot_info in data:
            assert type(plot_info) == Plot
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


def post_function_validate(receiver: Receiver, data: Union[List[Plot], List[str]], expected_state: State) -> None:
    if expected_state == State.loaded:
        for plot_info in data:
            assert type(plot_info) == Plot
            assert plot_info.filename in receiver._current_sync.delta.valid.additions
    elif expected_state == State.removed:
        for path in data:
            assert path in receiver._current_sync.delta.valid.removals
    elif expected_state == State.invalid:
        for path in data:
            assert path in receiver._current_sync.delta.invalid.additions
    elif expected_state == State.keys_missing:
        for path in data:
            assert path in receiver._current_sync.delta.keys_missing.additions
    elif expected_state == State.duplicates:
        for path in data:
            assert path in receiver._current_sync.delta.duplicates.additions


@pytest.mark.asyncio
async def run_sync_step(receiver: Receiver, sync_step: SyncStepData) -> None:
    assert receiver.current_sync().state == sync_step.state
    last_sync_time_before = receiver._last_sync.time_done
    # For the the list types invoke the trigger function in batches
    if sync_step.payload_type == PlotSyncPlotList or sync_step.payload_type == PlotSyncPathList:
        step_data, _ = sync_step.args
        assert len(step_data) == 10
        # Invoke batches of: 1, 2, 3, 4 items and validate the data against plot store before and after
        indexes = [0, 1, 3, 6, 10]
        for i in range(0, len(indexes) - 1):
            plots_processed_before = receiver.current_sync().plots_processed
            invoke_data = step_data[indexes[i] : indexes[i + 1]]
            pre_function_validate(receiver, invoke_data, sync_step.state)
            await sync_step.function(
                create_payload(sync_step.payload_type, False, invoke_data, i == (len(indexes) - 2))
            )
            post_function_validate(receiver, invoke_data, sync_step.state)
            if sync_step.state == State.removed:
                assert receiver.current_sync().plots_processed == plots_processed_before
            else:
                assert receiver.current_sync().plots_processed == plots_processed_before + len(invoke_data)
    else:
        # For Start/Done just invoke it..
        await sync_step.function(create_payload(sync_step.payload_type, sync_step.state == State.idle, *sync_step.args))
    # Make sure we moved to the next state
    assert receiver.current_sync().state != sync_step.state
    if sync_step.payload_type == PlotSyncDone:
        assert receiver._last_sync.time_done != last_sync_time_before
        assert receiver.last_sync().plots_processed == receiver.last_sync().plots_total
    else:
        assert receiver._last_sync.time_done == last_sync_time_before


def plot_sync_setup() -> Tuple[Receiver, List[SyncStepData]]:
    harvester_connection = get_dummy_connection(NodeType.HARVESTER)
    receiver = Receiver(harvester_connection, dummy_callback)  # type:ignore[arg-type]

    # Create example plot data
    path_list = [str(x) for x in range(0, 40)]
    plot_info_list = [
        Plot(
            filename=str(x),
            size=uint8(0),
            plot_id=bytes32(token_bytes(32)),
            pool_contract_puzzle_hash=None,
            pool_public_key=None,
            plot_public_key=G1Element(),
            file_size=uint64(random.randint(0, 100)),
            time_modified=uint64(0),
            compression_level=uint8(0),
        )
        for x in path_list
    ]

    # Manually add the plots we want to remove in tests
    receiver._plots = {plot_info.filename: plot_info for plot_info in plot_info_list[0:10]}
    receiver._total_plot_size = sum(plot.file_size for plot in receiver.plots().values())
    receiver._total_effective_plot_size = int(
        sum(UI_ACTUAL_SPACE_CONSTANT_FACTOR * int(_expected_plot_size(plot.size)) for plot in receiver.plots().values())
    )
    sync_steps: List[SyncStepData] = [
        SyncStepData(
            State.idle,
            receiver.sync_started,
            PlotSyncStart,
            False,
            uint64(0),
            uint32(len(plot_info_list)),
            uint8(HarvestingMode.CPU),
        ),
        SyncStepData(State.loaded, receiver.process_loaded, PlotSyncPlotList, plot_info_list[10:20], True),
        SyncStepData(State.removed, receiver.process_removed, PlotSyncPathList, path_list[0:10], True),
        SyncStepData(State.invalid, receiver.process_invalid, PlotSyncPathList, path_list[20:30], True),
        SyncStepData(State.keys_missing, receiver.process_keys_missing, PlotSyncPathList, path_list[30:40], True),
        SyncStepData(State.duplicates, receiver.process_duplicates, PlotSyncPathList, path_list[10:20], True),
        SyncStepData(State.done, receiver.sync_done, PlotSyncDone, uint64(0)),
    ]

    return receiver, sync_steps


def test_default_values() -> None:
    assert_default_values(Receiver(get_dummy_connection(NodeType.HARVESTER), dummy_callback))  # type:ignore[arg-type]


@pytest.mark.asyncio
async def test_reset() -> None:
    receiver, sync_steps = plot_sync_setup()
    connection_before = receiver.connection()
    # Assign some dummy values
    receiver._current_sync.state = State.done
    receiver._current_sync.sync_id = uint64(1)
    receiver._current_sync.next_message_id = uint64(1)
    receiver._current_sync.plots_processed = uint32(1)
    receiver._current_sync.plots_total = uint32(1)
    receiver._current_sync.delta.valid.additions = receiver.plots().copy()
    receiver._current_sync.delta.valid.removals = ["1"]
    receiver._current_sync.delta.invalid.additions = ["1"]
    receiver._current_sync.delta.invalid.removals = ["1"]
    receiver._current_sync.delta.keys_missing.additions = ["1"]
    receiver._current_sync.delta.keys_missing.removals = ["1"]
    receiver._current_sync.delta.duplicates.additions = ["1"]
    receiver._current_sync.delta.duplicates.removals = ["1"]
    receiver._current_sync.time_done = time.time()
    receiver._last_sync = dataclasses.replace(receiver._current_sync)
    receiver._invalid = ["1"]
    receiver._keys_missing = ["1"]
    receiver._duplicates = ["1"]

    receiver._last_sync.sync_id = uint64(1)
    # Call `reset` and make sure all expected values are set back to their defaults.
    receiver.reset()
    assert_default_values(receiver)
    assert receiver._current_sync.delta == Delta()
    # Connection should remain
    assert receiver.connection() == connection_before


@pytest.mark.parametrize("counts_only", [True, False])
@pytest.mark.asyncio
async def test_to_dict(counts_only: bool) -> None:
    receiver, sync_steps = plot_sync_setup()
    plot_sync_dict_1 = receiver.to_dict(counts_only)

    assert get_list_or_len(plot_sync_dict_1["plots"], not counts_only) == 10
    assert get_list_or_len(plot_sync_dict_1["failed_to_open_filenames"], not counts_only) == 0
    assert get_list_or_len(plot_sync_dict_1["no_key_filenames"], not counts_only) == 0
    assert get_list_or_len(plot_sync_dict_1["duplicates"], not counts_only) == 0
    assert plot_sync_dict_1["total_plot_size"] == sum(plot.file_size for plot in receiver.plots().values())
    assert plot_sync_dict_1["total_effective_plot_size"] == int(
        sum(UI_ACTUAL_SPACE_CONSTANT_FACTOR * int(_expected_plot_size(plot.size)) for plot in receiver.plots().values())
    )
    assert plot_sync_dict_1["syncing"] is None
    assert plot_sync_dict_1["last_sync_time"] is None
    assert plot_sync_dict_1["connection"] == {
        "node_id": receiver.connection().peer_node_id,
        "host": receiver.connection().peer_info.host,
        "port": receiver.connection().peer_info.port,
    }
    assert plot_sync_dict_1["harvesting_mode"] is None

    # We should get equal dicts
    assert plot_sync_dict_1 == receiver.to_dict(counts_only)
    # But unequal dicts wit the opposite counts_only value
    assert plot_sync_dict_1 != receiver.to_dict(not counts_only)

    expected_plot_files_processed: int = 0
    expected_plot_files_total: int = sync_steps[State.idle].args[2]

    # Walk through all states from idle to done and run them with the test data and validate the sync progress
    for state in State:
        await run_sync_step(receiver, sync_steps[state])

        if state != State.idle and state != State.removed and state != State.done:
            expected_plot_files_processed += len(sync_steps[state].args[0])

        sync_data = receiver.to_dict()["syncing"]
        if state == State.done:
            expected_sync_data = None
        else:
            expected_sync_data = {
                "initial": True,
                "plot_files_processed": expected_plot_files_processed,
                "plot_files_total": expected_plot_files_total,
            }
        assert sync_data == expected_sync_data

    plot_sync_dict_3 = receiver.to_dict(counts_only)
    assert get_list_or_len(sync_steps[State.loaded].args[0], counts_only) == plot_sync_dict_3["plots"]
    assert (
        get_list_or_len(sync_steps[State.invalid].args[0], counts_only) == plot_sync_dict_3["failed_to_open_filenames"]
    )
    assert get_list_or_len(sync_steps[State.keys_missing].args[0], counts_only) == plot_sync_dict_3["no_key_filenames"]
    assert get_list_or_len(sync_steps[State.duplicates].args[0], counts_only) == plot_sync_dict_3["duplicates"]

    assert plot_sync_dict_3["total_plot_size"] == sum(plot.file_size for plot in receiver.plots().values())
    assert plot_sync_dict_3["total_effective_plot_size"] == int(
        sum(UI_ACTUAL_SPACE_CONSTANT_FACTOR * int(_expected_plot_size(plot.size)) for plot in receiver.plots().values())
    )
    assert plot_sync_dict_3["last_sync_time"] > 0
    assert plot_sync_dict_3["syncing"] is None
    assert sync_steps[State.idle].args[3] == plot_sync_dict_3["harvesting_mode"]

    # Trigger a repeated plot sync
    await receiver.sync_started(
        PlotSyncStart(
            PlotSyncIdentifier(uint64(time.time()), uint64(receiver.last_sync().sync_id + 1), uint64(0)),
            False,
            receiver.last_sync().sync_id,
            uint32(1),
            uint8(HarvestingMode.CPU),
        )
    )
    assert receiver.to_dict()["syncing"] == {
        "initial": False,
        "plot_files_processed": 0,
        "plot_files_total": 1,
    }


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

    for path in sync_steps[State.duplicates].args[0]:
        assert path not in receiver.duplicates()

    # Walk through all states from idle to done and run them with the test data
    for state in State:
        await run_sync_step(receiver, sync_steps[state])

    for plot_info in sync_steps[State.loaded].args[0]:
        assert plot_info.filename in receiver.plots()

    for path in sync_steps[State.removed].args[0]:
        assert path not in receiver.plots()

    for path in sync_steps[State.invalid].args[0]:
        assert path in receiver.invalid()

    for path in sync_steps[State.keys_missing].args[0]:
        assert path in receiver.keys_missing()

    for path in sync_steps[State.duplicates].args[0]:
        assert path in receiver.duplicates()

    # We should be in idle state again
    assert receiver.current_sync().state == State.idle


@pytest.mark.asyncio
async def test_invalid_ids() -> None:
    receiver, sync_steps = plot_sync_setup()
    for state in State:
        assert receiver.current_sync().state == state
        current_step = sync_steps[state]
        if receiver.current_sync().state == State.idle:
            # Set last_sync_id for the tests below
            receiver._last_sync.sync_id = uint64(1)
            # Test "sync_started last doesn't match"
            invalid_last_sync_id_param = PlotSyncStart(
                plot_sync_identifier(uint64(0), uint64(0)), False, uint64(2), uint32(0), uint8(HarvestingMode.CPU)
            )
            await current_step.function(invalid_last_sync_id_param)
            assert_error_response(receiver, ErrorCodes.invalid_last_sync_id)
            # Test "last_sync_id == new_sync_id"
            invalid_sync_id_match_param = PlotSyncStart(
                plot_sync_identifier(uint64(1), uint64(0)), False, uint64(1), uint32(0), uint8(HarvestingMode.CPU)
            )
            await current_step.function(invalid_sync_id_match_param)
            assert_error_response(receiver, ErrorCodes.sync_ids_match)
            # Reset the last_sync_id to the default
            receiver._last_sync.sync_id = uint64(0)
        else:
            # Test invalid sync_id
            invalid_sync_id_param = current_step.payload_type(
                plot_sync_identifier(uint64(10), uint64(receiver.current_sync().next_message_id)), *current_step.args
            )
            await current_step.function(invalid_sync_id_param)
            assert_error_response(receiver, ErrorCodes.invalid_identifier)
            # Test invalid message_id
            invalid_message_id_param = current_step.payload_type(
                plot_sync_identifier(
                    receiver.current_sync().sync_id, uint64(receiver.current_sync().next_message_id + 1)
                ),
                *current_step.args,
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
        assert receiver.current_sync().state == state
        current_step = sync_steps[state]
        if state == state_to_fail:
            plot_infos, _ = current_step.args
            await current_step.function(create_payload(current_step.payload_type, False, plot_infos, False))
            identifier = plot_sync_identifier(receiver.current_sync().sync_id, receiver.current_sync().next_message_id)
            invalid_payload = current_step.payload_type(identifier, plot_infos, True)
            await current_step.function(invalid_payload)
            if state == state_to_fail:
                assert_error_response(receiver, expected_error_code)
                return
        else:
            await current_step.function(
                create_payload(current_step.payload_type, state == State.idle, *current_step.args)
            )
    assert False, "Didn't fail in the expected state"
