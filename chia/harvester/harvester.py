import asyncio
import concurrent
import logging
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from chia.consensus.coinbase import create_puzzlehash_for_pk
import chia.server.ws_connection as ws  # lgtm [py/import-and-import-from]
from chia.consensus.constants import ConsensusConstants
from chia.plotting.manager import PlotManager
from chia.plotting.util import (
    add_plot_directory,
    get_plot_directories,
    remove_plot_directory,
    remove_plot,
    PlotsRefreshParameter,
    PlotRefreshResult,
    PlotRefreshEvents,
)
from chia.util.streamable import dataclass_from_dict
from chia.util.bech32m import encode_puzzle_hash

log = logging.getLogger(__name__)


class Harvester:
    plot_manager: PlotManager
    root_path: Path
    _is_shutdown: bool
    executor: ThreadPoolExecutor
    state_changed_callback: Optional[Callable]
    cached_challenges: List
    constants: ConsensusConstants
    _refresh_lock: asyncio.Lock
    event_loop: asyncio.events.AbstractEventLoop
    config: Dict

    def __init__(self, root_path: Path, config: Dict, constants: ConsensusConstants):
        self.log = log
        self.root_path = root_path
        self.config = config
        # TODO, remove checks below later after some versions / time
        refresh_parameter: PlotsRefreshParameter = PlotsRefreshParameter()
        if "plot_loading_frequency_seconds" in config:
            self.log.info(
                "`harvester.plot_loading_frequency_seconds` is deprecated. Consider replacing it with the new section "
                "`harvester.plots_refresh_parameter`. See `initial-config.yaml`."
            )
        if "plots_refresh_parameter" in config:
            refresh_parameter = dataclass_from_dict(PlotsRefreshParameter, config["plots_refresh_parameter"])

        self.plot_manager = PlotManager(
            root_path, refresh_parameter=refresh_parameter, refresh_callback=self._plot_refresh_callback
        )
        self._is_shutdown = False
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=config["num_threads"])
        self.state_changed_callback = None
        self.server = None
        self.constants = constants
        self.cached_challenges = []
        self.state_changed_callback: Optional[Callable] = None
        self.parallel_read: bool = config.get("parallel_read", True)

    async def _start(self):
        self._refresh_lock = asyncio.Lock()
        self.event_loop = asyncio.get_event_loop()

    def _close(self):
        self._is_shutdown = True
        self.executor.shutdown(wait=True)
        self.plot_manager.stop_refreshing()

    async def _await_closed(self):
        pass

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    def _plot_refresh_callback(self, event: PlotRefreshEvents, update_result: PlotRefreshResult):
        self.log.info(
            f"refresh_batch: event {event.name}, loaded {update_result.loaded}, "
            f"removed {update_result.removed}, processed {update_result.processed}, "
            f"remaining {update_result.remaining}, "
            f"duration: {update_result.duration:.2f} seconds"
        )
        if update_result.loaded > 0:
            self.event_loop.call_soon_threadsafe(self._state_changed, "plots")

    def on_disconnect(self, connection: ws.WSChiaConnection):
        self.log.info(f"peer disconnected {connection.get_peer_logging()}")
        self._state_changed("close_connection")

    def get_plots(self) -> Tuple[List[Dict], List[str], List[str]]:
        self.log.debug(f"get_plots prover items: {self.plot_manager.plot_count()}")
        address_prefix = self.config["network_overrides"]["config"][self.config["selected_network"]]["address_prefix"]
        response_plots: List[Dict] = []
        with self.plot_manager:
            for path, plot_info in self.plot_manager.plots.items():
                prover = plot_info.prover
                response_plots.append(
                    {
                        "filename": str(path),
                        "size": prover.get_size(),
                        "plot-seed": prover.get_id(),  # Deprecated
                        "plot_id": prover.get_id(),
                        "pool_public_key": plot_info.pool_public_key,
                        "pool_contract_puzzle_hash": plot_info.pool_contract_puzzle_hash,
                        "plot_public_key": plot_info.plot_public_key,
                        "file_size": plot_info.file_size,
                        "time_modified": plot_info.time_modified,
                        "farmer_public_key": plot_info.farmer_public_key,
                        "farmer_puzzle_hash": encode_puzzle_hash(create_puzzlehash_for_pk(plot_info.farmer_public_key), address_prefix),
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

    def delete_plot(self, str_path: str):
        remove_plot(Path(str_path))
        self.plot_manager.trigger_refresh()
        self._state_changed("plots")
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

    def set_server(self, server):
        self.server = server
