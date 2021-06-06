# flake8: noqa: E501
from pathlib import Path

from blspy import AugSchemeMPL, PrivateKey

from chia.pools.pool_config import PoolWalletConfig
from chia.util.config import load_config, save_config, create_default_chia_config


def test_pool_config():
    test_root = Path("/tmp")
    test_path = Path("/tmp/config")
    eg_config = test_path / "config.yaml"
    to_config = test_path / "test_pool_config.yaml"

    create_default_chia_config(test_root, ["config.yaml"])
    assert eg_config.exists()
    eg_config.rename(to_config)
    config = load_config(test_root, "test_pool_config.yaml")

    auth_sk: PrivateKey = AugSchemeMPL.key_gen(b"1" * 32)
    d = {
        "authentication_key_info_signature": "8fa411d3164d6d4fc1a5985ea474a853304fec99b93300e12e3b3e8fc16dea8834804eb3dfcee7181a59cd4e969ada0e119d7c8cc94f5c912280dc4cfdbadd9076b6393b135e35b182bcd4e13bf9216877a6033dd9f89c249981e83908c5a926",
        "authentication_public_key": bytes(auth_sk.get_g1()).hex(),
        "authentication_public_key_timestamp": 1621854388,
        "owner_public_key": "84c3fcf9d5581c1ddc702cb0f3b4a06043303b334dd993ab42b2c320ebfa98e5ce558448615b3f69638ba92cf7f43da5",
        "pool_payout_instructions": "c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8",
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
    save_config(test_root, "test_pool_config_a.yaml", config_a)
    save_config(test_root, "test_pool_config_b.yaml", config_b)
    assert config_a == config_b
