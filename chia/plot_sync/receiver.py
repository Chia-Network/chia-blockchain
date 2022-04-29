import logging
import time
from typing import Any, Callable, Collection, Coroutine, Dict, List, Optional

from chia.plot_sync.delta import Delta, PathListDelta, PlotListDelta
from chia.plot_sync.exceptions import (
    InvalidIdentifierError,
    InvalidLastSyncIdError,
    PlotAlreadyAvailableError,
    PlotNotAvailableError,
    PlotSyncException,
    SyncIdsMatchError,
)
from chia.plot_sync.util import ErrorCodes, State
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
from chia.server.ws_connection import ProtocolMessageTypes, WSChiaConnection, make_msg
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import int16, uint64
from chia.util.misc import get_list_or_len
from chia.util.streamable import _T_Streamable

log = logging.getLogger(__name__)


class Receiver:
    _connection: WSChiaConnection
    _sync_state: State
    _delta: Delta
    _expected_sync_id: uint64
    _expected_message_id: uint64
    _last_sync_id: uint64
    _last_sync_time: float
    _plots: Dict[str, Plot]
    _invalid: List[str]
    _keys_missing: List[str]
    _duplicates: List[str]
    _update_callback: Callable[[bytes32, Delta], Coroutine[Any, Any, None]]

    def __init__(
        self, connection: WSChiaConnection, update_callback: Callable[[bytes32, Delta], Coroutine[Any, Any, None]]
    ) -> None:
        self._connection = connection
        self._sync_state = State.idle
        self._delta = Delta()
        self._expected_sync_id = uint64(0)
        self._expected_message_id = uint64(0)
        self._last_sync_id = uint64(0)
        self._last_sync_time = 0
        self._plots = {}
        self._invalid = []
        self._keys_missing = []
        self._duplicates = []
        self._update_callback = update_callback  # type: ignore[assignment, misc]

    def reset(self) -> None:
        self._sync_state = State.idle
        self._expected_sync_id = uint64(0)
        self._expected_message_id = uint64(0)
        self._last_sync_id = uint64(0)
        self._last_sync_time = 0
        self._plots.clear()
        self._invalid.clear()
        self._keys_missing.clear()
        self._duplicates.clear()
        self._delta.clear()

    def bump_expected_message_id(self) -> None:
        self._expected_message_id = uint64(self._expected_message_id + 1)

    def connection(self) -> WSChiaConnection:
        return self._connection

    def state(self) -> State:
        return self._sync_state

    def expected_sync_id(self) -> uint64:
        return self._expected_sync_id

    def expected_message_id(self) -> uint64:
        return self._expected_message_id

    def last_sync_id(self) -> uint64:
        return self._last_sync_id

    def last_sync_time(self) -> float:
        return self._last_sync_time

    def plots(self) -> Dict[str, Plot]:
        return self._plots

    def invalid(self) -> List[str]:
        return self._invalid

    def keys_missing(self) -> List[str]:
        return self._keys_missing

    def duplicates(self) -> List[str]:
        return self._duplicates

    async def _process(
        self, method: Callable[[_T_Streamable], Any], message_type: ProtocolMessageTypes, message: Any
    ) -> None:
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
            log.warning(f"_process: InvalidIdentifierError {e}")
            await send_response(PlotSyncError(int16(e.error_code), f"{e}", e.expected_identifier))
        except PlotSyncException as e:
            log.warning(f"_process: Error {e}")
            await send_response(PlotSyncError(int16(e.error_code), f"{e}", None))
        except Exception as e:
            log.warning(f"_process: Exception {e}")
            await send_response(PlotSyncError(int16(ErrorCodes.unknown), f"{e}", None))

    def _validate_identifier(self, identifier: PlotSyncIdentifier, start: bool = False) -> None:
        sync_id_match = identifier.sync_id == self._expected_sync_id
        message_id_match = identifier.message_id == self._expected_message_id
        identifier_match = sync_id_match and message_id_match
        if (start and not message_id_match) or (not start and not identifier_match):
            expected: PlotSyncIdentifier = PlotSyncIdentifier(
                identifier.timestamp, self._expected_sync_id, self._expected_message_id
            )
            raise InvalidIdentifierError(
                identifier,
                expected,
            )

    async def _sync_started(self, data: PlotSyncStart) -> None:
        if data.initial:
            self.reset()
        self._validate_identifier(data.identifier, True)
        if data.last_sync_id != self.last_sync_id():
            raise InvalidLastSyncIdError(data.last_sync_id, self.last_sync_id())
        if data.last_sync_id == data.identifier.sync_id:
            raise SyncIdsMatchError(State.idle, data.last_sync_id)
        self._expected_sync_id = data.identifier.sync_id
        self._delta.clear()
        self._sync_state = State.loaded
        self.bump_expected_message_id()

    async def sync_started(self, data: PlotSyncStart) -> None:
        await self._process(self._sync_started, ProtocolMessageTypes.plot_sync_start, data)

    async def _process_loaded(self, plot_infos: PlotSyncPlotList) -> None:
        self._validate_identifier(plot_infos.identifier)

        for plot_info in plot_infos.data:
            if plot_info.filename in self._plots or plot_info.filename in self._delta.valid.additions:
                raise PlotAlreadyAvailableError(State.loaded, plot_info.filename)
            self._delta.valid.additions[plot_info.filename] = plot_info

        if plot_infos.final:
            self._sync_state = State.removed

        self.bump_expected_message_id()

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

        if paths.final:
            self._sync_state = next_state

        self.bump_expected_message_id()

    async def _process_removed(self, paths: PlotSyncPathList) -> None:
        await self.process_path_list(
            state=State.removed,
            next_state=State.invalid,
            target=self._plots,
            delta=self._delta.valid.removals,
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
            delta=self._delta.invalid.additions,
            paths=paths,
        )

    async def process_invalid(self, paths: PlotSyncPathList) -> None:
        await self._process(self._process_invalid, ProtocolMessageTypes.plot_sync_invalid, paths)

    async def _process_keys_missing(self, paths: PlotSyncPathList) -> None:
        await self.process_path_list(
            state=State.keys_missing,
            next_state=State.duplicates,
            target=self._keys_missing,
            delta=self._delta.keys_missing.additions,
            paths=paths,
        )

    async def process_keys_missing(self, paths: PlotSyncPathList) -> None:
        await self._process(self._process_keys_missing, ProtocolMessageTypes.plot_sync_keys_missing, paths)

    async def _process_duplicates(self, paths: PlotSyncPathList) -> None:
        await self.process_path_list(
            state=State.duplicates,
            next_state=State.done,
            target=self._duplicates,
            delta=self._delta.duplicates.additions,
            paths=paths,
        )

    async def process_duplicates(self, paths: PlotSyncPathList) -> None:
        await self._process(self._process_duplicates, ProtocolMessageTypes.plot_sync_duplicates, paths)

    async def _sync_done(self, data: PlotSyncDone) -> None:
        self._validate_identifier(data.identifier)
        # Update ids
        self._last_sync_id = self._expected_sync_id
        self._expected_sync_id = uint64(0)
        self._expected_message_id = uint64(0)
        # First create the update delta (i.e. transform invalid/keys_missing into additions/removals) which we will
        # send to the callback receiver below
        delta_invalid: PathListDelta = PathListDelta.from_lists(self._invalid, self._delta.invalid.additions)
        delta_keys_missing: PathListDelta = PathListDelta.from_lists(
            self._keys_missing, self._delta.keys_missing.additions
        )
        delta_duplicates: PathListDelta = PathListDelta.from_lists(self._duplicates, self._delta.duplicates.additions)
        update = Delta(
            PlotListDelta(self._delta.valid.additions.copy(), self._delta.valid.removals.copy()),
            delta_invalid,
            delta_keys_missing,
            delta_duplicates,
        )
        # Apply delta
        self._plots.update(self._delta.valid.additions)
        for removal in self._delta.valid.removals:
            del self._plots[removal]
        self._invalid = self._delta.invalid.additions.copy()
        self._keys_missing = self._delta.keys_missing.additions.copy()
        self._duplicates = self._delta.duplicates.additions.copy()
        # Update state and bump last sync time
        self._sync_state = State.idle
        self._last_sync_time = time.time()
        # Let the callback receiver know if this sync cycle caused any update
        try:
            await self._update_callback(self._connection.peer_node_id, update)  # type: ignore[misc,call-arg]
        except Exception as e:
            log.error(f"_update_callback raised: {e}")
        self._delta.clear()

    async def sync_done(self, data: PlotSyncDone) -> None:
        await self._process(self._sync_done, ProtocolMessageTypes.plot_sync_done, data)

    def to_dict(self, counts_only: bool = False) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "connection": {
                "node_id": self._connection.peer_node_id,
                "host": self._connection.peer_host,
                "port": self._connection.peer_port,
            },
            "plots": get_list_or_len(list(self._plots.values()), counts_only),
            "failed_to_open_filenames": get_list_or_len(self._invalid, counts_only),
            "no_key_filenames": get_list_or_len(self._keys_missing, counts_only),
            "duplicates": get_list_or_len(self._duplicates, counts_only),
        }
        if self._last_sync_time != 0:
            result["last_sync_time"] = self._last_sync_time
        return result
