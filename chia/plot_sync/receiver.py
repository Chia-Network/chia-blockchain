from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Collection, Dict, List, Optional

from typing_extensions import Protocol

from chia.plot_sync.delta import Delta, PathListDelta, PlotListDelta
from chia.plot_sync.exceptions import (
    InvalidIdentifierError,
    InvalidLastSyncIdError,
    PlotAlreadyAvailableError,
    PlotNotAvailableError,
    PlotSyncException,
    SyncIdsMatchError,
)
from chia.plot_sync.util import ErrorCodes, State, T_PlotSyncMessage
from chia.protocols.harvester_protocol import (
    Plot,
    PlotSyncDone,
    PlotSyncError,
    PlotSyncIdentifier,
    PlotSyncPathList,
    PlotSyncPlotList,
    PlotSyncResponse,
    PlotSyncStart,
)
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import make_msg
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import int16, uint32, uint64
from chia.util.misc import get_list_or_len

log = logging.getLogger(__name__)


@dataclass
class Sync:
    state: State = State.idle
    sync_id: uint64 = uint64(0)
    next_message_id: uint64 = uint64(0)
    plots_processed: uint32 = uint32(0)
    plots_total: uint32 = uint32(0)
    delta: Delta = field(default_factory=Delta)
    time_done: Optional[float] = None

    def in_progress(self) -> bool:
        return self.sync_id != 0

    def bump_next_message_id(self) -> None:
        self.next_message_id = uint64(self.next_message_id + 1)

    def bump_plots_processed(self) -> None:
        self.plots_processed = uint32(self.plots_processed + 1)

    def __str__(self) -> str:
        return (
            f"[state {self.state}, "
            f"sync_id {self.sync_id}, "
            f"next_message_id {self.next_message_id}, "
            f"plots_processed {self.plots_processed}, "
            f"plots_total {self.plots_total}, "
            f"delta {self.delta}, "
            f"time_done {self.time_done}]"
        )


class ReceiverUpdateCallback(Protocol):
    def __call__(self, peer_id: bytes32, delta: Optional[Delta]) -> Awaitable[None]:
        pass


