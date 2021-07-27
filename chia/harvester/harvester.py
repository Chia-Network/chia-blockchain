import asyncio
import concurrent
import logging
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import chia.server.ws_connection as ws  # lgtm [py/import-and-import-from]
from chia.consensus.constants import ConsensusConstants
from chia.plotting.plot_tools import PlotsRefreshParameter, PlotManager

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

    def __init__(self, root_path: Path, config: Dict, constants: ConsensusConstants):
        self.log = log
        # TODO, remove checks below later after some versions / time
        refresh_parameter: PlotsRefreshParameter = PlotsRefreshParameter()
        if "plot_loading_frequency_seconds" in config:
            self.log.warning(
                "plot_loading_frequency_seconds is deprecated but found in config. Replace it with the "
                "new section `plots_refresh_parameter`. See `initial-config.yaml`."
            )
        if "plots_refresh_parameter" in config:
            refresh_parameter = PlotsRefreshParameter.from_json_dict(config["plots_refresh_parameter"])

        self.plot_manager = PlotManager(root_path, refresh_parameter=refresh_parameter)
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

    def _close(self):
        self._is_shutdown = True
        self.executor.shutdown(wait=True)

    async def _await_closed(self):
        pass

    def _set_state_changed_callback(self, callback: Callable):
        self.state_changed_callback = callback

    def _state_changed(self, change: str):
        if self.state_changed_callback is not None:
            self.state_changed_callback(change)

    def on_disconnect(self, connection: ws.WSChiaConnection):
        self.log.info(f"peer disconnected {connection.get_peer_info()}")
        self._state_changed("close_connection")

    def get_plots(self) -> Tuple[List[Dict], List[str], List[str]]:
        self.log.debug(f"get_plots prover items: {self.plot_manager.plot_count()}")
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

    async def refresh_plots(self):
        locked: bool = self._refresh_lock.locked()
        if not locked:
            async with self._refresh_lock:
                # Avoid double refreshing of plots
                loaded_plots = self.plot_manager.refresh()
        self.log.info(f"{loaded_plots} new plots loaded")
        if loaded_plots > 0:
            self._state_changed("plots")

    def delete_plot(self, str_path: str):
        self.plot_manager.remove_plot(Path(str_path))
        self._state_changed("plots")
        return True

    async def add_plot_directory(self, str_path: str) -> bool:
        self.plot_manager.add_plot_directory(str_path)
        await self.refresh_plots()
        return True

    async def get_plot_directories(self) -> List[str]:
        return self.plot_manager.get_plot_directories()

    async def remove_plot_directory(self, str_path: str) -> bool:
        self.plot_manager.remove_plot_directory(str_path)
        return True

    def set_server(self, server):
        self.server = server
