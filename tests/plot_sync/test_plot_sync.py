from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass, field, replace
from pathlib import Path
from shutil import copy
from typing import Any, Callable, List, Optional, Tuple

import pytest
import pytest_asyncio
from blspy import G1Element

from chia.farmer.farmer_api import Farmer
from chia.harvester.harvester_api import Harvester
from chia.plot_sync.delta import Delta, PathListDelta, PlotListDelta
from chia.plot_sync.receiver import Receiver
from chia.plot_sync.sender import Sender
from chia.plot_sync.util import Constants, State
from chia.plotting.manager import PlotManager
from chia.plotting.util import add_plot_directory, remove_plot_directory
from chia.protocols.harvester_protocol import Plot
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.start_service import Service
from chia.simulator.block_tools import BlockTools
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.config import create_default_chia_config, lock_and_load_config, save_config
from chia.util.ints import uint8, uint32, uint64
from chia.util.streamable import _T_Streamable
from tests.plot_sync.util import start_harvester_service
from tests.plotting.test_plot_manager import Directory, MockPlotInfo
from tests.plotting.util import get_test_plots


def synced(sender: Sender, receiver: Receiver, previous_last_sync_id: int) -> bool:
    return (
        sender._last_sync_id != previous_last_sync_id
        and sender._last_sync_id == receiver._last_sync.sync_id != 0
        and receiver.current_sync().state == State.idle
        and not sender.sync_active()
    )


def assert_path_list_matches(expected_list: List[str], actual_list: List[str]) -> None:
    assert len(expected_list) == len(actual_list)
    for item in expected_list:
        assert str(item) in actual_list


@dataclass
class ExpectedResult:
    valid_count: int = 0
    valid_delta: PlotListDelta = field(default_factory=PlotListDelta)
    invalid_count: int = 0
    invalid_delta: PathListDelta = field(default_factory=PathListDelta)
    keys_missing_count: int = 0
    keys_missing_delta: PathListDelta = field(default_factory=PathListDelta)
    duplicates_count: int = 0
    duplicates_delta: PathListDelta = field(default_factory=PathListDelta)
    callback_passed: bool = False

    def add_valid(self, list_plots: List[MockPlotInfo]) -> None:
        def create_mock_plot(info: MockPlotInfo) -> Plot:
            return Plot(
                info.prover.get_filename(),
                uint8(0),
                bytes32(b"\x00" * 32),
                None,
                None,
                G1Element(),
                uint64(0),
                uint64(0),
            )

        self.valid_count += len(list_plots)
        self.valid_delta.additions.update({x.prover.get_filename(): create_mock_plot(x) for x in list_plots})

    def remove_valid(self, list_paths: List[Path]) -> None:
        self.valid_count -= len(list_paths)
        self.valid_delta.removals += [str(x) for x in list_paths]

    def add_invalid(self, list_paths: List[Path]) -> None:
        self.invalid_count += len(list_paths)
        self.invalid_delta.additions += [str(x) for x in list_paths]

    def remove_invalid(self, list_paths: List[Path]) -> None:
        self.invalid_count -= len(list_paths)
        self.invalid_delta.removals += [str(x) for x in list_paths]

    def add_keys_missing(self, list_paths: List[Path]) -> None:
        self.keys_missing_count += len(list_paths)
        self.keys_missing_delta.additions += [str(x) for x in list_paths]

    def remove_keys_missing(self, list_paths: List[Path]) -> None:
        self.keys_missing_count -= len(list_paths)
        self.keys_missing_delta.removals += [str(x) for x in list_paths]

    def add_duplicates(self, list_paths: List[Path]) -> None:
        self.duplicates_count += len(list_paths)
        self.duplicates_delta.additions += [str(x) for x in list_paths]

    def remove_duplicates(self, list_paths: List[Path]) -> None:
        self.duplicates_count -= len(list_paths)
        self.duplicates_delta.removals += [str(x) for x in list_paths]


