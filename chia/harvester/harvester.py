from __future__ import annotations

import asyncio
import concurrent
import contextlib
import dataclasses
import logging
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, ClassVar, Dict, List, Optional, Tuple, cast

from typing_extensions import Literal

from chia.consensus.constants import ConsensusConstants
from chia.plot_sync.sender import Sender
from chia.plotting.manager import PlotManager
from chia.plotting.util import (
    DEFAULT_DECOMPRESSOR_THREAD_COUNT,
    DEFAULT_DECOMPRESSOR_TIMEOUT,
    DEFAULT_DISABLE_CPU_AFFINITY,
    DEFAULT_ENFORCE_GPU_INDEX,
    DEFAULT_GPU_INDEX,
    DEFAULT_MAX_COMPRESSION_LEVEL_ALLOWED,
    DEFAULT_PARALLEL_DECOMPRESSOR_COUNT,
    DEFAULT_USE_GPU_HARVESTING,
    HarvestingMode,
    PlotRefreshEvents,
    PlotRefreshResult,
    PlotsRefreshParameter,
    add_plot_directory,
    get_harvester_config,
    get_plot_directories,
    remove_plot,
    remove_plot_directory,
    update_harvester_config,
)
from chia.rpc.rpc_server import StateChangedProtocol, default_get_connections
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.util.cpu import available_logical_cores
from chia.util.ints import uint32

log = logging.getLogger(__name__)


