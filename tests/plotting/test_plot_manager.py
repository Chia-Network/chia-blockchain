import logging
import time
from os import unlink
from pathlib import Path
from shutil import copy, move
from typing import Callable, Iterator, List, Optional
import pytest
from blspy import G1Element

from dataclasses import dataclass
from chia.plotting.util import (
    PlotInfo,
    PlotRefreshResult,
    PlotRefreshEvents,
    remove_plot,
    get_plot_directories,
    add_plot_directory,
    remove_plot_directory,
)
from chia.util.config import create_default_chia_config
from chia.util.path import mkdir
from chia.plotting.manager import PlotManager
from tests.block_tools import get_plot_dir
from tests.plotting.util import get_test_plots
from tests.setup_nodes import bt
from tests.time_out_assert import time_out_assert

log = logging.getLogger(__name__)


@dataclass
class MockDiskProver:
    filename: str

    def get_filename(self) -> str:
        return self.filename


@dataclass
class MockPlotInfo:
    prover: MockDiskProver


class TestDirectory:
    path: Path
    plots: List[Path]

    def __init__(self, path: Path, plots_origin: List[Path]):
        self.path = path
        mkdir(path)
        # Drop the existing files in the test directories
        for plot in path.iterdir():
            unlink(plot)
        # Copy over the original plots
        for plot in plots_origin:
            if not Path(path / plot.name).exists():
                copy(plot, path)
        # Adjust the paths to reflect the testing plots
        self.plots = [path / plot.name for plot in plots_origin]

    def __len__(self):
        return len(self.plots)

    def plot_info_list(self) -> List[MockPlotInfo]:
        return [MockPlotInfo(MockDiskProver(str(x))) for x in self.plots]

    def path_list(self) -> List[Path]:
        return self.plots

    def drop(self, path: Path):
        assert self.path / path.name
        del self.plots[self.plots.index(self.path / path.name)]


class PlotRefreshTester:
    plot_manager: PlotManager
    expected_result: PlotRefreshResult
    expected_result_matched: bool

    def __init__(self, root_path: Path):
        self.plot_manager = PlotManager(root_path, self.refresh_callback)
        # Set a very high refresh interval here to avoid unintentional refresh cycles
        self.plot_manager.refresh_parameter.interval_seconds = 10000
        # Set to the current time to avoid automated refresh after we start below.
        self.plot_manager.last_refresh_time = time.time()
        self.plot_manager.start_refreshing()

    def refresh_callback(self, event: PlotRefreshEvents, refresh_result: PlotRefreshResult):
        if event != PlotRefreshEvents.done:
            # Only validate the final results for this tests
            return
        for name in ["loaded", "removed", "processed", "remaining"]:
            try:
                actual_value = refresh_result.__getattribute__(name)
                if type(actual_value) == list:
                    expected_list = self.expected_result.__getattribute__(name)
                    if len(expected_list) != len(actual_value):
                        return
                    values_found = 0
                    for value in actual_value:
                        if type(value) == PlotInfo:
                            for plot_info in expected_list:
                                if plot_info.prover.get_filename() == value.prover.get_filename():
                                    values_found += 1
                                    continue
                        else:
                            if value in expected_list:
                                values_found += 1
                                continue
                    if values_found != len(expected_list):
                        log.error(f"{name} invalid: values_found {values_found} expected {len(expected_list)}")
                        return
                else:
                    expected_value = self.expected_result.__getattribute__(name)
                    if actual_value != expected_value:
                        log.error(f"{name} invalid: actual {actual_value} expected {expected_value}")
                        return

            except AttributeError as error:
                log.error(f"{error}")
                return

        self.expected_result_matched = True

    async def run(self, expected_result: PlotRefreshResult):
        self.expected_result = expected_result
        self.expected_result_matched = False
        self.plot_manager.trigger_refresh()
        await time_out_assert(5, self.plot_manager.needs_refresh, value=False)
        assert self.expected_result_matched