@dataclass
class Environment:
    root_path: Path
    harvester_services: List[Service[Harvester]]
    farmer_service: Service[Farmer]
    harvesters: List[Harvester]
    farmer: Farmer
    dir_1: Directory
    dir_2: Directory
    dir_3: Directory
    dir_4: Directory
    dir_invalid: Directory
    dir_keys_missing: Directory
    dir_duplicates: Directory
    expected: List[ExpectedResult]

    def get_harvester(self, peer_id: bytes32) -> Optional[Harvester]:
        for harvester in self.harvesters:
            assert harvester.server is not None
            if harvester.server.node_id == peer_id:
                return harvester
        return None

    def add_directory(self, harvester_index: int, directory: Directory, state: State = State.loaded) -> None:
        try:
            add_plot_directory(self.harvesters[harvester_index].root_path, str(directory.path))
        except ValueError:
            pass
        if state == State.loaded:
            self.expected[harvester_index].add_valid(directory.plot_info_list())
        elif state == State.invalid:
            self.expected[harvester_index].add_invalid(directory.path_list())
        elif state == State.keys_missing:
            self.expected[harvester_index].add_keys_missing(directory.path_list())
        elif state == State.duplicates:
            self.expected[harvester_index].add_duplicates(directory.path_list())
        else:
            assert False, "Invalid state"

    def remove_directory(self, harvester_index: int, directory: Directory, state: State = State.removed) -> None:
        remove_plot_directory(self.harvesters[harvester_index].root_path, str(directory.path))
        if state == State.removed:
            self.expected[harvester_index].remove_valid(directory.path_list())
        elif state == State.invalid:
            self.expected[harvester_index].remove_invalid(directory.path_list())
        elif state == State.keys_missing:
            self.expected[harvester_index].remove_keys_missing(directory.path_list())
        elif state == State.duplicates:
            self.expected[harvester_index].remove_duplicates(directory.path_list())
        else:
            assert False, "Invalid state"

    def add_all_directories(self, harvester_index: int) -> None:
        self.add_directory(harvester_index, self.dir_1)
        self.add_directory(harvester_index, self.dir_2)
        self.add_directory(harvester_index, self.dir_3)
        self.add_directory(harvester_index, self.dir_4)
        self.add_directory(harvester_index, self.dir_keys_missing, State.keys_missing)
        self.add_directory(harvester_index, self.dir_invalid, State.invalid)
        # Note: This does not add dir_duplicates since its important that the duplicated plots are loaded after the
        # the original ones.
        # self.add_directory(harvester_index, self.dir_duplicates, State.duplicates)

    def remove_all_directories(self, harvester_index: int) -> None:
        self.remove_directory(harvester_index, self.dir_1)
        self.remove_directory(harvester_index, self.dir_2)
        self.remove_directory(harvester_index, self.dir_3)
        self.remove_directory(harvester_index, self.dir_4)
        self.remove_directory(harvester_index, self.dir_keys_missing, State.keys_missing)
        self.remove_directory(harvester_index, self.dir_invalid, State.invalid)
        self.remove_directory(harvester_index, self.dir_duplicates, State.duplicates)

    async def plot_sync_callback(self, peer_id: bytes32, delta: Optional[Delta]) -> None:
        if delta is None:
            return
        harvester: Optional[Harvester] = self.get_harvester(peer_id)
        assert harvester is not None
        expected = self.expected[self.harvesters.index(harvester)]
        assert len(expected.valid_delta.additions) == len(delta.valid.additions)
        for path, plot_info in expected.valid_delta.additions.items():
            assert path in delta.valid.additions
            plot = harvester.plot_manager.plots.get(Path(path), None)
            assert plot is not None
            assert plot.prover.get_filename() == delta.valid.additions[path].filename
            assert plot.prover.get_size() == delta.valid.additions[path].size
            assert plot.prover.get_id() == delta.valid.additions[path].plot_id
            assert plot.pool_public_key == delta.valid.additions[path].pool_public_key
            assert plot.pool_contract_puzzle_hash == delta.valid.additions[path].pool_contract_puzzle_hash
            assert plot.plot_public_key == delta.valid.additions[path].plot_public_key
            assert plot.file_size == delta.valid.additions[path].file_size
            assert int(plot.time_modified) == delta.valid.additions[path].time_modified

        assert_path_list_matches(expected.valid_delta.removals, delta.valid.removals)
        assert_path_list_matches(expected.invalid_delta.additions, delta.invalid.additions)
        assert_path_list_matches(expected.invalid_delta.removals, delta.invalid.removals)
        assert_path_list_matches(expected.keys_missing_delta.additions, delta.keys_missing.additions)
        assert_path_list_matches(expected.keys_missing_delta.removals, delta.keys_missing.removals)
        assert_path_list_matches(expected.duplicates_delta.additions, delta.duplicates.additions)
        assert_path_list_matches(expected.duplicates_delta.removals, delta.duplicates.removals)
        expected.valid_delta.clear()
        expected.invalid_delta.clear()
        expected.keys_missing_delta.clear()
        expected.duplicates_delta.clear()
        expected.callback_passed = True

    async def run_sync_test(self) -> None:
        plot_manager: PlotManager
        assert len(self.harvesters) == len(self.expected)
        last_sync_ids: List[uint64] = []
        # Run the test in two steps, first trigger the refresh on both harvesters
        for harvester in self.harvesters:
            plot_manager = harvester.plot_manager
            assert harvester.server is not None
            receiver = self.farmer.plot_sync_receivers[harvester.server.node_id]
            # Make sure to reset the passed flag always before a new run
            self.expected[self.harvesters.index(harvester)].callback_passed = False
            receiver._update_callback = self.plot_sync_callback
            assert harvester.plot_sync_sender._last_sync_id == receiver._last_sync.sync_id
            last_sync_ids.append(harvester.plot_sync_sender._last_sync_id)
            plot_manager.start_refreshing()
            plot_manager.trigger_refresh()
        # Then wait for them to be synced with the farmer and validate them
        for harvester in self.harvesters:
            plot_manager = harvester.plot_manager
            assert harvester.server is not None
            receiver = self.farmer.plot_sync_receivers[harvester.server.node_id]
            await time_out_assert(20, plot_manager.needs_refresh, value=False)
            harvester_index = self.harvesters.index(harvester)
            await time_out_assert(
                10, synced, True, harvester.plot_sync_sender, receiver, last_sync_ids[harvester_index]
            )
            expected = self.expected[harvester_index]
            assert plot_manager.plot_count() == len(receiver.plots()) == expected.valid_count
            assert len(plot_manager.failed_to_open_filenames) == len(receiver.invalid()) == expected.invalid_count
            assert len(plot_manager.no_key_filenames) == len(receiver.keys_missing()) == expected.keys_missing_count
            assert len(plot_manager.get_duplicates()) == len(receiver.duplicates()) == expected.duplicates_count
            assert expected.callback_passed
            assert expected.valid_delta.empty()
            assert expected.invalid_delta.empty()
            assert expected.keys_missing_delta.empty()
            assert expected.duplicates_delta.empty()
            for path, plot_info in plot_manager.plots.items():
                assert str(path) in receiver.plots()
                assert plot_info.prover.get_filename() == receiver.plots()[str(path)].filename
                assert plot_info.prover.get_size() == receiver.plots()[str(path)].size
                assert plot_info.prover.get_id() == receiver.plots()[str(path)].plot_id
                assert plot_info.pool_public_key == receiver.plots()[str(path)].pool_public_key
                assert plot_info.pool_contract_puzzle_hash == receiver.plots()[str(path)].pool_contract_puzzle_hash
                assert plot_info.plot_public_key == receiver.plots()[str(path)].plot_public_key
                assert plot_info.file_size == receiver.plots()[str(path)].file_size
                assert int(plot_info.time_modified) == receiver.plots()[str(path)].time_modified
            for path in plot_manager.failed_to_open_filenames:
                assert str(path) in receiver.invalid()
            for path in plot_manager.no_key_filenames:
                assert str(path) in receiver.keys_missing()
            for path in plot_manager.get_duplicates():
                assert str(path) in receiver.duplicates()

    async def handshake_done(self, index: int) -> bool:
        return (
            self.harvesters[index].plot_manager._refresh_thread is not None
            and len(self.harvesters[index].plot_manager.farmer_public_keys) > 0
        )


