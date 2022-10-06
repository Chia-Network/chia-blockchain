from __future__ import annotations

import pytest

from chia.plot_sync.exceptions import AlreadyStartedError, InvalidConnectionTypeError
from chia.plot_sync.sender import ExpectedResponse, Sender
from chia.plot_sync.util import Constants
from chia.protocols.harvester_protocol import PlotSyncIdentifier, PlotSyncResponse
from chia.server.ws_connection import NodeType, ProtocolMessageTypes
from chia.simulator.block_tools import BlockTools
from chia.util.ints import int16, uint64
from tests.plot_sync.util import get_dummy_connection, plot_sync_identifier


def test_default_values(bt: BlockTools) -> None:
    sender = Sender(bt.plot_manager)
    assert sender._plot_manager == bt.plot_manager
    assert sender._connection is None
    assert sender._sync_id == uint64(0)
    assert sender._next_message_id == uint64(0)
    assert sender._messages == []
    assert sender._last_sync_id == uint64(0)
    assert not sender._stop_requested
    assert sender._task is None
    assert sender._response is None


def test_set_connection_values(bt: BlockTools) -> None:
    farmer_connection = get_dummy_connection(NodeType.FARMER)
    sender = Sender(bt.plot_manager)
    # Test invalid NodeType values
    for connection_type in NodeType:
        if connection_type != NodeType.FARMER:
            pytest.raises(
                InvalidConnectionTypeError,
                sender.set_connection,
                get_dummy_connection(connection_type, farmer_connection.peer_node_id),
            )
    # Test setting a valid connection works
    sender.set_connection(farmer_connection)  # type:ignore[arg-type]
    assert sender._connection is not None
    assert sender._connection == farmer_connection  # type: ignore[comparison-overlap]


@pytest.mark.asyncio
async def test_start_stop_send_task(bt: BlockTools) -> None:
    sender = Sender(bt.plot_manager)
    # Make sure starting/restarting works
    for _ in range(2):
        assert sender._task is None
        await sender.start()
        assert sender._task is not None
        with pytest.raises(AlreadyStartedError):
            await sender.start()
        assert not sender._stop_requested
        sender.stop()
        assert sender._stop_requested
        await sender.await_closed()
        assert not sender._stop_requested
        assert sender._task is None


def test_set_response(bt: BlockTools) -> None:
    sender = Sender(bt.plot_manager)

    def new_expected_response(sync_id: int, message_id: int, message_type: ProtocolMessageTypes) -> ExpectedResponse:
        return ExpectedResponse(message_type, plot_sync_identifier(uint64(sync_id), uint64(message_id)))

    def new_response_message(sync_id: int, message_id: int, message_type: ProtocolMessageTypes) -> PlotSyncResponse:
        return PlotSyncResponse(
            plot_sync_identifier(uint64(sync_id), uint64(message_id)), int16(int(message_type.value)), None
        )

    response_message = new_response_message(0, 1, ProtocolMessageTypes.plot_sync_start)
    assert sender._response is None
    # Should trigger unexpected response because `Farmer._response` is `None`
    assert not sender.set_response(response_message)
    # Set `Farmer._response` and make sure the response gets assigned properly
    sender._response = new_expected_response(0, 1, ProtocolMessageTypes.plot_sync_start)
    assert sender._response.message is None
    assert sender.set_response(response_message)
    assert sender._response.message is not None
    # Should trigger unexpected response because we already received the message for the currently expected response
    assert not sender.set_response(response_message)
    # Test expired message
    expected_response = new_expected_response(1, 0, ProtocolMessageTypes.plot_sync_start)
    sender._response = expected_response
    expired_identifier = PlotSyncIdentifier(
        uint64(expected_response.identifier.timestamp - Constants.message_timeout - 1),
        expected_response.identifier.sync_id,
        expected_response.identifier.message_id,
    )
    expired_message = PlotSyncResponse(expired_identifier, int16(int(ProtocolMessageTypes.plot_sync_start.value)), None)
    assert not sender.set_response(expired_message)
    # Test invalid sync-id
    sender._response = new_expected_response(2, 0, ProtocolMessageTypes.plot_sync_start)
    assert not sender.set_response(new_response_message(3, 0, ProtocolMessageTypes.plot_sync_start))
    # Test invalid message-id
    sender._response = new_expected_response(2, 1, ProtocolMessageTypes.plot_sync_start)
    assert not sender.set_response(new_response_message(2, 2, ProtocolMessageTypes.plot_sync_start))
    # Test invalid message-type
    sender._response = new_expected_response(3, 0, ProtocolMessageTypes.plot_sync_start)
    assert not sender.set_response(new_response_message(3, 0, ProtocolMessageTypes.plot_sync_loaded))