@dataclass
class TestEnvironment:
    root_path: Path
    refresh_tester: PlotRefreshTester
    dir_1: TestDirectory
    dir_2: TestDirectory


@pytest.fixture(scope="function")
def test_environment(tmp_path) -> Iterator[TestEnvironment]:
    dir_1_count: int = 7
    dir_2_count: int = 3
    plots: List[Path] = get_test_plots()
    assert len(plots) >= dir_1_count + dir_2_count

    dir_1: TestDirectory = TestDirectory(tmp_path / "plots" / "1", plots[0:dir_1_count])
    dir_2: TestDirectory = TestDirectory(tmp_path / "plots" / "2", plots[dir_1_count : dir_1_count + dir_2_count])
    create_default_chia_config(tmp_path)

    refresh_tester = PlotRefreshTester(tmp_path)
    refresh_tester.plot_manager.set_public_keys(bt.plot_manager.farmer_public_keys, bt.plot_manager.pool_public_keys)

    yield TestEnvironment(tmp_path, refresh_tester, dir_1, dir_2)

    refresh_tester.plot_manager.stop_refreshing()


# Wrap `remove_plot` to give it the same interface as the other triggers, e.g. `add_plot_directory(Path, str)`.
def trigger_remove_plot(_: Path, plot_path: str):
    remove_plot(Path(plot_path))