@pytest_asyncio.fixture(scope="function")
async def environment(
    tmp_path: Path, farmer_two_harvester_not_started: Tuple[List[Service[Harvester]], Service[Farmer], BlockTools]
) -> Environment:
    def new_test_dir(name: str, plot_list: List[Path]) -> Directory:
        return Directory(tmp_path / "plots" / name, plot_list)

    plots: List[Path] = get_test_plots()
    plots_invalid: List[Path] = get_test_plots()[0:3]
    plots_keys_missing: List[Path] = get_test_plots("not_in_keychain")
    # Create 4 directories where: dir_n contains n plots
    directories: List[Directory] = []
    offset: int = 0
    while len(directories) < 4:
        dir_number = len(directories) + 1
        directories.append(new_test_dir(f"{dir_number}", plots[offset : offset + dir_number]))
        offset += dir_number

    dir_invalid: Directory = new_test_dir("invalid", plots_invalid)
    dir_keys_missing: Directory = new_test_dir("keys_missing", plots_keys_missing)
    dir_duplicates: Directory = new_test_dir("duplicates", directories[3].plots)
    create_default_chia_config(tmp_path)

    # Invalidate the plots in `dir_invalid`
    for path in dir_invalid.path_list():
        with open(path, "wb") as file:
            file.write(bytes(100))

    harvester_services, farmer_service, bt = farmer_two_harvester_not_started
    farmer: Farmer = farmer_service._node
    await farmer_service.start()
    harvesters: List[Harvester] = [
        await start_harvester_service(service, farmer_service) for service in harvester_services
    ]
    for harvester in harvesters:
        # Remove default plot directory for this tests
        with lock_and_load_config(harvester.root_path, "config.yaml") as config:
            config["harvester"]["plot_directories"] = []
            save_config(harvester.root_path, "config.yaml", config)
        harvester.plot_manager.set_public_keys(
            bt.plot_manager.farmer_public_keys.copy(), bt.plot_manager.pool_public_keys.copy()
        )

    assert len(farmer.plot_sync_receivers) == 2

    return Environment(
        tmp_path,
        harvester_services,
        farmer_service,
        harvesters,
        farmer,
        directories[0],
        directories[1],
        directories[2],
        directories[3],
        dir_invalid,
        dir_keys_missing,
        dir_duplicates,
        [ExpectedResult() for _ in harvesters],
    )


