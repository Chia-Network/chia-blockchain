from __future__ import annotations

import asyncio
import copy
import random
import shutil
import tempfile
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Pool, Queue, TimeoutError
from pathlib import Path
from threading import Thread
from time import sleep
from typing import Any, Dict, Optional

import pytest
import yaml

from chia.util.config import (
    config_path_for_filename,
    create_default_chia_config,
    initial_config_file,
    load_config,
    lock_and_load_config,
    lock_config,
    save_config,
    selected_network_address_prefix,
)
from chia.util.timing import adjusted_timeout

# Commented-out lines are preserved to aid in debugging the multiprocessing tests
# import logging
# import os
# import threading

# log = logging.getLogger(__name__)


def write_config(
    root_path: Path,
    config: Dict,
    atomic_write: bool,
    do_sleep: bool,
    iterations: int,
    error_queue: Optional[Queue] = None,
):
    """
    Wait for a random amount of time and write out the config data. With a large
    config, we expect save_config() to require multiple writes.
    """
    try:
        for i in range(iterations):
            # This is a small sleep to get interweaving reads and writes
            sleep(0.05)

            if do_sleep:
                sleep(random.random())
            if atomic_write:
                # Note that this is usually atomic but in certain circumstances in Windows it can copy the file,
                # leading to a non-atomic operation.
                with lock_config(root_path, "config.yaml"):
                    save_config(root_path=root_path, filename="config.yaml", config_data=config)
            else:
                path: Path = config_path_for_filename(root_path, filename="config.yaml")
                with lock_config(root_path, "config.yaml"):
                    with tempfile.TemporaryDirectory(dir=path.parent) as tmp_dir:
                        tmp_path: Path = Path(tmp_dir) / Path("config.yaml")
                        with open(tmp_path, "w") as f:
                            yaml.safe_dump(config, f)
                        shutil.copy2(str(tmp_path), str(path))
    except Exception as e:
        if error_queue is not None:
            error_queue.put(e)
        raise


def read_and_compare_config(
    root_path: Path, default_config: Dict, do_sleep: bool, iterations: int, error_queue: Optional[Queue] = None
):
    """
    Wait for a random amount of time, read the config and compare with the
    default config data. If the config file is partially-written or corrupt,
    load_config should fail or return bad data
    """
    try:
        for i in range(iterations):
            # This is a small sleep to get interweaving reads and writes
            sleep(0.05)

            # Wait a moment. The read and write threads are delayed by a random amount
            # in an attempt to interleave their execution.
            if do_sleep:
                sleep(random.random())

            with lock_and_load_config(root_path, "config.yaml") as config:
                assert config == default_config
    except Exception as e:
        if error_queue is not None:
            error_queue.put(e)
        raise


async def create_reader_and_writer_tasks(root_path: Path, default_config: Dict):
    """
    Spin-off reader and writer threads and wait for completion
    """
    error_queue: Queue = Queue()
    thread1 = Thread(
        target=write_config,
        kwargs={
            "root_path": root_path,
            "config": default_config,
            "atomic_write": False,
            "do_sleep": True,
            "iterations": 1,
            "error_queue": error_queue,
        },
    )
    thread2 = Thread(
        target=read_and_compare_config,
        kwargs={
            "root_path": root_path,
            "default_config": default_config,
            "do_sleep": True,
            "iterations": 1,
            "error_queue": error_queue,
        },
    )

    thread1.start()
    thread2.start()

    thread1.join()
    thread2.join()
    if not error_queue.empty():
        raise error_queue.get()


def run_reader_and_writer_tasks(root_path: Path, default_config: Dict):
    """
    Subprocess entry point. This function spins-off threads to perform read/write tasks
    concurrently, possibly leading to synchronization issues accessing config data.
    """
    asyncio.run(create_reader_and_writer_tasks(root_path, default_config))