@pytest.mark.asyncio
async def test_plot_refreshing(test_environment):
    env: TestEnvironment = test_environment
    expected_result = PlotRefreshResult()
    dir_duplicates: TestDirectory = TestDirectory(get_plot_dir().resolve() / "duplicates", env.dir_1.plots)

    async def run_test_case(
        *,
        trigger: Callable,
        test_path: Path,
        expect_loaded: List[MockPlotInfo],
        expect_removed: List[Path],
        expect_processed: int,
        expect_duplicates: int,
        expected_directories: int,
        expect_total_plots: int,
    ):
        expected_result.loaded = expect_loaded
        expected_result.removed = expect_removed
        expected_result.processed = expect_processed
        trigger(env.root_path, str(test_path))
        assert len(get_plot_directories(env.root_path)) == expected_directories
        await env.refresh_tester.run(expected_result)
        assert len(env.refresh_tester.plot_manager.plots) == expect_total_plots
        assert len(env.refresh_tester.plot_manager.cache) == expect_total_plots
        assert len(env.refresh_tester.plot_manager.get_duplicates()) == expect_duplicates
        assert len(env.refresh_tester.plot_manager.failed_to_open_filenames) == 0

    # Add dir_1
    await run_test_case(
        trigger=add_plot_directory,
        test_path=env.dir_1.path,
        expect_loaded=env.dir_1.plot_info_list(),
        expect_removed=[],
        expect_processed=len(env.dir_1),
        expect_duplicates=0,
        expected_directories=1,
        expect_total_plots=len(env.dir_1),
    )

    # Add dir_2
    await run_test_case(
        trigger=add_plot_directory,
        test_path=env.dir_2.path,
        expect_loaded=env.dir_2.plot_info_list(),
        expect_removed=[],
        expect_processed=len(env.dir_1) + len(env.dir_2),
        expect_duplicates=0,
        expected_directories=2,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )

    # Add dir_duplicates
    await run_test_case(
        trigger=add_plot_directory,
        test_path=dir_duplicates.path,
        expect_loaded=[],
        expect_removed=[],
        expect_processed=len(env.dir_1) + len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=len(dir_duplicates),
        expected_directories=3,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )
    for item in dir_duplicates.path.iterdir():
        assert item.is_file() and item in env.refresh_tester.plot_manager.get_duplicates()

    # Drop the duplicated plot we remove in the next test case from the test directory upfront so that the numbers match
    # the expected below
    drop_path = dir_duplicates.plots[0]
    dir_duplicates.drop(drop_path)
    # Delete one duplicated plot
    await run_test_case(
        trigger=trigger_remove_plot,
        test_path=drop_path,
        expect_loaded=[],
        expect_removed=[drop_path],
        expect_processed=len(env.dir_1) + len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=len(dir_duplicates),
        expected_directories=3,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )
    # Drop the duplicated plot we remove in the next test case from the test directory upfront so that the numbers match
    # the expected below
    drop_path = env.dir_1.plots[0]
    env.dir_1.drop(drop_path)
    # Delete one duplicated plot
    await run_test_case(
        trigger=trigger_remove_plot,
        test_path=drop_path,
        expect_loaded=[],
        expect_removed=[drop_path],
        expect_processed=len(env.dir_1) + len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=len(dir_duplicates),
        expected_directories=3,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )
    # Remove directory with the duplicates
    await run_test_case(
        trigger=remove_plot_directory,
        test_path=dir_duplicates.path,
        expect_loaded=[],
        expect_removed=dir_duplicates.path_list(),
        expect_processed=len(env.dir_1) + len(env.dir_2),
        expect_duplicates=0,
        expected_directories=2,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )
    for item in dir_duplicates.path.iterdir():
        assert item.is_file() and item not in env.refresh_tester.plot_manager.get_duplicates()

    # Re-add the directory with the duplicates for other tests
    await run_test_case(
        trigger=add_plot_directory,
        test_path=dir_duplicates.path,
        expect_loaded=[],
        expect_removed=[],
        expect_processed=len(env.dir_1) + len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=len(dir_duplicates),
        expected_directories=3,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )

    # Remove dir_1 from which the duplicated plots are loaded. This removes the duplicates of dir_1
    # and in the same run loads them from dir_duplicates.
    await run_test_case(
        trigger=remove_plot_directory,
        test_path=env.dir_1.path,
        expect_loaded=dir_duplicates.plot_info_list(),
        expect_removed=env.dir_1.path_list(),
        expect_processed=len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=0,
        expected_directories=2,
        expect_total_plots=len(env.dir_2) + len(dir_duplicates),
    )

    # Re-add the directory. Now the plot seen as duplicate is from dir_1, not from dir_duplicates like before
    await run_test_case(
        trigger=add_plot_directory,
        test_path=env.dir_1.path,
        expect_loaded=[],
        expect_removed=[],
        expect_processed=len(env.dir_1) + len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=len(dir_duplicates),
        expected_directories=3,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )
    # Drop the duplicated plot we remove in the next test case from the test directory upfront so that the numbers match
    # the expected below
    drop_path = env.dir_1.plots[2]
    env.dir_1.drop(drop_path)
    # Remove the duplicated plot
    await run_test_case(
        trigger=trigger_remove_plot,
        test_path=drop_path,
        expect_loaded=[],
        expect_removed=[drop_path],
        expect_processed=len(env.dir_1) + len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=len(env.dir_1),
        expected_directories=3,
        expect_total_plots=len(env.dir_2) + len(dir_duplicates),
    )
    # Remove dir_duplicates, this drops the duplicates and loads all plots from dir_1
    await run_test_case(
        trigger=remove_plot_directory,
        test_path=dir_duplicates.path,
        expect_loaded=env.dir_1.plot_info_list(),
        expect_removed=dir_duplicates.path_list(),
        expect_processed=len(env.dir_1) + len(env.dir_2),
        expect_duplicates=0,
        expected_directories=2,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )
    # Remove dir_2
    await run_test_case(
        trigger=remove_plot_directory,
        test_path=env.dir_2.path,
        expect_loaded=[],
        expect_removed=env.dir_2.path_list(),
        expect_processed=len(env.dir_1),
        expect_duplicates=0,
        expected_directories=1,
        expect_total_plots=len(env.dir_1),
    )
    # Remove dir_1
    await run_test_case(
        trigger=remove_plot_directory,
        test_path=env.dir_1.path,
        expect_loaded=[],
        expect_removed=env.dir_1.path_list(),
        expect_processed=0,
        expect_duplicates=0,
        expected_directories=0,
        expect_total_plots=0,
    )


