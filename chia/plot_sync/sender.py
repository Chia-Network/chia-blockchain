from __future__ import annotations

import asyncio
import logging
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Iterable, List, Optional, Tuple, Type, TypeVar

from typing_extensions import Protocol

from chia.plot_sync.exceptions import AlreadyStartedError, InvalidConnectionTypeError
from chia.plot_sync.util import Constants
from chia.plotting.manager import PlotManager
from chia.plotting.util import PlotInfo
from chia.protocols.harvester_protocol import (
    Plot,
    PlotSyncDone,
    PlotSyncIdentifier,
    PlotSyncPathList,
    PlotSyncPlotList,
    PlotSyncResponse,
    PlotSyncStart,
)
from chia.server.ws_connection import NodeType, ProtocolMessageTypes, WSChiaConnection, make_msg
from chia.util.generator_tools import list_to_batches
from chia.util.ints import int16, uint32, uint64

log = logging.getLogger(__name__)


def _convert_plot_info_list(plot_infos: List[PlotInfo]) -> List[Plot]:
    converted: List[Plot] = []
    for plot_info in plot_infos:
        converted.append(
            Plot(
                filename=plot_info.prover.get_filename(),
                size=plot_info.prover.get_size(),
                plot_id=plot_info.prover.get_id(),
                pool_public_key=plot_info.pool_public_key,
                pool_contract_puzzle_hash=plot_info.pool_contract_puzzle_hash,
                plot_public_key=plot_info.plot_public_key,
                file_size=uint64(plot_info.file_size),
                time_modified=uint64(int(plot_info.time_modified)),
            )
        )
    return converted


class PayloadType(Protocol):
    def __init__(self, identifier: PlotSyncIdentifier, *args: object) -> None:
        ...

    def __bytes__(self) -> bytes:
        pass


T = TypeVar("T", bound=PayloadType)


@dataclass
class MessageGenerator(Generic[T]):
    sync_id: uint64
    message_type: ProtocolMessageTypes
    message_id: uint64
    payload_type: Type[T]
    args: Iterable[object]

    def generate(self) -> Tuple[PlotSyncIdentifier, T]:
        identifier = PlotSyncIdentifier(uint64(int(time.time())), self.sync_id, self.message_id)
        payload = self.payload_type(identifier, *self.args)
        return identifier, payload


@dataclass
class ExpectedResponse:
    message_type: ProtocolMessageTypes
    identifier: PlotSyncIdentifier
    message: Optional[PlotSyncResponse] = None

    def __str__(self) -> str:
        return (
            f"expected_message_type: {self.message_type.name}, "
            f"expected_identifier: {self.identifier}, message {self.message}"
        )


