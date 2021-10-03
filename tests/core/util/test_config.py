import asyncio
import copy
import pytest
import random
import yaml

from chia.util.config import create_default_chia_config, initial_config_file, load_config, save_config
from chia.util.path import mkdir
from multiprocessing import Pool
from pathlib import Path
from threading import Thread
from time import sleep
from typing import Dict

# Commented-out lines are preserved to aide in debugging the multiprocessing tests
# import logging
# import os
# import threading

# log = logging.getLogger(__name__)


def write_config(root_path: Path, config: Dict):
    """
    Wait for a random amount of time and write out the config data. With a large
    config, we expect save_config() to require multiple writes.
    """
    sleep(random.random())
    # log.warning(f"[pid:{os.getpid()}:{threading.get_ident()}] write_config")
    # save_config(root_path=root_path, filename="config.yaml", config_data=modified_config)
    save_config(root_path=root_path, filename="config.yaml", config_data=config)


def read_and_compare_config(root_path: Path, default_config: Dict):
    """
    Wait for a random amount of time, read the config and compare with the
    default config data. If the config file is partially-written or corrupt,
    load_config should fail or return bad data
    """
    # Wait a moment. The read and write threads are delayed by a random amount
    # in an attempt to interleave their execution.
    sleep(random.random())
    # log.warning(f"[pid:{os.getpid()}:{threading.get_ident()}] read_and_compare_config")
    config: Dict = load_config(root_path=root_path, filename="config.yaml")
    assert len(config) > 0
    # if config != default_config:
    #     log.error(f"[pid:{os.getpid()}:{threading.get_ident()}] bad config: {config}")
    #     log.error(f"[pid:{os.getpid()}:{threading.get_ident()}] default config: {default_config}")
    assert config == default_config


async def create_reader_and_writer_tasks(root_path: Path, default_config: Dict):
    """
    Spin-off reader and writer threads and wait for completion
    """
    thread1 = Thread(target=write_config, kwargs={"root_path": root_path, "config": default_config})
    thread2 = Thread(target=read_and_compare_config, kwargs={"root_path": root_path, "default_config": default_config})

    thread1.start()
    thread2.start()

    thread1.join()
    thread2.join()


def run_reader_and_writer_tasks(root_path: Path, default_config: Dict):
    """
    Subprocess entry point. This function spins-off threads to perform read/write tasks
    concurrently, possibly leading to synchronization issues accessing config data.
    """
    asyncio.get_event_loop().run_until_complete(create_reader_and_writer_tasks(root_path, default_config))


class TestConfig:
    @pytest.fixture(scope="function")
    def root_path_populated_with_config(self, tmpdir) -> Path:
        """
        Create a temp directory and populate it with a default config.yaml.
        Returns the root path containing the config.
        """
        root_path: Path = Path(tmpdir)
        create_default_chia_config(root_path)
        return Path(root_path)

    @pytest.fixture(scope="function")
    def default_config_dict(self) -> Dict:
        """
        Returns a dictionary containing the default config.yaml contents
        """
        content: str = initial_config_file("config.yaml")
        config: Dict = yaml.safe_load(content)
        return config

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

        with open(config_file_path, "r") as f:
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
        mkdir(config_file_path.parent)
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

        with open(config_file_path, "r") as f:
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

    def test_load_config_exit_on_error(self, tmpdir):
        """
        Call load_config() with an invalid path. Behavior should be dependent on the exit_on_error flag.
        """
        root_path: Path = tmpdir
        config_file_path: Path = root_path / "config" / "config.yaml"
        # When: config file path points to a directory
        mkdir(config_file_path)
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
        config["harvester"]["farmer_peer"]["host"] = "oldmacdonald.eie.io"
        # Sanity check that we didn't modify the default config
        assert config["harvester"]["farmer_peer"]["host"] != default_config_dict["harvester"]["farmer_peer"]["host"]
        # When: saving the modified config
        save_config(root_path=root_path, filename="config.yaml", config_data=config)

        # Expect: modifications should be preserved in the config read from disk
        loaded: Dict = load_config(root_path=root_path, filename="config.yaml")
        assert loaded["harvester"]["farmer_peer"]["host"] == "oldmacdonald.eie.io"

    def test_multiple_writers(self, root_path_populated_with_config, default_config_dict):
        """
        Test whether multiple readers/writers encounter data corruption. When using non-atomic operations
        to write to the config, partial/incomplete writes can cause readers to yield bad/corrupt data.
        Access to config.yaml isn't currently synchronized, so the best we can currently hope for is that
        the file contents are written-to as a whole.
        """
        # Artifically inflate the size of the default config. This is done to (hopefully) force
        # save_config() to require multiple writes. When save_config() was using shutil.move()
        # multiple writes were observed, leading to read failures when data was partially written.
        default_config_dict["xyz"] = "x" * 32768
        root_path: Path = root_path_populated_with_config
        save_config(root_path=root_path, filename="config.yaml", config_data=default_config_dict)
        num_workers: int = 30
        args = list(map(lambda _: (root_path, default_config_dict), range(num_workers)))
        # Spin-off several processes (not threads) to read and write config data. If any
        # read failures are detected, the failing process will assert.
        with Pool(processes=num_workers) as pool:
            res = pool.starmap_async(run_reader_and_writer_tasks, args)
            res.get(timeout=10)