@pytest.mark.asyncio
async def test_initial_refresh_flag(test_environment: TestEnvironment) -> None:
    env: TestEnvironment = test_environment
    assert env.refresh_tester.plot_manager.initial_refresh()
    for _ in range(2):
        await env.refresh_tester.run(PlotRefreshResult())
        assert not env.refresh_tester.plot_manager.initial_refresh()
    env.refresh_tester.plot_manager.reset()
    assert env.refresh_tester.plot_manager.initial_refresh()


@pytest.mark.asyncio
async def test_invalid_plots(test_environment):
    env: TestEnvironment = test_environment
    expected_result = PlotRefreshResult()
    # Test re-trying if processing a plot failed
    # First create a backup of the plot
    retry_test_plot = env.dir_1.path_list()[0].resolve()
    retry_test_plot_save = Path(env.dir_1.path / ".backup").resolve()
    copy(retry_test_plot, retry_test_plot_save)
    # Invalidate the plot
    with open(retry_test_plot, "r+b") as file:
        file.write(bytes(100))
    # Add it and validate it fails to load
    add_plot_directory(env.root_path, str(env.dir_1.path))
    expected_result.loaded = env.dir_1.plot_info_list()[1:]
    expected_result.removed = []
    expected_result.processed = len(env.dir_1)
    expected_result.remaining = 0
    await env.refresh_tester.run(expected_result)
    assert len(env.refresh_tester.plot_manager.failed_to_open_filenames) == 1
    assert retry_test_plot in env.refresh_tester.plot_manager.failed_to_open_filenames
    # Give it a non .plot ending and make sure it gets removed from the invalid list on the next refresh
    retry_test_plot_unload = Path(env.dir_1.path / ".unload").resolve()
    move(retry_test_plot, retry_test_plot_unload)
    expected_result.processed -= 1
    expected_result.loaded = []
    await env.refresh_tester.run(expected_result)
    assert len(env.refresh_tester.plot_manager.failed_to_open_filenames) == 0
    assert retry_test_plot not in env.refresh_tester.plot_manager.failed_to_open_filenames
    # Recover the name and make sure it reappears in the invalid list
    move(retry_test_plot_unload, retry_test_plot)
    expected_result.processed += 1
    await env.refresh_tester.run(expected_result)
    assert len(env.refresh_tester.plot_manager.failed_to_open_filenames) == 1
    assert retry_test_plot in env.refresh_tester.plot_manager.failed_to_open_filenames
    # Make sure the file stays in `failed_to_open_filenames` and doesn't get loaded in the next refresh cycle
    expected_result.loaded = []
    expected_result.processed = len(env.dir_1)
    await env.refresh_tester.run(expected_result)
    assert len(env.refresh_tester.plot_manager.failed_to_open_filenames) == 1
    assert retry_test_plot in env.refresh_tester.plot_manager.failed_to_open_filenames
    # Now decrease the re-try timeout, restore the valid plot file and make sure it properly loads now
    env.refresh_tester.plot_manager.refresh_parameter.retry_invalid_seconds = 0
    move(retry_test_plot_save, retry_test_plot)
    expected_result.loaded = env.dir_1.plot_info_list()[0:1]
    expected_result.processed = len(env.dir_1)
    await env.refresh_tester.run(expected_result)
    assert len(env.refresh_tester.plot_manager.failed_to_open_filenames) == 0
    assert retry_test_plot not in env.refresh_tester.plot_manager.failed_to_open_filenames


