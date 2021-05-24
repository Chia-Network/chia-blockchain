from dataclasses import dataclass
from typing import Dict
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48, bytes96
"""
Config example
pool_list:
  - owner_public_key: b6509da7ddb76adacdffd9c93145a585f07e8976d9d5b1f575d82fdafda2e2f0dd66fa22589ca344d95ee9d44cf51c74
    pool_puzzle_hash: 2e4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791af9
    pool_url: https://pool.example.org:5555/config.json
    singleton_genesis: ae4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791afa
    target: c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8
    target_signature: 95ae82302134489d68cf0890356fc2d360c3bda9c9f15a3111a6a776df073a2fc6194896f3196a10fba18bb9de8e4fae0caf08e49fe32786d35fe0538daf0ceb6f7ace9477440b9978589bcaa28690dded6e5a296b47bffe2db97c1c28c9d13c
""" # noqa

@dataclass(frozen=True)
class PoolWalletConfig:
    owner_public_key: bytes48
    pool_puzzle_hash: bytes32  # Duplicate of target_address?
    pool_url: str
    singleton_genesis: bytes32
    target_address: bytes32 # 1/8 block reward address?
    target_signature: bytes96

def pool_wallet_config_to_dict(p: PoolWalletConfig) -> Dict:
    return {
        "owner_public_key": p.owner_public_key.hex(),
        "pool_puzzle_hash": p.pool_puzzle_hash.hex(),
        "pool_url": p.pool_url,
        "singleton_genesis": p.singleton_genesis.hex(),
        "target_address": p.target_address.hex(),
        "target_signature": p.target_signature.hex()
    }