@pytest.mark.asyncio
async def test_sync_valid(environment: Environment) -> None:
    env: Environment = environment
    env.add_directory(0, env.dir_1)
    env.add_directory(1, env.dir_2)
    await env.run_sync_test()
    # Run again two times to make sure we still get the same results in repeated refresh intervals
    env.expected[0].valid_delta.clear()
    env.expected[1].valid_delta.clear()
    await env.run_sync_test()
    await env.run_sync_test()
    env.add_directory(0, env.dir_3)
    env.add_directory(1, env.dir_4)
    await env.run_sync_test()
    while len(env.dir_3.path_list()):
        drop_plot = env.dir_3.path_list()[0]
        drop_plot.unlink()
        env.dir_3.drop(drop_plot)
        env.expected[0].remove_valid([drop_plot])
        await env.run_sync_test()
    env.remove_directory(0, env.dir_3)
    await env.run_sync_test()
    env.remove_directory(1, env.dir_4)
    await env.run_sync_test()
    env.remove_directory(0, env.dir_1)
    env.remove_directory(1, env.dir_2)
    await env.run_sync_test()


@pytest.mark.asyncio
async def test_sync_invalid(environment: Environment) -> None:
    env: Environment = environment
    assert len(env.farmer.plot_sync_receivers) == 2
    # Use dir_3 and dir_4 in this test because the invalid plots are copies from dir_1 + dir_2
    env.add_directory(0, env.dir_3)
    env.add_directory(0, env.dir_invalid, State.invalid)
    env.add_directory(1, env.dir_4)
    await env.run_sync_test()
    # Run again two times to make sure we still get the same results in repeated refresh intervals
    await env.run_sync_test()
    await env.run_sync_test()
    # Drop all but two of the invalid plots
    assert len(env.dir_invalid) > 2
    for _ in range(len(env.dir_invalid) - 2):
        drop_plot = env.dir_invalid.path_list()[0]
        drop_plot.unlink()
        env.dir_invalid.drop(drop_plot)
        env.expected[0].remove_invalid([drop_plot])
        await env.run_sync_test()
    assert len(env.dir_invalid) == 2
    # Add the directory to the first harvester too
    env.add_directory(1, env.dir_invalid, State.invalid)
    await env.run_sync_test()
    # Recover one the remaining invalid plot
    for path in get_test_plots():
        if path.name == env.dir_invalid.path_list()[0].name:
            copy(path, env.dir_invalid.path)
    for i in range(len(env.harvesters)):
        env.expected[i].add_valid([env.dir_invalid.plot_info_list()[0]])
        env.expected[i].remove_invalid([env.dir_invalid.path_list()[0]])
        env.harvesters[i].plot_manager.refresh_parameter = replace(
            env.harvesters[i].plot_manager.refresh_parameter, retry_invalid_seconds=uint32(0)
        )
    await env.run_sync_test()
    for i in [0, 1]:
        remove_plot_directory(env.harvesters[i].root_path, str(env.dir_invalid.path))
        env.expected[i].remove_valid([env.dir_invalid.path_list()[0]])
        env.expected[i].remove_invalid([env.dir_invalid.path_list()[1]])
    await env.run_sync_test()


