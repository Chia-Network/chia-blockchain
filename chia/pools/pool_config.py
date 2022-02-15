import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List

from blspy import G1Element

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.config import load_config, save_config
from chia.util.streamable import Streamable, streamable

"""
Config example
This is what goes into the user's config file, to communicate between the wallet and the farmer processes.
pool_list:
    launcher_id: ae4ef3b9bfe68949691281a015a9c16630fc8f66d48c19ca548fb80768791afa
    owner_public_key: 84c3fcf9d5581c1ddc702cb0f3b4a06043303b334dd993ab42b2c320ebfa98e5ce558448615b3f69638ba92cf7f43da5
    payout_instructions: c2b08e41d766da4116e388357ed957d04ad754623a915f3fd65188a8746cf3e8
    pool_url: localhost
    p2_singleton_puzzle_hash: 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824
    target_puzzle_hash: 344587cf06a39db471d2cc027504e8688a0a67cce961253500c956c73603fd58
"""  # noqa

log = logging.getLogger(__name__)


@dataclass(frozen=True)
@streamable
class PoolWalletConfig(Streamable):
    launcher_id: bytes32
    pool_url: str
    payout_instructions: str
    target_puzzle_hash: bytes32
    p2_singleton_puzzle_hash: bytes32
    owner_public_key: G1Element


def load_pool_config(root_path: Path) -> List[PoolWalletConfig]:
    config = load_config(root_path, "config.yaml")
    ret_list: List[PoolWalletConfig] = []
    pool_list = config["pool"].get("pool_list", [])
    if pool_list is not None:
        for pool_config_dict in pool_list:
            try:
                pool_config = PoolWalletConfig(
                    bytes32.from_hexstr(pool_config_dict["launcher_id"]),
                    pool_config_dict["pool_url"],
                    pool_config_dict["payout_instructions"],
                    bytes32.from_hexstr(pool_config_dict["target_puzzle_hash"]),
                    bytes32.from_hexstr(pool_config_dict["p2_singleton_puzzle_hash"]),
                    G1Element.from_bytes(hexstr_to_bytes(pool_config_dict["owner_public_key"])),
                )
                ret_list.append(pool_config)
            except Exception as e:
                log.error(f"Exception loading config: {pool_config_dict} {e}")

    return ret_list


async def update_pool_config(root_path: Path, pool_config_list: List[PoolWalletConfig]):
    full_config = load_config(root_path, "config.yaml")
    full_config["pool"]["pool_list"] = [c.to_json_dict() for c in pool_config_list]
    save_config(root_path, "config.yaml", full_config)
