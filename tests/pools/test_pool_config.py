from pathlib import Path

from chia.pools.pool_config import PoolWalletConfig, pool_wallet_config_to_dict
from chia.util.byte_types import hexstr_to_bytes
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

    d = {
        "owner_public_key": "b6509da7ddb76adacdffd9c93145a585f07e8976d9d5b1f575d82fdafda2e2f0dd66fa22589ca344d95ee9d44cf51c74",
        "pool_puzzle_hash": "2e4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791af9",
        "pool_url": "https://pool.example.org:5555/config.json",
        "singleton_genesis": "ae4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791afa",
        "target": "c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8",
        "target_signature": "95ae82302134489d68cf0890356fc2d360c3bda9c9f15a3111a6a776df073a2fc6194896f3196a10fba18bb9de8e4fae0caf08e49fe32786d35fe0538daf0ceb6f7ace9477440b9978589bcaa28690dded6e5a296b47bffe2db97c1c28c9d13c"
    }

    pwc = PoolWalletConfig(
        hexstr_to_bytes(d["owner_public_key"]),
        hexstr_to_bytes(d["pool_puzzle_hash"]),
        d["pool_url"],
        hexstr_to_bytes(d["singleton_genesis"]),
        hexstr_to_bytes(d["target"]),
        hexstr_to_bytes(d["target_signature"]),
    )

    config_a = config.copy()
    config_b = config.copy()

    config_a["wallet"]["pool_list"] = [d]
    config_b["wallet"]["pool_list"] = [pool_wallet_config_to_dict(pwc)]

    print(config["wallet"]["pool_list"])
    save_config(test_root, "test_pool_config_a.yaml", config_a)
    save_config(test_root, "test_pool_config_b.yaml", config_b)
    assert config_a == config_b