@pytest.mark.asyncio
async def test_keys_missing(test_environment: TestEnvironment) -> None:
    env: TestEnvironment = test_environment
    not_in_keychain_plots: List[Path] = get_test_plots("not_in_keychain")
    dir_not_in_keychain: TestDirectory = TestDirectory(
        env.root_path / "plots" / "not_in_keychain", not_in_keychain_plots
    )
    expected_result = PlotRefreshResult()
    # The plots in "not_in_keychain" directory have infinity g1 elements as farmer/pool key so they should be plots
    # with missing keys for now
    add_plot_directory(env.root_path, str(dir_not_in_keychain.path))
    expected_result.loaded = []
    expected_result.removed = []
    expected_result.processed = len(dir_not_in_keychain)
    expected_result.remaining = 0
    for i in range(2):
        await env.refresh_tester.run(expected_result)
        assert len(env.refresh_tester.plot_manager.no_key_filenames) == len(dir_not_in_keychain)
        for path in env.refresh_tester.plot_manager.no_key_filenames:
            assert path in dir_not_in_keychain.plots
    # Delete one of the plots and make sure it gets dropped from the no key filenames list
    drop_plot = dir_not_in_keychain.path_list()[0]
    dir_not_in_keychain.drop(drop_plot)
    drop_plot.unlink()
    assert drop_plot in env.refresh_tester.plot_manager.no_key_filenames
    expected_result.processed -= 1
    await env.refresh_tester.run(expected_result)
    assert drop_plot not in env.refresh_tester.plot_manager.no_key_filenames
    # Now add the missing keys to the plot manager's key lists and make sure the plots are getting loaded
    env.refresh_tester.plot_manager.farmer_public_keys.append(G1Element())
    env.refresh_tester.plot_manager.pool_public_keys.append(G1Element())
    expected_result.loaded = dir_not_in_keychain.plot_info_list()  # type: ignore[assignment]
    expected_result.processed = len(dir_not_in_keychain)
    await env.refresh_tester.run(expected_result)
    # And make sure they are dropped from the list of plots with missing keys
    assert len(env.refresh_tester.plot_manager.no_key_filenames) == 0


@pytest.mark.asyncio
async def test_plot_info_caching(test_environment):
    env: TestEnvironment = test_environment
    expected_result = PlotRefreshResult()
    add_plot_directory(env.root_path, str(env.dir_1.path))
    expected_result.loaded = env.dir_1.plot_info_list()
    expected_result.removed = []
    expected_result.processed = len(env.dir_1)
    expected_result.remaining = 0
    await env.refresh_tester.run(expected_result)
    assert env.refresh_tester.plot_manager.cache.path().exists()
    unlink(env.refresh_tester.plot_manager.cache.path())
    # Should not write the cache again on shutdown because it didn't change
    assert not env.refresh_tester.plot_manager.cache.path().exists()
    env.refresh_tester.plot_manager.stop_refreshing()
    assert not env.refresh_tester.plot_manager.cache.path().exists()
    # Manually trigger `save_cache` and make sure it creates a new cache file
    env.refresh_tester.plot_manager.cache.save()
    assert env.refresh_tester.plot_manager.cache.path().exists()
    refresh_tester: PlotRefreshTester = PlotRefreshTester(env.root_path)
    plot_manager = refresh_tester.plot_manager
    plot_manager.cache.load()
    assert len(plot_manager.cache) == len(env.refresh_tester.plot_manager.cache)
    for plot_id, cache_entry in env.refresh_tester.plot_manager.cache.items():
        cache_entry_new = plot_manager.cache.get(plot_id)
        assert cache_entry_new.pool_public_key == cache_entry.pool_public_key
        assert cache_entry_new.pool_contract_puzzle_hash == cache_entry.pool_contract_puzzle_hash
        assert cache_entry_new.plot_public_key == cache_entry.plot_public_key
    await refresh_tester.run(expected_result)
    for path, plot_info in env.refresh_tester.plot_manager.plots.items():
        assert path in plot_manager.plots
        assert plot_manager.plots[path].prover.get_filename() == plot_info.prover.get_filename()
        assert plot_manager.plots[path].prover.get_id() == plot_info.prover.get_id()
        assert plot_manager.plots[path].prover.get_memo() == plot_info.prover.get_memo()
        assert plot_manager.plots[path].prover.get_size() == plot_info.prover.get_size()
        assert plot_manager.plots[path].pool_public_key == plot_info.pool_public_key
        assert plot_manager.plots[path].pool_contract_puzzle_hash == plot_info.pool_contract_puzzle_hash
        assert plot_manager.plots[path].plot_public_key == plot_info.plot_public_key
        assert plot_manager.plots[path].file_size == plot_info.file_size
        assert plot_manager.plots[path].time_modified == plot_info.time_modified
    assert plot_manager.plot_filename_paths == env.refresh_tester.plot_manager.plot_filename_paths
    assert plot_manager.failed_to_open_filenames == env.refresh_tester.plot_manager.failed_to_open_filenames
    assert plot_manager.no_key_filenames == env.refresh_tester.plot_manager.no_key_filenames
    plot_manager.stop_refreshing()
    # Modify the content of the plot_manager.dat
    with open(plot_manager.cache.path(), "r+b") as file:
        file.write(b"\xff\xff")  # Sets Cache.version to 65535
    # Make sure it just loads the plots normally if it fails to load the cache
    refresh_tester: PlotRefreshTester = PlotRefreshTester(env.root_path)
    plot_manager = refresh_tester.plot_manager
    plot_manager.cache.load()
    assert len(plot_manager.cache) == 0
    plot_manager.set_public_keys(bt.plot_manager.farmer_public_keys, bt.plot_manager.pool_public_keys)
    await refresh_tester.run(expected_result)
    assert len(plot_manager.plots) == len(plot_manager.plots)
    plot_manager.stop_refreshing()