@pytest.fixture(scope="function")
def default_config_dict() -> Dict:
    """
    Returns a dictionary containing the default config.yaml contents
    """
    content: str = initial_config_file("config.yaml")
    config: Dict = yaml.safe_load(content)
    return config


class TestConfig:
    def test_create_config_new(self, tmpdir):
        """
        Test create_default_chia_config() as in a first run scenario
        """
        # When: using a clean directory
        root_path: Path = Path(tmpdir)
        config_file_path: Path = root_path / "config" / "config.yaml"
        # Expect: config.yaml doesn't exist
        assert config_file_path.exists() is False
        # When: creating a new config
        create_default_chia_config(root_path)
        # Expect: config.yaml exists
        assert config_file_path.exists() is True

        expected_content: str = initial_config_file("config.yaml")
        assert len(expected_content) > 0

        with open(config_file_path) as f:
            actual_content: str = f.read()
            # Expect: config.yaml contents are seeded with initial contents
            assert actual_content == expected_content

    def test_create_config_overwrite(self, tmpdir):
        """
        Test create_default_chia_config() when overwriting an existing config.yaml
        """
        # When: using a clean directory
        root_path: Path = Path(tmpdir)
        config_file_path: Path = root_path / "config" / "config.yaml"
        config_file_path.parent.mkdir(parents=True, exist_ok=True)
        # When: config.yaml already exists with content
        with open(config_file_path, "w") as f:
            f.write("Some config content")
        # Expect: config.yaml exists
        assert config_file_path.exists() is True
        # When: creating a new config
        create_default_chia_config(root_path)
        # Expect: config.yaml exists
        assert config_file_path.exists() is True

        expected_content: str = initial_config_file("config.yaml")
        assert len(expected_content) > 0

        with open(config_file_path) as f:
            actual_content: str = f.read()
            # Expect: config.yaml contents are overwritten with initial contents
            assert actual_content == expected_content

    def test_load_config(self, root_path_populated_with_config, default_config_dict):
        """
        Call load_config() with a default config and verify a few values are set to the expected values
        """
        root_path: Path = root_path_populated_with_config
        # When: loading a newly created config
        config: Dict = load_config(root_path=root_path, filename="config.yaml")
        assert config is not None
        # Expect: config values should match the defaults (from a small sampling)
        assert config["daemon_port"] == default_config_dict["daemon_port"] == 55400
        assert config["self_hostname"] == default_config_dict["self_hostname"] == "localhost"
        assert (
            config["farmer"]["network_overrides"]["constants"]["mainnet"]["GENESIS_CHALLENGE"]
            == default_config_dict["farmer"]["network_overrides"]["constants"]["mainnet"]["GENESIS_CHALLENGE"]
            == "ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb"
        )

    def test_load_config_exit_on_error(self, tmp_path: Path):
        """
        Call load_config() with an invalid path. Behavior should be dependent on the exit_on_error flag.
        """
        root_path = tmp_path
        config_file_path: Path = root_path / "config" / "config.yaml"
        # When: config file path points to a directory
        config_file_path.mkdir(parents=True, exist_ok=True)
        # When: exit_on_error is True
        # Expect: load_config will exit
        with pytest.raises(SystemExit):
            _ = load_config(root_path=root_path, filename=config_file_path, exit_on_error=True)
        # When: exit_on_error is False
        # Expect: load_config will raise an exception
        with pytest.raises(ValueError):
            _ = load_config(root_path=root_path, filename=config_file_path, exit_on_error=False)

    def test_save_config(self, root_path_populated_with_config, default_config_dict):
        """
        Test modifying the config and saving it to disk. The modified value(s) should be present after
        calling load_config().
        """
        root_path: Path = root_path_populated_with_config
        config: Dict = copy.deepcopy(default_config_dict)
        # When: modifying the config
        config["harvester"]["farmer_peers"][0]["host"] = "oldmacdonald.eie.io"
        # Sanity check that we didn't modify the default config
        assert (
            config["harvester"]["farmer_peers"][0]["host"]
            != default_config_dict["harvester"]["farmer_peers"][0]["host"]
        )
        # When: saving the modified config
        with lock_config(root_path, "config.yaml"):
            save_config(root_path=root_path, filename="config.yaml", config_data=config)

        # Expect: modifications should be preserved in the config read from disk
        loaded: Dict = load_config(root_path=root_path, filename="config.yaml")
        assert loaded["harvester"]["farmer_peers"][0]["host"] == "oldmacdonald.eie.io"

    def test_multiple_writers(self, root_path_populated_with_config, default_config_dict):
        """
        Test whether multiple readers/writers encounter data corruption. When using non-atomic operations
        to write to the config, partial/incomplete writes can cause readers to yield bad/corrupt data.
        """
        # Artifically inflate the size of the default config. This is done to (hopefully) force
        # save_config() to require multiple writes. When save_config() was using shutil.move()
        # multiple writes were observed, leading to read failures when data was partially written.
        default_config_dict["xyz"] = "x" * 32768
        root_path: Path = root_path_populated_with_config
        with lock_config(root_path, "config.yaml"):
            save_config(root_path=root_path, filename="config.yaml", config_data=default_config_dict)
        num_workers: int = 30
        args = list(map(lambda _: (root_path, default_config_dict), range(num_workers)))
        # Spin-off several processes (not threads) to read and write config data. If any
        # read failures are detected, the failing process will assert.
        with Pool(processes=num_workers) as pool:
            res = pool.starmap_async(run_reader_and_writer_tasks, args)
            try:
                res.get(timeout=adjusted_timeout(timeout=60))
            except TimeoutError:
                pytest.skip("Timed out waiting for reader/writer processes to complete")

    @pytest.mark.anyio
    async def test_non_atomic_writes(self, root_path_populated_with_config, default_config_dict):
        """
        Test whether one continuous writer (writing constantly, but not atomically) will interfere with many
        concurrent readers.
        """

        default_config_dict["xyz"] = "x" * 32768
        root_path: Path = root_path_populated_with_config
        with lock_config(root_path, "config.yaml"):
            save_config(root_path=root_path, filename="config.yaml", config_data=default_config_dict)

        with ProcessPoolExecutor(max_workers=4) as pool:
            all_tasks = []
            for i in range(10):
                all_tasks.append(
                    asyncio.get_running_loop().run_in_executor(
                        pool, read_and_compare_config, root_path, default_config_dict, False, 100, None
                    )
                )
                if i % 2 == 0:
                    all_tasks.append(
                        asyncio.get_running_loop().run_in_executor(
                            pool, write_config, root_path, default_config_dict, False, False, 100, None
                        )
                    )
            await asyncio.gather(*all_tasks)

    @pytest.mark.parametrize("prefix", [None])
    def test_selected_network_address_prefix_default_config(self, config_with_address_prefix: Dict[str, Any]) -> None:
        """
        Temp config.yaml created using a default config. address_prefix is defaulted to "xch"
        """
        config = config_with_address_prefix
        prefix = selected_network_address_prefix(config)
        assert prefix == "xch"

    @pytest.mark.parametrize("prefix", ["txch"])
    def test_selected_network_address_prefix_testnet_config(self, config_with_address_prefix: Dict[str, Any]) -> None:
        """
        Temp config.yaml created using a modified config. address_prefix is set to "txch"
        """
        config = config_with_address_prefix
        prefix = selected_network_address_prefix(config)
        assert prefix == "txch"

    def test_selected_network_address_prefix_config_dict(self, default_config_dict: Dict[str, Any]) -> None:
        """
        Modified config dictionary has address_prefix set to "customxch"
        """
        config = default_config_dict
        config["network_overrides"]["config"][config["selected_network"]]["address_prefix"] = "customxch"
        prefix = selected_network_address_prefix(config)
        assert prefix == "customxch"