class Sender:
    _plot_manager: PlotManager
    _connection: Optional[WSChiaConnection]
    _sync_id: uint64
    _next_message_id: uint64
    _messages: List[MessageGenerator[PayloadType]]
    _last_sync_id: uint64
    _stop_requested = False
    _task: Optional[asyncio.Task[None]]
    _response: Optional[ExpectedResponse]

    def __init__(self, plot_manager: PlotManager) -> None:
        self._plot_manager = plot_manager
        self._connection = None
        self._sync_id = uint64(0)
        self._next_message_id = uint64(0)
        self._messages = []
        self._last_sync_id = uint64(0)
        self._stop_requested = False
        self._task = None
        self._response = None

    def __str__(self) -> str:
        return f"sync_id {self._sync_id}, next_message_id {self._next_message_id}, messages {len(self._messages)}"

    async def start(self) -> None:
        if self._task is not None and self._stop_requested:
            await self.await_closed()
        if self._task is None:
            self._task = asyncio.create_task(self._run())
            # TODO, Add typing in PlotManager
            if not self._plot_manager.initial_refresh() or self._sync_id != 0:  # type:ignore[no-untyped-call]
                self._reset()
        else:
            raise AlreadyStartedError()

    def stop(self) -> None:
        self._stop_requested = True

    async def await_closed(self) -> None:
        if self._task is not None:
            await self._task
        self._task = None
        self._reset()
        self._stop_requested = False

    def set_connection(self, connection: WSChiaConnection) -> None:
        assert connection.connection_type is not None
        if connection.connection_type != NodeType.FARMER:
            raise InvalidConnectionTypeError(connection.connection_type, NodeType.HARVESTER)
        self._connection = connection

    def bump_next_message_id(self) -> None:
        self._next_message_id = uint64(self._next_message_id + 1)

    def _reset(self) -> None:
        log.debug(f"_reset {self}")
        self._last_sync_id = uint64(0)
        self._sync_id = uint64(0)
        self._next_message_id = uint64(0)
        self._messages.clear()
        if self._task is not None:
            self.sync_start(self._plot_manager.plot_count(), True)
            for remaining, batch in list_to_batches(
                list(self._plot_manager.plots.values()), self._plot_manager.refresh_parameter.batch_size
            ):
                self.process_batch(batch, remaining)
            self.sync_done([], 0)

    async def _wait_for_response(self) -> bool:
        start = time.time()
        assert self._response is not None
        while time.time() - start < Constants.message_timeout and self._response.message is None:
            await asyncio.sleep(0.1)
        return self._response.message is not None

    def set_response(self, response: PlotSyncResponse) -> bool:
        if self._response is None or self._response.message is not None:
            log.warning(f"set_response skip unexpected response: {response}")
            return False
        if time.time() - float(response.identifier.timestamp) > Constants.message_timeout:
            log.warning(f"set_response skip expired response: {response}")
            return False
        if response.identifier.sync_id != self._response.identifier.sync_id:
            log.warning(
                "set_response unexpected sync-id: " f"{response.identifier.sync_id}/{self._response.identifier.sync_id}"
            )
            return False
        if response.identifier.message_id != self._response.identifier.message_id:
            log.warning(
                "set_response unexpected message-id: "
                f"{response.identifier.message_id}/{self._response.identifier.message_id}"
            )
            return False
        if response.message_type != int16(self._response.message_type.value):
            log.warning(
                "set_response unexpected message-type: " f"{response.message_type}/{self._response.message_type.value}"
            )
            return False
        log.debug(f"set_response valid {response}")
        self._response.message = response
        return True

    def _add_message(self, message_type: ProtocolMessageTypes, payload_type: Any, *args: Any) -> None:
        assert self._sync_id != 0
        message_id = uint64(len(self._messages))
        self._messages.append(MessageGenerator(self._sync_id, message_type, message_id, payload_type, args))

    async def _send_next_message(self) -> bool:
        def failed(message: str) -> bool:
            # By forcing a reset we try to get back into a normal state if some not recoverable failure came up.
            log.warning(message)
            self._reset()
            return False

        assert len(self._messages) >= self._next_message_id
        message_generator = self._messages[self._next_message_id]
        identifier, payload = message_generator.generate()
        if self._sync_id == 0 or identifier.sync_id != self._sync_id or identifier.message_id != self._next_message_id:
            return failed(f"Invalid message generator {message_generator} for {self}")

        self._response = ExpectedResponse(message_generator.message_type, identifier)
        log.debug(f"_send_next_message send {message_generator.message_type.name}: {payload}")
        if self._connection is None or not await self._connection.send_message(
            make_msg(message_generator.message_type, payload)
        ):
            return failed(f"Send failed {self._connection}")
        if not await self._wait_for_response():
            log.info(f"_send_next_message didn't receive response {self._response}")
            return False

        assert self._response.message is not None
        if self._response.message.error is not None:
            recovered = False
            expected = self._response.message.error.expected_identifier
            # If we have a recoverable error there is a `expected_identifier` included
            if expected is not None:
                # If the receiver has a zero sync/message id and we already sent all messages from the current event
                # we most likely missed the response to the done message. We can finalize the sync and move on here.
                all_sent = (
                    self._messages[-1].message_type == ProtocolMessageTypes.plot_sync_done
                    and self._next_message_id == len(self._messages) - 1
                )
                if expected.sync_id == expected.message_id == 0 and all_sent:
                    self._finalize_sync()
                    recovered = True
                elif self._sync_id == expected.sync_id and expected.message_id < len(self._messages):
                    self._next_message_id = expected.message_id
                    recovered = True
            if not recovered:
                return failed(f"Not recoverable error {self._response.message}")
            return True

        if self._response.message_type == ProtocolMessageTypes.plot_sync_done:
            self._finalize_sync()
        else:
            self.bump_next_message_id()

        return True

    def _add_list_batched(self, message_type: ProtocolMessageTypes, payload_type: Any, data: List[Any]) -> None:
        if len(data) == 0:
            self._add_message(message_type, payload_type, [], True)
            return
        for remaining, batch in list_to_batches(data, self._plot_manager.refresh_parameter.batch_size):
            self._add_message(message_type, payload_type, batch, remaining == 0)

    def sync_start(self, count: float, initial: bool) -> None:
        log.debug(f"sync_start {self}: count {count}, initial {initial}")
        while self.sync_active():
            if self._stop_requested:
                log.debug("sync_start aborted")
                return
            time.sleep(0.1)
        sync_id = int(time.time())
        # Make sure we have unique sync-id's even if we restart refreshing within a second (i.e. in tests)
        if sync_id == self._last_sync_id:
            sync_id = sync_id + 1
        log.debug(f"sync_start {sync_id}")
        self._sync_id = uint64(sync_id)
        self._add_message(
            ProtocolMessageTypes.plot_sync_start, PlotSyncStart, initial, self._last_sync_id, uint32(int(count))
        )

    def process_batch(self, loaded: List[PlotInfo], remaining: int) -> None:
        log.debug(f"process_batch {self}: loaded {len(loaded)}, remaining {remaining}")
        if len(loaded) > 0 or remaining == 0:
            converted = _convert_plot_info_list(loaded)
            self._add_message(ProtocolMessageTypes.plot_sync_loaded, PlotSyncPlotList, converted, remaining == 0)

    def sync_done(self, removed: List[Path], duration: float) -> None:
        log.debug(f"sync_done {self}: removed {len(removed)}, duration {duration}")
        removed_list = [str(x) for x in removed]
        self._add_list_batched(
            ProtocolMessageTypes.plot_sync_removed,
            PlotSyncPathList,
            removed_list,
        )
        failed_to_open_list = [str(x) for x in list(self._plot_manager.failed_to_open_filenames)]
        self._add_list_batched(ProtocolMessageTypes.plot_sync_invalid, PlotSyncPathList, failed_to_open_list)
        no_key_list = [str(x) for x in self._plot_manager.no_key_filenames]
        self._add_list_batched(ProtocolMessageTypes.plot_sync_keys_missing, PlotSyncPathList, no_key_list)
        duplicates_list = self._plot_manager.get_duplicates().copy()
        self._add_list_batched(ProtocolMessageTypes.plot_sync_duplicates, PlotSyncPathList, duplicates_list)
        self._add_message(ProtocolMessageTypes.plot_sync_done, PlotSyncDone, uint64(int(duration)))

    def _finalize_sync(self) -> None:
        log.debug(f"_finalize_sync {self}")
        assert self._sync_id != 0
        self._last_sync_id = self._sync_id
        self._next_message_id = uint64(0)
        self._messages.clear()
        # Do this at the end since `_sync_id` is used as sync active indicator.
        self._sync_id = uint64(0)

    def sync_active(self) -> bool:
        return self._sync_id != 0

    def connected(self) -> bool:
        return self._connection is not None

    async def _run(self) -> None:
        """
        This is the sender task responsible to send new messages during sync as they come into Sender._messages
        triggered by the plot manager callback.
        """
        while not self._stop_requested:
            try:
                while not self.connected() or not self.sync_active():
                    if self._stop_requested:
                        return
                    await asyncio.sleep(0.1)
                while not self._stop_requested and self.sync_active():
                    if self._next_message_id >= len(self._messages):
                        await asyncio.sleep(0.1)
                        continue
                    if not await self._send_next_message():
                        await asyncio.sleep(Constants.message_timeout)
            except Exception as e:
                log.error(f"Exception: {e} {traceback.format_exc()}")
                self._reset()
