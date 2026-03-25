from __future__ import annotations

import re
from pathlib import Path

import pytest
from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32

from chia.pools.pool_config import PoolingShareState, perform_migration_from_old_config
from chia.util.config import create_default_chia_config, load_config, save_config


def test_pool_config(tmp_path: Path) -> None:
    test_root = tmp_path

    p2_singleton_puzzle_hash = bytes32.from_hexstr("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")
    initial_share_state = PoolingShareState(
        p2_singleton_puzzle_hash=p2_singleton_puzzle_hash,
        launcher_id=bytes32.zeros,
        pool_url="localhost",
        payout_instructions="c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8",
        target_puzzle_hash=bytes32.from_hexstr("344587cf06a39db471d2cc027504e8688a0a67cce961253500c956c73603fd58"),
        owner_public_key=G1Element.from_bytes(
            bytes.fromhex(
                "84c3fcf9d5581c1ddc702cb0f3b4a06043303b334dd993ab42b2c320ebfa98e5ce558448615b3f69638ba92cf7f43da5"
            )
        ),
    )
    initial_share_state.add(root_path=test_root)
    with pytest.raises(ValueError, match=re.escape("Can only call .add() for new singleton entries")):
        initial_share_state.add(root_path=test_root)

    assert PoolingShareState.get_all_p2_singleton_puzzle_hashes(root_path=test_root) == [p2_singleton_puzzle_hash]
    with PoolingShareState.acquire(
        root_path=test_root, p2_singleton_puzzle_hash=p2_singleton_puzzle_hash
    ) as pool_config:
        pool_config.payout_instructions = "foo"
    with PoolingShareState.acquire(
        root_path=test_root, p2_singleton_puzzle_hash=p2_singleton_puzzle_hash
    ) as pool_config:
        assert pool_config.payout_instructions == "foo"
    with pytest.raises(ValueError, match=f"Attempting to load non-existent pooling state for {bytes32.zeros.hex()}"):
        with PoolingShareState.acquire(root_path=test_root, p2_singleton_puzzle_hash=bytes32.zeros):
            pass


def test_migration(tmp_path: Path) -> None:
    test_root = tmp_path
    create_default_chia_config(test_root, ["config.yaml"])
    config = load_config(test_root, "config.yaml")
    config["pool"]["pool_list"] = [
        {
            "owner_public_key": (
                "84c3fcf9d5581c1ddc702cb0f3b4a06043303b334dd993ab42b2c320ebfa98e5ce558448615b3f69638ba92cf7f43da5"
            ),
            "p2_singleton_puzzle_hash": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            "payout_instructions": "c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8",
            "pool_url": "localhost",
            "launcher_id": "ae4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791afa",
            "target_puzzle_hash": "344587cf06a39db471d2cc027504e8688a0a67cce961253500c956c73603fd58",
        }
    ]
    save_config(
        test_root,
        "config.yaml",
        config,
    )
    perform_migration_from_old_config(root_path=test_root)
    assert PoolingShareState.get_all_p2_singleton_puzzle_hashes(root_path=test_root) == [
        bytes32.from_hexstr("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")
    ]
    assert load_config(test_root, "config.yaml")["pool"]["pool_list"] == []
