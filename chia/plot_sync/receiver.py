import logging
import time
from typing import Any, Callable, Dict, List, Optional

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
from chia.protocols.harvester_protocol import Plot
from chia.protocols.plot_sync_protocol import Done, Error, Identifier, PathList, PlotList, Response, Start
from chia.server.ws_connection import ProtocolMessageTypes, WSChiaConnection, make_msg
from chia.util.ints import int16, uint64

log = logging.getLogger(__name__)


class Receiver:
    _connection: WSChiaConnection
    _sync_state: State
    _delta: Delta
    _expected_sync_id: uint64
    _expected_message_id: uint64
    _last_sync_id: uint64
    _plots: Dict[str, Plot]
    _invalid: List[str]
    _keys_missing: List[str]
    _last_activity: float
    _update_callback: Callable

    def __init__(self, connection: WSChiaConnection, update_callback: Callable) -> None:
        self._connection = connection
        self._sync_state = State.idle
        self._delta = Delta()
        self._expected_sync_id = uint64(0)
        self._expected_message_id = uint64(0)
        self._last_sync_id = uint64(0)
        self._plots = {}
        self._invalid = []
        self._keys_missing = []
        self._last_activity = 0
        self._update_callback = update_callback  # type: ignore[assignment]

    def reset(self) -> None:
        self._sync_state = State.idle
        self._expected_sync_id = uint64(0)
        self._expected_message_id = uint64(0)
        self._last_sync_id = uint64(0)
        self._plots.clear()
        self._invalid.clear()
        self._keys_missing.clear()
        self._delta.clear()
        self.bump_last_activity()

    def bump_last_activity(self) -> None:
        self._last_activity = time.time()

    def bump_expected_message_id(self) -> None:
        self._expected_message_id = uint64(self._expected_message_id + 1)

    def connection(self) -> Optional[WSChiaConnection]:
        return self._connection

    def state(self) -> State:
        return self._sync_state

    def expected_sync_id(self) -> uint64:
        return self._expected_sync_id

    def expected_message_id(self) -> uint64:
        return self._expected_message_id

    def last_sync_id(self) -> uint64:
        return self._last_sync_id

    def plots(self) -> Dict[str, Plot]:
        return self._plots

    def invalid(self) -> List[str]:
        return self._invalid

    def keys_missing(self) -> List[str]:
        return self._keys_missing

    async def _process(self, method: Callable, message_type: ProtocolMessageTypes, message: Any) -> None:
        try:
            await method(message)
            if self._connection is not None:
                await self._connection.send_message(
                    make_msg(
                        ProtocolMessageTypes.plot_sync_response,
                        Response(message.identifier, int16(message_type.value), None),
                    )
                )
        except InvalidIdentifierError as e:
            log.warning(f"_process: InvalidIdentifierError {e}")
            if self._connection is not None:
                await self._connection.send_message(
                    make_msg(
                        ProtocolMessageTypes.plot_sync_response,
                        Response(
                            message.identifier,
                            int16(message_type.value),
                            Error(int16(e.error_code), f"{e}", e.expected_identifier),
                        ),
                    )
                )
        except PlotSyncException as e:
            log.warning(f"_process: Error {e}")
            if self._connection is not None:
                await self._connection.send_message(
                    make_msg(
                        ProtocolMessageTypes.plot_sync_response,
                        Response(
                            message.identifier,
                            int16(message_type.value),
                            Error(int16(e.error_code), f"{e}", None),
                        ),
                    )
                )
        except Exception as e:
            log.warning(f"_process: Exception {e}")
            if self._connection is not None:
                await self._connection.send_message(
                    make_msg(
                        ProtocolMessageTypes.plot_sync_response,
                        Response(
                            message.identifier,
                            int16(message_type.value),
                            Error(int16(ErrorCodes.unknown), f"{e}", None),
                        ),
                    )
                )

    def _validate_identifier(self, identifier: Identifier, start: bool = False) -> None:
        sync_id_match = identifier.sync_id == self._expected_sync_id
        message_id_match = identifier.message_id == self._expected_message_id
        identifier_match = sync_id_match and message_id_match
        if start and not message_id_match or not start and not identifier_match:
            expected: Identifier = Identifier(identifier.timestamp, self._expected_sync_id, self._expected_message_id)
            raise InvalidIdentifierError(
                identifier,
                expected,
            )

    async def _sync_started(self, data: Start) -> None:
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
        self.bump_last_activity()
        self.bump_expected_message_id()

    async def sync_started(self, data: Start) -> None:
        await self._process(self._sync_started, ProtocolMessageTypes.plot_sync_start, data)

    async def _process_loaded(self, plot_infos: PlotList) -> None:
        self._validate_identifier(plot_infos.identifier)

        for plot_info in plot_infos.data:
            if plot_info.filename in self._plots or plot_info.filename in self._delta.valid.additions:
                raise PlotAlreadyAvailableError(State.loaded, plot_info.filename)
            self._delta.valid.additions[plot_info.filename] = plot_info

        if plot_infos.final:
            self._sync_state = State.removed

        self.bump_last_activity()
        self.bump_expected_message_id()

    async def process_loaded(self, plot_infos: PlotList) -> None:
        await self._process(self._process_loaded, ProtocolMessageTypes.plot_sync_loaded, plot_infos)

    async def process_path_list(
        self,
        state: State,
        next_state: State,
        target: Any,
        delta: List[str],
        paths: PathList,
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

        self.bump_last_activity()
        self.bump_expected_message_id()

    async def _process_removed(self, paths: PathList) -> None:
        await self.process_path_list(State.removed, State.invalid, self._plots, self._delta.valid.removals, paths, True)

    async def process_removed(self, paths: PathList) -> None:
        await self._process(self._process_removed, ProtocolMessageTypes.plot_sync_removed, paths)

    async def _process_invalid(self, paths: PathList) -> None:
        await self.process_path_list(
            State.invalid, State.keys_missing, self._invalid, self._delta.invalid.additions, paths
        )

    async def process_invalid(self, paths: PathList) -> None:
        await self._process(self._process_invalid, ProtocolMessageTypes.plot_sync_invalid, paths)

    async def _process_keys_missing(self, paths: PathList) -> None:
        await self.process_path_list(
            State.keys_missing,
            State.done,
            self._keys_missing,
            self._delta.keys_missing.additions,
            paths,
        )

    async def process_keys_missing(self, paths: PathList) -> None:
        await self._process(self._process_keys_missing, ProtocolMessageTypes.plot_sync_keys_missing, paths)

    async def _sync_done(self, data: Done) -> None:
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
        update = Delta(
            PlotListDelta(self._delta.valid.additions.copy(), self._delta.valid.removals.copy()),
            delta_invalid,
            delta_keys_missing,
        )
        # Apply delta
        self._plots.update(self._delta.valid.additions)
        for removal in self._delta.valid.removals:
            del self._plots[removal]
        self._invalid = self._delta.invalid.additions.copy()
        self._keys_missing = self._delta.keys_missing.additions.copy()
        # Update state and bump activity
        self._sync_state = State.idle
        self.bump_last_activity()
        # Let the callback receiver know if this sync cycle caused any update
        try:
            await self._update_callback(self._connection.peer_node_id, update)
        except Exception as e:
            log.error(f"_update_callback raised: {e}")
        self._delta.clear()

    async def sync_done(self, data: Done) -> None:
        await self._process(self._sync_done, ProtocolMessageTypes.plot_sync_done, data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "connection": {
                "node_id": self._connection.peer_node_id,
                "host": self._connection.peer_host,
                "port": self._connection.peer_port,
            },
            "plots": list(self._plots.values()),
            "failed_to_open_filenames": self._invalid,
            "no_key_filenames": self._keys_missing,
            "last_activity": self._last_activity,
        }