@pytest.mark.asyncio
async def test_sync_keys_missing(environment: Environment) -> None:
    env: Environment = environment
    env.add_directory(0, env.dir_1)
    env.add_directory(0, env.dir_keys_missing, State.keys_missing)
    env.add_directory(1, env.dir_2)
    await env.run_sync_test()
    # Run again two times to make sure we still get the same results in repeated refresh intervals
    await env.run_sync_test()
    await env.run_sync_test()
    # Drop all but 2 plots with missing keys and test sync inbetween
    assert len(env.dir_keys_missing) > 2
    for _ in range(len(env.dir_keys_missing) - 2):
        drop_plot = env.dir_keys_missing.path_list()[0]
        drop_plot.unlink()
        env.dir_keys_missing.drop(drop_plot)
        env.expected[0].remove_keys_missing([drop_plot])
        await env.run_sync_test()
    assert len(env.dir_keys_missing) == 2
    # Add the plots with missing keys to the other harvester
    env.add_directory(0, env.dir_3)
    env.add_directory(1, env.dir_keys_missing, State.keys_missing)
    await env.run_sync_test()
    # Add the missing keys to the first harvester's plot manager
    env.harvesters[0].plot_manager.farmer_public_keys.append(G1Element())
    env.harvesters[0].plot_manager.pool_public_keys.append(G1Element())
    # And validate they become valid now
    env.expected[0].add_valid(env.dir_keys_missing.plot_info_list())
    env.expected[0].remove_keys_missing(env.dir_keys_missing.path_list())
    await env.run_sync_test()
    # Drop the valid plots from one harvester and the keys missing plots from the other harvester
    env.remove_directory(0, env.dir_keys_missing)
    env.remove_directory(1, env.dir_keys_missing, State.keys_missing)
    await env.run_sync_test()