@pytest.mark.parametrize(
    ["event_to_raise"],
    [
        pytest.param(PlotRefreshEvents.started, id="started"),
        pytest.param(PlotRefreshEvents.batch_processed, id="batch_processed"),
        pytest.param(PlotRefreshEvents.done, id="done"),
    ],
)
@pytest.mark.asyncio
async def test_callback_event_raises(test_environment, event_to_raise: PlotRefreshEvents):
    last_event_fired: Optional[PlotRefreshEvents] = None

    def raising_callback(event: PlotRefreshEvents, _: PlotRefreshResult):
        nonlocal last_event_fired
        last_event_fired = event
        if event == event_to_raise:
            raise Exception(f"run_raise_in_callback {event_to_raise}")

    env: TestEnvironment = test_environment
    expected_result = PlotRefreshResult()
    # Load dir_1
    add_plot_directory(env.root_path, str(env.dir_1.path))
    expected_result.loaded = env.dir_1.plot_info_list()  # type: ignore[assignment]
    expected_result.removed = []
    expected_result.processed = len(env.dir_1)
    expected_result.remaining = 0
    await env.refresh_tester.run(expected_result)
    # Load dir_2
    add_plot_directory(env.root_path, str(env.dir_2.path))
    expected_result.loaded = env.dir_2.plot_info_list()  # type: ignore[assignment]
    expected_result.removed = []
    expected_result.processed = len(env.dir_1) + len(env.dir_2)
    expected_result.remaining = 0
    await env.refresh_tester.run(expected_result)
    # Now raise the exception in the callback
    default_callback = env.refresh_tester.plot_manager._refresh_callback
    env.refresh_tester.plot_manager.set_refresh_callback(raising_callback)
    env.refresh_tester.plot_manager.start_refreshing()
    env.refresh_tester.plot_manager.trigger_refresh()
    await time_out_assert(5, env.refresh_tester.plot_manager.needs_refresh, value=False)
    # And make sure the follow-up evens aren't fired
    assert last_event_fired == event_to_raise
    # The exception should trigger `PlotManager.reset()` and clear the plots
    assert len(env.refresh_tester.plot_manager.plots) == 0
    assert len(env.refresh_tester.plot_manager.plot_filename_paths) == 0
    assert len(env.refresh_tester.plot_manager.failed_to_open_filenames) == 0
    assert len(env.refresh_tester.plot_manager.no_key_filenames) == 0
    # The next run without the valid callback should lead to re-loading of all plot
    env.refresh_tester.plot_manager.set_refresh_callback(default_callback)
    expected_result.loaded = env.dir_1.plot_info_list() + env.dir_2.plot_info_list()  # type: ignore[assignment]
    expected_result.removed = []
    expected_result.processed = len(env.dir_1) + len(env.dir_2)
    expected_result.remaining = 0
    await env.refresh_tester.run(expected_result)