class Receiver:
    _connection: WSChiaConnection
    _current_sync: Sync
    _last_sync: Sync
    _plots: Dict[str, Plot]
    _invalid: List[str]
    _keys_missing: List[str]
    _duplicates: List[str]
    _total_plot_size: int
    _update_callback: ReceiverUpdateCallback

    def __init__(
        self,
        connection: WSChiaConnection,
        update_callback: ReceiverUpdateCallback,
    ) -> None:
        self._connection = connection
        self._current_sync = Sync()
        self._last_sync = Sync()
        self._plots = {}
        self._invalid = []
        self._keys_missing = []
        self._duplicates = []
        self._total_plot_size = 0
        self._update_callback = update_callback

    async def trigger_callback(self, update: Optional[Delta] = None) -> None:
        try:
            await self._update_callback(self._connection.peer_node_id, update)
        except Exception as e:
            log.error(f"_update_callback: node_id {self.connection().peer_node_id}, raised {e}")

    def reset(self) -> None:
        log.info(f"reset: node_id {self.connection().peer_node_id}, current_sync: {self._current_sync}")
        self._current_sync = Sync()
        self._last_sync = Sync()
        self._plots.clear()
        self._invalid.clear()
        self._keys_missing.clear()
        self._duplicates.clear()
        self._total_plot_size = 0

    def connection(self) -> WSChiaConnection:
        return self._connection

    def current_sync(self) -> Sync:
        return self._current_sync

    def last_sync(self) -> Sync:
        return self._last_sync

    def initial_sync(self) -> bool:
        return self._last_sync.sync_id == 0

    def plots(self) -> Dict[str, Plot]:
        return self._plots

    def invalid(self) -> List[str]:
        return self._invalid

    def keys_missing(self) -> List[str]:
        return self._keys_missing

    def duplicates(self) -> List[str]:
        return self._duplicates

    def total_plot_size(self) -> int:
        return self._total_plot_size

    async def _process(
        self, method: Callable[[T_PlotSyncMessage], Any], message_type: ProtocolMessageTypes, message: T_PlotSyncMessage
    ) -> None:
        log.debug(
            f"_process: node_id {self.connection().peer_node_id}, message_type: {message_type}, message: {message}"
        )

        async def send_response(plot_sync_error: Optional[PlotSyncError] = None) -> None:
            if self._connection is not None:
                await self._connection.send_message(
                    make_msg(
                        ProtocolMessageTypes.plot_sync_response,
                        PlotSyncResponse(message.identifier, int16(message_type.value), plot_sync_error),
                    )
                )

        try:
            await method(message)
            await send_response()
        except InvalidIdentifierError as e:
            log.warning(f"_process: node_id {self.connection().peer_node_id}, InvalidIdentifierError {e}")
            await send_response(PlotSyncError(int16(e.error_code), f"{e}", e.expected_identifier))
        except PlotSyncException as e:
            log.warning(f"_process: node_id {self.connection().peer_node_id}, Error {e}")
            await send_response(PlotSyncError(int16(e.error_code), f"{e}", None))
        except Exception as e:
            log.warning(f"_process: node_id {self.connection().peer_node_id}, Exception {e}")
            await send_response(PlotSyncError(int16(ErrorCodes.unknown), f"{e}", None))

    def _validate_identifier(self, identifier: PlotSyncIdentifier, start: bool = False) -> None:
        sync_id_match = identifier.sync_id == self._current_sync.sync_id
        message_id_match = identifier.message_id == self._current_sync.next_message_id
        identifier_match = sync_id_match and message_id_match
        if (start and not message_id_match) or (not start and not identifier_match):
            expected: PlotSyncIdentifier = PlotSyncIdentifier(
                identifier.timestamp, self._current_sync.sync_id, self._current_sync.next_message_id
            )
            raise InvalidIdentifierError(
                identifier,
                expected,
            )

    async def _sync_started(self, data: PlotSyncStart) -> None:
        if data.initial:
            self.reset()
        self._validate_identifier(data.identifier, True)
        if data.last_sync_id != self._last_sync.sync_id:
            raise InvalidLastSyncIdError(data.last_sync_id, self._last_sync.sync_id)
        if data.last_sync_id == data.identifier.sync_id:
            raise SyncIdsMatchError(State.idle, data.last_sync_id)
        self._current_sync.sync_id = data.identifier.sync_id
        self._current_sync.delta.clear()
        self._current_sync.state = State.loaded
        self._current_sync.plots_total = data.plot_file_count
        self._current_sync.bump_next_message_id()

    async def sync_started(self, data: PlotSyncStart) -> None:
        await self._process(self._sync_started, ProtocolMessageTypes.plot_sync_start, data)

    async def _process_loaded(self, plot_infos: PlotSyncPlotList) -> None:
        self._validate_identifier(plot_infos.identifier)

        for plot_info in plot_infos.data:
            if plot_info.filename in self._plots or plot_info.filename in self._current_sync.delta.valid.additions:
                raise PlotAlreadyAvailableError(State.loaded, plot_info.filename)
            self._current_sync.delta.valid.additions[plot_info.filename] = plot_info
            self._current_sync.bump_plots_processed()

        # Let the callback receiver know about the sync progress updates
        await self.trigger_callback()

        if plot_infos.final:
            self._current_sync.state = State.removed

        self._current_sync.bump_next_message_id()

    async def process_loaded(self, plot_infos: PlotSyncPlotList) -> None:
        await self._process(self._process_loaded, ProtocolMessageTypes.plot_sync_loaded, plot_infos)

    async def process_path_list(
        self,
        *,
        state: State,
        next_state: State,
        target: Collection[str],
        delta: List[str],
        paths: PlotSyncPathList,
        is_removal: bool = False,
    ) -> None:
        self._validate_identifier(paths.identifier)

        for path in paths.data:
            if is_removal and (path not in target or path in delta):
                raise PlotNotAvailableError(state, path)
            if not is_removal and path in delta:
                raise PlotAlreadyAvailableError(state, path)
            delta.append(path)
            if not is_removal:
                self._current_sync.bump_plots_processed()

        # Let the callback receiver know about the sync progress updates
        await self.trigger_callback()

        if paths.final:
            self._current_sync.state = next_state

        self._current_sync.bump_next_message_id()

    async def _process_removed(self, paths: PlotSyncPathList) -> None:
        await self.process_path_list(
            state=State.removed,
            next_state=State.invalid,
            target=self._plots,
            delta=self._current_sync.delta.valid.removals,
            paths=paths,
            is_removal=True,
        )

    async def process_removed(self, paths: PlotSyncPathList) -> None:
        await self._process(self._process_removed, ProtocolMessageTypes.plot_sync_removed, paths)

    async def _process_invalid(self, paths: PlotSyncPathList) -> None:
        await self.process_path_list(
            state=State.invalid,
            next_state=State.keys_missing,
            target=self._invalid,
            delta=self._current_sync.delta.invalid.additions,
            paths=paths,
        )

    async def process_invalid(self, paths: PlotSyncPathList) -> None:
        await self._process(self._process_invalid, ProtocolMessageTypes.plot_sync_invalid, paths)

    async def _process_keys_missing(self, paths: PlotSyncPathList) -> None:
        await self.process_path_list(
            state=State.keys_missing,
            next_state=State.duplicates,
            target=self._keys_missing,
            delta=self._current_sync.delta.keys_missing.additions,
            paths=paths,
        )

    async def process_keys_missing(self, paths: PlotSyncPathList) -> None:
        await self._process(self._process_keys_missing, ProtocolMessageTypes.plot_sync_keys_missing, paths)

    async def _process_duplicates(self, paths: PlotSyncPathList) -> None:
        await self.process_path_list(
            state=State.duplicates,
            next_state=State.done,
            target=self._duplicates,
            delta=self._current_sync.delta.duplicates.additions,
            paths=paths,
        )

    async def process_duplicates(self, paths: PlotSyncPathList) -> None:
        await self._process(self._process_duplicates, ProtocolMessageTypes.plot_sync_duplicates, paths)

    async def _sync_done(self, data: PlotSyncDone) -> None:
        self._validate_identifier(data.identifier)
        self._current_sync.time_done = time.time()
        # First create the update delta (i.e. transform invalid/keys_missing into additions/removals) which we will
        # send to the callback receiver below
        delta_invalid: PathListDelta = PathListDelta.from_lists(
            self._invalid, self._current_sync.delta.invalid.additions
        )
        delta_keys_missing: PathListDelta = PathListDelta.from_lists(
            self._keys_missing, self._current_sync.delta.keys_missing.additions
        )
        delta_duplicates: PathListDelta = PathListDelta.from_lists(
            self._duplicates, self._current_sync.delta.duplicates.additions
        )
        update = Delta(
            PlotListDelta(
                self._current_sync.delta.valid.additions.copy(), self._current_sync.delta.valid.removals.copy()
            ),
            delta_invalid,
            delta_keys_missing,
            delta_duplicates,
        )
        # Apply delta
        self._plots.update(self._current_sync.delta.valid.additions)
        for removal in self._current_sync.delta.valid.removals:
            del self._plots[removal]
        self._invalid = self._current_sync.delta.invalid.additions.copy()
        self._keys_missing = self._current_sync.delta.keys_missing.additions.copy()
        self._duplicates = self._current_sync.delta.duplicates.additions.copy()
        self._total_plot_size = sum(plot.file_size for plot in self._plots.values())
        # Save current sync as last sync and create a new current sync
        self._last_sync = self._current_sync
        self._current_sync = Sync()
        # Let the callback receiver know if this sync cycle caused any update
        await self.trigger_callback(update)

    async def sync_done(self, data: PlotSyncDone) -> None:
        await self._process(self._sync_done, ProtocolMessageTypes.plot_sync_done, data)

    def to_dict(self, counts_only: bool = False) -> Dict[str, Any]:
        syncing = None
        if self._current_sync.in_progress():
            syncing = {
                "initial": self.initial_sync(),
                "plot_files_processed": self._current_sync.plots_processed,
                "plot_files_total": self._current_sync.plots_total,
            }
        return {
            "connection": {
                "node_id": self._connection.peer_node_id,
                "host": self._connection.peer_info.host,
                "port": self._connection.peer_info.port,
            },
            "plots": get_list_or_len(list(self._plots.values()), counts_only),
            "failed_to_open_filenames": get_list_or_len(self._invalid, counts_only),
            "no_key_filenames": get_list_or_len(self._keys_missing, counts_only),
            "duplicates": get_list_or_len(self._duplicates, counts_only),
            "total_plot_size": self._total_plot_size,
            "syncing": syncing,
            "last_sync_time": self._last_sync.time_done,
        }