@pytest.mark.asyncio
async def test_sync_duplicates(environment: Environment) -> None:
    env: Environment = environment
    # dir_4 and then dir_duplicates contain the same plots. Load dir_4 first to make sure the plots seen as duplicates
    # are from dir_duplicates.
    env.add_directory(0, env.dir_4)
    await env.run_sync_test()
    env.add_directory(0, env.dir_duplicates, State.duplicates)
    env.add_directory(1, env.dir_2)
    await env.run_sync_test()
    # Run again two times to make sure we still get the same results in repeated refresh intervals
    await env.run_sync_test()
    await env.run_sync_test()
    # Drop all but 1 duplicates and test sync in-between
    assert len(env.dir_duplicates) > 2
    for _ in range(len(env.dir_duplicates) - 2):
        drop_plot = env.dir_duplicates.path_list()[0]
        drop_plot.unlink()
        env.dir_duplicates.drop(drop_plot)
        env.expected[0].remove_duplicates([drop_plot])
        await env.run_sync_test()
    assert len(env.dir_duplicates) == 2
    # Removing dir_4 now leads to the plots in dir_duplicates to become loaded instead
    env.remove_directory(0, env.dir_4)
    env.expected[0].remove_duplicates(env.dir_duplicates.path_list())
    env.expected[0].add_valid(env.dir_duplicates.plot_info_list())
    await env.run_sync_test()


async def add_and_validate_all_directories(env: Environment) -> None:
    # Add all available directories to both harvesters and make sure they load and get synced
    env.add_all_directories(0)
    env.add_all_directories(1)
    await env.run_sync_test()
    env.add_directory(0, env.dir_duplicates, State.duplicates)
    env.add_directory(1, env.dir_duplicates, State.duplicates)
    await env.run_sync_test()


async def remove_and_validate_all_directories(env: Environment) -> None:
    # Remove all available directories to both harvesters and make sure they are removed and get synced
    env.remove_all_directories(0)
    env.remove_all_directories(1)
    await env.run_sync_test()


@pytest.mark.asyncio
async def test_add_and_remove_all_directories(environment: Environment) -> None:
    await add_and_validate_all_directories(environment)
    await remove_and_validate_all_directories(environment)


@pytest.mark.asyncio
async def test_harvester_restart(environment: Environment) -> None:
    env: Environment = environment
    # Load all directories for both harvesters
    await add_and_validate_all_directories(env)
    # Stop the harvester and make sure the receiver gets dropped on the farmer and refreshing gets stopped
    env.harvester_services[0].stop()
    await env.harvester_services[0].wait_closed()
    assert len(env.farmer.plot_sync_receivers) == 1
    assert not env.harvesters[0].plot_manager._refreshing_enabled
    assert not env.harvesters[0].plot_manager.needs_refresh()
    # Start the harvester, wait for the handshake and make sure the receiver comes back
    await start_harvester_service(env.harvester_services[0], env.farmer_service)
    await time_out_assert(5, env.handshake_done, True, 0)
    assert len(env.farmer.plot_sync_receivers) == 2
    # Remove the duplicates dir to avoid conflicts with the original plots
    env.remove_directory(0, env.dir_duplicates)
    # Reset the expected data for harvester 0 and re-add all directories because of the restart
    env.expected[0] = ExpectedResult()
    env.add_all_directories(0)
    # Run the refresh two times and make sure everything recovers and stays recovered after harvester restart
    await env.run_sync_test()
    env.add_directory(0, env.dir_duplicates, State.duplicates)
    await env.run_sync_test()


