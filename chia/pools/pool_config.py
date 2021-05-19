from dataclasses import dataclass
from typing import Dict
from chia.types.blockchain_format.sized_bytes import bytes32, bytes48, bytes96

"""
Config example
pool_list:
  - owner_public_key: b6509da7ddb76adacdffd9c93145a585f07e8976d9d5b1f575d82fdafda2e2f0dd66fa22589ca344d95ee9d44cf51c74
    target_puzzle_hash: 2e4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791af9
    pool_url: https://pool.example.org:5555/config.json
    singleton_genesis: ae4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791afa
    pool_payout_instructions: c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8
    pool_payout_instructions_signature: 95ae82302134489d68cf0890356fc2d360c3bda9c9f15a3111a6a776df073a2fc6194896f3196a10fba18bb9de8e4fae0caf08e49fe32786d35fe0538daf0ceb6f7ace9477440b9978589bcaa28690dded6e5a296b47bffe2db97c1c28c9d13c
"""  # noqa


@dataclass(frozen=True)
class PoolWalletConfig:
    """
    `owner_public_key` is a public key from the user's Chia wallet
    `target_puzzle_hash` is the Chia address that the Pooling smart contract will
    pay to when it farms a block reward. This is address is set in the inner layer of
    the pooling singleton when the user joins the pool. When pooling, this address belongs
    to the pool, and is received via `pool_url`. When self-pooling, it is a user address.
    `pool_url` is a URL that the farmer uses to download pooling configuration information.
    `pool_url` can be updated dynamically, and the data returned is not signed.
    `pool_url` should be HTTPS only.
    `singleton_genesis` uniquely identifies the set of plots plotted to the singleton_genesis ID,
    and the pooling smart coin. The genesis is the coin_id of the first incarnation of the singleton
    `pool_payout_instructions` is information the pool uses to pay the pool member. For example, a
    Chia or Bitcoin address.
    `pool_payout_instructions_signature` - a signature of pool_payout_instructions, signed
    by the private key associated with `owner_public_key`. It is used to prove that the
    entity that controls the plots has authorized the pool payout address.
    """

    owner_public_key: bytes48
    target_puzzle_hash: bytes32
    pool_url: str
    singleton_genesis: bytes32
    pool_payout_instructions: bytes32
    pool_payout_instructions_signature: bytes96


def pool_wallet_config_to_dict(p: PoolWalletConfig) -> Dict:
    return {
        "owner_public_key": p.owner_public_key.hex(),
        "target_puzzle_hash": p.target_puzzle_hash.hex(),
        "pool_url": p.pool_url,
        "singleton_genesis": p.singleton_genesis.hex(),
        "pool_payout_instructions": p.pool_payout_instructions.hex(),
        "pool_payout_instructions_signature": p.pool_payout_instructions_signature.hex(),
    }