class Harvester:
    if TYPE_CHECKING:
        from chia.rpc.rpc_server import RpcServiceProtocol

        _protocol_check: ClassVar[RpcServiceProtocol] = cast("Harvester", None)

    plot_manager: PlotManager
    plot_sync_sender: Sender
    root_path: Path
    _shut_down: bool
    executor: ThreadPoolExecutor
    state_changed_callback: Optional[StateChangedProtocol] = None
    constants: ConsensusConstants
    _refresh_lock: asyncio.Lock
    event_loop: asyncio.events.AbstractEventLoop
    _server: Optional[ChiaServer]
    _mode: HarvestingMode

    @property
    def server(self) -> ChiaServer:
        # This is a stop gap until the class usage is refactored such the values of
        # integral attributes are known at creation of the instance.
        if self._server is None:
            raise RuntimeError("server not assigned")

        return self._server

    def __init__(self, root_path: Path, config: Dict[str, Any], constants: ConsensusConstants):
        self.log = log
        self.root_path = root_path
        # TODO, remove checks below later after some versions / time
        refresh_parameter: PlotsRefreshParameter = PlotsRefreshParameter()
        if "plot_loading_frequency_seconds" in config:
            self.log.info(
                "`harvester.plot_loading_frequency_seconds` is deprecated. Consider replacing it with the new section "
                "`harvester.plots_refresh_parameter`. See `initial-config.yaml`."
            )
            refresh_parameter = dataclasses.replace(
                refresh_parameter, interval_seconds=config["plot_loading_frequency_seconds"]
            )
        if "plots_refresh_parameter" in config:
            refresh_parameter = PlotsRefreshParameter.from_json_dict(config["plots_refresh_parameter"])

        self.log.info(f"Using plots_refresh_parameter: {refresh_parameter}")

        self.plot_manager = PlotManager(
            root_path, refresh_parameter=refresh_parameter, refresh_callback=self._plot_refresh_callback
        )
        self._shut_down = False
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=config["num_threads"])
        self._server = None
        self.constants = constants
        self.state_changed_callback: Optional[StateChangedProtocol] = None
        self.parallel_read: bool = config.get("parallel_read", True)

        context_count = config.get("parallel_decompressor_count", DEFAULT_PARALLEL_DECOMPRESSOR_COUNT)
        thread_count = config.get("decompressor_thread_count", DEFAULT_DECOMPRESSOR_THREAD_COUNT)
        cpu_count = available_logical_cores()
        if thread_count == 0:
            thread_count = cpu_count // 2
        disable_cpu_affinity = config.get("disable_cpu_affinity", DEFAULT_DISABLE_CPU_AFFINITY)
        max_compression_level_allowed = config.get(
            "max_compression_level_allowed", DEFAULT_MAX_COMPRESSION_LEVEL_ALLOWED
        )
        use_gpu_harvesting = config.get("use_gpu_harvesting", DEFAULT_USE_GPU_HARVESTING)
        gpu_index = config.get("gpu_index", DEFAULT_GPU_INDEX)
        enforce_gpu_index = config.get("enforce_gpu_index", DEFAULT_ENFORCE_GPU_INDEX)
        decompressor_timeout = config.get("decompressor_timeout", DEFAULT_DECOMPRESSOR_TIMEOUT)

        try:
            self._mode = self.plot_manager.configure_decompressor(
                context_count,
                thread_count,
                disable_cpu_affinity,
                max_compression_level_allowed,
                use_gpu_harvesting,
                gpu_index,
                enforce_gpu_index,
                decompressor_timeout,
            )
        except Exception as e:
            self.log.error(f"{type(e)} {e} while configuring decompressor.")
            raise

        self.plot_sync_sender = Sender(self.plot_manager, self._mode)

    @contextlib.asynccontextmanager
    async def manage(self) -> AsyncIterator[None]:
        self._refresh_lock = asyncio.Lock()
        self.event_loop = asyncio.get_running_loop()
        try:
            yield
        finally:
            self._shut_down = True
            self.executor.shutdown(wait=True)
            self.plot_manager.stop_refreshing()
            self.plot_manager.reset()
            self.plot_sync_sender.stop()

            await self.plot_sync_sender.await_closed()

    def get_connections(self, request_node_type: Optional[NodeType]) -> List[Dict[str, Any]]:
        return default_get_connections(server=self.server, request_node_type=request_node_type)

    async def on_connect(self, connection: WSChiaConnection) -> None:
        self.state_changed("add_connection")

    def _set_state_changed_callback(self, callback: StateChangedProtocol) -> None:
        self.state_changed_callback = callback

    def state_changed(self, change: str, change_data: Optional[Dict[str, Any]] = None) -> None:
        if self.state_changed_callback is not None:
            self.state_changed_callback(change, change_data)

    def _plot_refresh_callback(self, event: PlotRefreshEvents, update_result: PlotRefreshResult) -> None:
        log_function = self.log.debug if event == PlotRefreshEvents.batch_processed else self.log.info
        log_function(
            f"_plot_refresh_callback: event {event.name}, loaded {len(update_result.loaded)}, "
            f"removed {len(update_result.removed)}, processed {update_result.processed}, "
            f"remaining {update_result.remaining}, "
            f"duration: {update_result.duration:.2f} seconds, "
            f"total plots: {len(self.plot_manager.plots)}"
        )
        if event == PlotRefreshEvents.started:
            self.plot_sync_sender.sync_start(update_result.remaining, self.plot_manager.initial_refresh())
        if event == PlotRefreshEvents.batch_processed:
            self.plot_sync_sender.process_batch(update_result.loaded, update_result.remaining)
        if event == PlotRefreshEvents.done:
            self.plot_sync_sender.sync_done(update_result.removed, update_result.duration)

    async def on_disconnect(self, connection: WSChiaConnection) -> None:
        self.log.info(f"peer disconnected {connection.get_peer_logging()}")
        self.state_changed("close_connection")
        self.plot_sync_sender.stop()
        asyncio.run_coroutine_threadsafe(self.plot_sync_sender.await_closed(), asyncio.get_running_loop())
        self.plot_manager.stop_refreshing()

    def get_plots(self) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
        self.log.debug(f"get_plots prover items: {self.plot_manager.plot_count()}")
        response_plots: List[Dict[str, Any]] = []
        with self.plot_manager:
            for path, plot_info in self.plot_manager.plots.items():
                prover = plot_info.prover
                response_plots.append(
                    {
                        "filename": str(path),
                        "size": prover.get_size(),
                        "plot_id": prover.get_id(),
                        "pool_public_key": plot_info.pool_public_key,
                        "pool_contract_puzzle_hash": plot_info.pool_contract_puzzle_hash,
                        "plot_public_key": plot_info.plot_public_key,
                        "file_size": plot_info.file_size,
                        "time_modified": int(plot_info.time_modified),
                        "compression_level": prover.get_compression_level(),
                    }
                )
            self.log.debug(
                f"get_plots response: plots: {len(response_plots)}, "
                f"failed_to_open_filenames: {len(self.plot_manager.failed_to_open_filenames)}, "
                f"no_key_filenames: {len(self.plot_manager.no_key_filenames)}"
            )
            return (
                response_plots,
                [str(s) for s, _ in self.plot_manager.failed_to_open_filenames.items()],
                [str(s) for s in self.plot_manager.no_key_filenames],
            )

    def delete_plot(self, str_path: str) -> Literal[True]:
        remove_plot(Path(str_path))
        self.plot_manager.trigger_refresh()
        self.state_changed("plots")
        return True

    async def add_plot_directory(self, str_path: str) -> bool:
        add_plot_directory(self.root_path, str_path)
        self.plot_manager.trigger_refresh()
        return True

    async def get_plot_directories(self) -> List[str]:
        return get_plot_directories(self.root_path)

    async def remove_plot_directory(self, str_path: str) -> bool:
        remove_plot_directory(self.root_path, str_path)
        self.plot_manager.trigger_refresh()
        return True

    async def get_harvester_config(self) -> Dict[str, Any]:
        return get_harvester_config(self.root_path)

    async def update_harvester_config(
        self,
        *,
        use_gpu_harvesting: Optional[bool] = None,
        gpu_index: Optional[int] = None,
        enforce_gpu_index: Optional[bool] = None,
        disable_cpu_affinity: Optional[bool] = None,
        parallel_decompressor_count: Optional[int] = None,
        decompressor_thread_count: Optional[int] = None,
        recursive_plot_scan: Optional[bool] = None,
        refresh_parameter_interval_seconds: Optional[uint32] = None,
    ) -> bool:
        refresh_parameter: Optional[PlotsRefreshParameter] = None
        if refresh_parameter_interval_seconds is not None:
            refresh_parameter = PlotsRefreshParameter(
                interval_seconds=refresh_parameter_interval_seconds,
                retry_invalid_seconds=self.plot_manager.refresh_parameter.retry_invalid_seconds,
                batch_size=self.plot_manager.refresh_parameter.batch_size,
                batch_sleep_milliseconds=self.plot_manager.refresh_parameter.batch_sleep_milliseconds,
            )

        update_harvester_config(
            self.root_path,
            use_gpu_harvesting=use_gpu_harvesting,
            gpu_index=gpu_index,
            enforce_gpu_index=enforce_gpu_index,
            disable_cpu_affinity=disable_cpu_affinity,
            parallel_decompressor_count=parallel_decompressor_count,
            decompressor_thread_count=decompressor_thread_count,
            recursive_plot_scan=recursive_plot_scan,
            refresh_parameter=refresh_parameter,
        )
        return True

    def set_server(self, server: ChiaServer) -> None:
        self._server = server