@pytest.mark.asyncio
async def test_farmer_restart(environment: Environment) -> None:
    env: Environment = environment
    # Load all directories for both harvesters
    await add_and_validate_all_directories(env)
    last_sync_ids: List[uint64] = []
    for i in range(0, len(env.harvesters)):
        last_sync_ids.append(env.harvesters[i].plot_sync_sender._last_sync_id)
    # Stop the farmer and make sure both receivers get dropped and refreshing gets stopped on the harvesters
    env.farmer_service.stop()
    await env.farmer_service.wait_closed()
    assert len(env.farmer.plot_sync_receivers) == 0
    assert not env.harvesters[0].plot_manager._refreshing_enabled
    assert not env.harvesters[1].plot_manager._refreshing_enabled
    # Start the farmer, wait for the handshake and make sure the receivers come back
    await env.farmer_service.start()
    await time_out_assert(5, env.handshake_done, True, 0)
    await time_out_assert(5, env.handshake_done, True, 1)
    assert len(env.farmer.plot_sync_receivers) == 2
    # Do not use run_sync_test here, to have a more realistic test scenario just wait for the harvesters to be synced.
    # The handshake should trigger re-sync.
    for i in range(0, len(env.harvesters)):
        harvester: Harvester = env.harvesters[i]
        assert harvester.server is not None
        receiver = env.farmer.plot_sync_receivers[harvester.server.node_id]
        await time_out_assert(20, synced, True, harvester.plot_sync_sender, receiver, last_sync_ids[i])
    # Validate the sync
    for harvester in env.harvesters:
        plot_manager: PlotManager = harvester.plot_manager
        assert harvester.server is not None
        receiver = env.farmer.plot_sync_receivers[harvester.server.node_id]
        expected = env.expected[env.harvesters.index(harvester)]
        assert plot_manager.plot_count() == len(receiver.plots()) == expected.valid_count
        assert len(plot_manager.failed_to_open_filenames) == len(receiver.invalid()) == expected.invalid_count
        assert len(plot_manager.no_key_filenames) == len(receiver.keys_missing()) == expected.keys_missing_count
        assert len(plot_manager.get_duplicates()) == len(receiver.duplicates()) == expected.duplicates_count


@pytest.mark.asyncio
async def test_sync_start_and_disconnect_while_sync_is_active(
    farmer_one_harvester: Tuple[List[Service[Harvester]], Service[Farmer], BlockTools]
) -> None:
    harvesters, farmer_service, _ = farmer_one_harvester
    harvester_service = harvesters[0]
    harvester = harvester_service._node
    farmer: Farmer = farmer_service._node
    Constants.message_timeout = 3

    async def receiver_available() -> bool:
        return harvester.server.node_id in farmer.plot_sync_receivers

    async def disconnecting_process(
        self: Receiver, method: Callable[[_T_Streamable], Any], message_type: ProtocolMessageTypes, message: Any
    ) -> None:
        if self.current_sync().state == State.loaded:
            harvester.plot_manager.trigger_refresh()
            await asyncio.sleep(2)
            await self.connection().close()
            return
        await original_process(method, message_type, message)

    # Wait for the receiver to show up
    await time_out_assert(20, receiver_available)
    receiver = farmer.plot_sync_receivers[harvester.server.node_id]
    # And wait until the first sync from the harvester to the farmer is done
    await time_out_assert(20, receiver.initial_sync, False)
    # Replace the `Receiver._process` with `disconnecting_process` which triggers a plot manager refresh and disconnects
    # the farmer from the harvester during an active sync.
    original_process = receiver._process
    receiver._process = functools.partial(disconnecting_process, receiver)  # type: ignore[assignment]
    # Trigger the refresh which leads to a new sync_start being triggered during the active sync.
    harvester.plot_manager.trigger_refresh()
    await time_out_assert(20, harvester.plot_sync_sender.sync_active)
    # Now wait until the receiver disappears from the farmer's plot_sync_receivers which means its disconnected.
    await time_out_assert(20, receiver_available, False)
    # Wait until the sync was aborted
    await time_out_assert(20, harvester.plot_sync_sender.sync_active, False)
    # And then wait for the harvester to reconnect and the receiver to re-appear.
    await time_out_assert(20, receiver_available, True)
    # Make sure the receiver object has been changed because of the disconnect
    assert farmer.plot_sync_receivers[harvester.server.node_id] is not receiver
    receiver = farmer.plot_sync_receivers[harvester.server.node_id]
    current_last_sync_id = receiver.last_sync().sync_id
    # Now start another sync and wait for it to be done to make sure everything still works fine
    harvester.plot_manager.trigger_refresh()
    await time_out_assert(20, synced, True, harvester.plot_sync_sender, receiver, current_last_sync_id)
