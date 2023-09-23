# flake8: noqa: E501
from __future__ import annotations

from blspy import AugSchemeMPL, PrivateKey

from chia.pools.pool_config import PoolWalletConfig
from chia.util.config import create_default_chia_config, load_config, lock_config, save_config


def test_pool_config(tmp_path):
    test_root = tmp_path
    test_path = test_root / "config"
    eg_config = test_path / "config.yaml"
    to_config = test_path / "test_pool_config.yaml"

    create_default_chia_config(test_root, ["config.yaml"])
    assert eg_config.exists()
    eg_config.rename(to_config)
    config = load_config(test_root, "test_pool_config.yaml")

    auth_sk: PrivateKey = AugSchemeMPL.key_gen(b"1" * 32)
    d = {
        "owner_public_key": "84c3fcf9d5581c1ddc702cb0f3b4a06043303b334dd993ab42b2c320ebfa98e5ce558448615b3f69638ba92cf7f43da5",
        "p2_singleton_puzzle_hash": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        "payout_instructions": "c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8",
        "pool_url": "localhost",
        "launcher_id": "ae4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791afa",
        "target_puzzle_hash": "344587cf06a39db471d2cc027504e8688a0a67cce961253500c956c73603fd58",
    }

    pwc = PoolWalletConfig.from_json_dict(d)

    config_a = config.copy()
    config_b = config.copy()

    config_a["wallet"]["pool_list"] = [d]
    config_b["wallet"]["pool_list"] = [pwc.to_json_dict()]

    print(config["wallet"]["pool_list"])
    with lock_config(test_root, "test_pool_config_a.yaml"):
        save_config(test_root, "test_pool_config_a.yaml", config_a)
    with lock_config(test_root, "test_pool_config_b.yaml"):
        save_config(test_root, "test_pool_config_b.yaml", config_b)
    assert config_a == config_b
