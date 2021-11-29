import logging
from os import unlink
from pathlib import Path
from shutil import copy, move
from typing import Callable, List
import pytest

from dataclasses import dataclass
from chia.plotting.util import (
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
from tests.setup_nodes import bt
from tests.time_out_assert import time_out_assert

log = logging.getLogger(__name__)

expected_result: PlotRefreshResult = PlotRefreshResult()
expected_result_matched = True


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

    def drop(self, path: Path):
        assert self.path / path.name
        del self.plots[self.plots.index(self.path / path.name)]


@dataclass
class TestEnvironment:
    root_path: Path
    plot_manager: PlotManager
    dir_1: TestDirectory
    dir_2: TestDirectory


@pytest.fixture(scope="function")
def test_environment(tmp_path) -> TestEnvironment:
    dir_1_count: int = 7
    dir_2_count: int = 3
    plots: List[Path] = list(sorted(get_plot_dir().glob("*.plot")))
    assert len(plots) >= dir_1_count + dir_2_count

    dir_1: TestDirectory = TestDirectory(tmp_path / "plots" / "1", plots[0:dir_1_count])
    dir_2: TestDirectory = TestDirectory(tmp_path / "plots" / "2", plots[dir_1_count : dir_1_count + dir_2_count])
    create_default_chia_config(tmp_path)

    plot_manager = PlotManager(tmp_path, refresh_callback)
    plot_manager.set_public_keys(bt.plot_manager.farmer_public_keys, bt.plot_manager.pool_public_keys)

    return TestEnvironment(tmp_path, plot_manager, dir_1, dir_2)


# Wrap `remove_plot` to give it the same interface as the other triggers, e.g. `add_plot_directory(Path, str)`.
def trigger_remove_plot(_: Path, plot_path: str):
    remove_plot(Path(plot_path))


# Note: We assign `expected_result_matched` in the callback and assert it in the test thread to avoid
# crashing the refresh thread of the plot manager with invalid assertions.
def refresh_callback(event: PlotRefreshEvents, refresh_result: PlotRefreshResult):
    global expected_result_matched
    if event != PlotRefreshEvents.done:
        # Only validate the final results for this tests
        return
    expected_result_matched = validate_values(
        ["loaded", "removed", "processed", "remaining"], refresh_result, expected_result
    )


def validate_values(names: List[str], actual: PlotRefreshResult, expected: PlotRefreshResult):
    for name in names:
        try:
            actual_value = actual.__getattribute__(name)
            expected_value = expected.__getattribute__(name)
            if actual_value != expected_value:
                log.error(f"{name} invalid: actual {actual_value} expected {expected_value}")
                return False
        except AttributeError as error:
            log.error(f"{error}")
            return False
    return True


async def run_refresh_test(manager: PlotManager):
    global expected_result_matched
    expected_result_matched = True
    manager.start_refreshing()
    manager.trigger_refresh()
    await time_out_assert(5, manager.needs_refresh, value=False)
    assert expected_result_matched


@pytest.mark.asyncio
async def test_plot_refreshing(test_environment):
    env: TestEnvironment = test_environment
    dir_duplicates: TestDirectory = TestDirectory(get_plot_dir().resolve() / "duplicates", env.dir_1.plots)

    async def run_test_case(
        *,
        trigger: Callable,
        test_path: Path,
        expect_loaded: int,
        expect_removed: int,
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
        await run_refresh_test(env.plot_manager)
        assert len(env.plot_manager.plots) == expect_total_plots
        assert len(env.plot_manager.cache) == expect_total_plots
        assert len(env.plot_manager.get_duplicates()) == expect_duplicates
        assert len(env.plot_manager.failed_to_open_filenames) == 0

    # Add dir_1
    await run_test_case(
        trigger=add_plot_directory,
        test_path=env.dir_1.path,
        expect_loaded=len(env.dir_1),
        expect_removed=0,
        expect_processed=len(env.dir_1),
        expect_duplicates=0,
        expected_directories=1,
        expect_total_plots=len(env.dir_1),
    )

    # Add dir_2
    await run_test_case(
        trigger=add_plot_directory,
        test_path=env.dir_2.path,
        expect_loaded=len(env.dir_2),
        expect_removed=0,
        expect_processed=len(env.dir_1) + len(env.dir_2),
        expect_duplicates=0,
        expected_directories=2,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )

    # Add dir_duplicates
    await run_test_case(
        trigger=add_plot_directory,
        test_path=dir_duplicates.path,
        expect_loaded=0,
        expect_removed=0,
        expect_processed=len(env.dir_1) + len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=len(dir_duplicates),
        expected_directories=3,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )
    for item in dir_duplicates.path.iterdir():
        assert item.is_file() and item in env.plot_manager.get_duplicates()

    # Drop the duplicated plot we remove in the next test case from the test directory upfront so that the numbers match
    # the expected below
    drop_path = dir_duplicates.plots[0]
    dir_duplicates.drop(drop_path)
    # Delete one duplicated plot
    await run_test_case(
        trigger=trigger_remove_plot,
        test_path=drop_path,
        expect_loaded=0,
        expect_removed=1,
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
        expect_loaded=0,
        expect_removed=1,
        expect_processed=len(env.dir_1) + len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=len(dir_duplicates),
        expected_directories=3,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )
    # Remove directory with the duplicates
    await run_test_case(
        trigger=remove_plot_directory,
        test_path=dir_duplicates.path,
        expect_loaded=0,
        expect_removed=len(dir_duplicates),
        expect_processed=len(env.dir_1) + len(env.dir_2),
        expect_duplicates=0,
        expected_directories=2,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )
    for item in dir_duplicates.path.iterdir():
        assert item.is_file() and item not in env.plot_manager.get_duplicates()

    # Re-add the directory with the duplicates for other tests
    await run_test_case(
        trigger=add_plot_directory,
        test_path=dir_duplicates.path,
        expect_loaded=0,
        expect_removed=0,
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
        expect_loaded=len(dir_duplicates),
        expect_removed=len(env.dir_1),
        expect_processed=len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=0,
        expected_directories=2,
        expect_total_plots=len(env.dir_2) + len(dir_duplicates),
    )

    # Re-add the directory. Now the plot seen as duplicate is from dir_1, not from dir_duplicates like before
    await run_test_case(
        trigger=add_plot_directory,
        test_path=env.dir_1.path,
        expect_loaded=len(env.dir_1) - len(dir_duplicates),
        expect_removed=0,
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
        expect_loaded=0,
        expect_removed=1,
        expect_processed=len(env.dir_1) + len(env.dir_2) + len(dir_duplicates),
        expect_duplicates=len(env.dir_1),
        expected_directories=3,
        expect_total_plots=len(env.dir_2) + len(dir_duplicates),
    )
    # Remove dir_duplicates, this drops the duplicates and loads all plots from dir_1
    await run_test_case(
        trigger=remove_plot_directory,
        test_path=dir_duplicates.path,
        expect_loaded=len(env.dir_1),
        expect_removed=len(dir_duplicates),
        expect_processed=len(env.dir_1) + len(env.dir_2),
        expect_duplicates=0,
        expected_directories=2,
        expect_total_plots=len(env.dir_1) + len(env.dir_2),
    )
    # Remove dir_2
    await run_test_case(
        trigger=remove_plot_directory,
        test_path=env.dir_2.path,
        expect_loaded=0,
        expect_removed=len(env.dir_2),
        expect_processed=len(env.dir_1),
        expect_duplicates=0,
        expected_directories=1,
        expect_total_plots=len(env.dir_1),
    )
    # Remove dir_1
    await run_test_case(
        trigger=remove_plot_directory,
        test_path=env.dir_1.path,
        expect_loaded=0,
        expect_removed=len(env.dir_1),
        expect_processed=0,
        expect_duplicates=0,
        expected_directories=0,
        expect_total_plots=0,
    )
    env.plot_manager.stop_refreshing()


@pytest.mark.asyncio
async def test_invalid_plots(test_environment):
    env: TestEnvironment = test_environment
    # Test re-trying if processing a plot failed
    # First create a backup of the plot
    retry_test_plot = list(env.dir_1.path.iterdir())[0].resolve()
    retry_test_plot_save = Path(env.dir_1.path / ".backup").resolve()
    copy(retry_test_plot, retry_test_plot_save)
    # Invalidate the plot
    with open(retry_test_plot, "r+b") as file:
        file.write(bytes(100))
    # Add it and validate it fails to load
    add_plot_directory(env.root_path, str(env.dir_1.path))
    expected_result.loaded = len(env.dir_1) - 1
    expected_result.removed = 0
    expected_result.processed = len(env.dir_1)
    expected_result.remaining = 0
    await run_refresh_test(env.plot_manager)
    assert len(env.plot_manager.failed_to_open_filenames) == 1
    assert retry_test_plot in env.plot_manager.failed_to_open_filenames
    # Make sure the file stays in `failed_to_open_filenames` and doesn't get loaded in the next refresh cycle
    expected_result.loaded = 0
    expected_result.processed = len(env.dir_1)
    await run_refresh_test(env.plot_manager)
    assert len(env.plot_manager.failed_to_open_filenames) == 1
    assert retry_test_plot in env.plot_manager.failed_to_open_filenames
    # Now decrease the re-try timeout, restore the valid plot file and make sure it properly loads now
    env.plot_manager.refresh_parameter.retry_invalid_seconds = 0
    move(retry_test_plot_save, retry_test_plot)
    expected_result.loaded = 1
    expected_result.processed = len(env.dir_1)
    await run_refresh_test(env.plot_manager)
    assert len(env.plot_manager.failed_to_open_filenames) == 0
    assert retry_test_plot not in env.plot_manager.failed_to_open_filenames
    env.plot_manager.stop_refreshing()


@pytest.mark.asyncio
async def test_plot_info_caching(test_environment):
    env: TestEnvironment = test_environment
    add_plot_directory(env.root_path, str(env.dir_1.path))
    expected_result.loaded = len(env.dir_1)
    expected_result.removed = 0
    expected_result.processed = len(env.dir_1)
    expected_result.remaining = 0
    await run_refresh_test(env.plot_manager)
    assert env.plot_manager.cache.path().exists()
    unlink(env.plot_manager.cache.path())
    # Should not write the cache again on shutdown because it didn't change
    assert not env.plot_manager.cache.path().exists()
    env.plot_manager.stop_refreshing()
    assert not env.plot_manager.cache.path().exists()
    # Manually trigger `save_cache` and make sure it creates a new cache file
    env.plot_manager.cache.save()
    assert env.plot_manager.cache.path().exists()
    expected_result.loaded = len(env.dir_1)
    expected_result.removed = 0
    expected_result.processed = len(env.dir_1)
    expected_result.remaining = 0
    plot_manager: PlotManager = PlotManager(env.root_path, refresh_callback)
    plot_manager.cache.load()
    assert len(plot_manager.cache) == len(plot_manager.cache)
    await run_refresh_test(plot_manager)
    for path, plot_info in plot_manager.plots.items():
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
    assert plot_manager.plot_filename_paths == plot_manager.plot_filename_paths
    assert plot_manager.failed_to_open_filenames == plot_manager.failed_to_open_filenames
    assert plot_manager.no_key_filenames == plot_manager.no_key_filenames
    plot_manager.stop_refreshing()
    # Modify the content of the plot_manager.dat
    with open(plot_manager.cache.path(), "r+b") as file:
        file.write(b"\xff\xff")  # Sets Cache.version to 65535
    # Make sure it just loads the plots normally if it fails to load the cache
    plot_manager = PlotManager(env.root_path, refresh_callback)
    plot_manager.cache.load()
    assert len(plot_manager.cache) == 0
    plot_manager.set_public_keys(bt.plot_manager.farmer_public_keys, bt.plot_manager.pool_public_keys)
    expected_result.loaded = len(env.dir_1)
    expected_result.removed = 0
    expected_result.processed = len(env.dir_1)
    expected_result.remaining = 0
    await run_refresh_test(plot_manager)
    assert len(plot_manager.plots) == len(plot_manager.plots)
    plot_manager.stop_refreshing()
