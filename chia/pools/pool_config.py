from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import yaml
from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from typing_extensions import Self

from chia.util.config import lock_and_load_config, save_config
from chia.util.lock import Lockfile


class _PoolConfig(TypedDict):
    launcher_id: str
    pool_url: str
    payout_instructions: str
    target_puzzle_hash: str
    p2_singleton_puzzle_hash: str
    owner_public_key: str


@dataclass(kw_only=True)
class PoolingShareState:
    launcher_id: bytes32
    pool_url: str
    payout_instructions: str
    target_puzzle_hash: bytes32
    p2_singleton_puzzle_hash: bytes32
    owner_public_key: G1Element

    @staticmethod
    def state_path(root_path: Path) -> Path:
        return root_path / "pooling" / "pooling_share_state.yaml"

    @staticmethod
    def lock(root_path: Path) -> Lockfile:
        return Lockfile.create(root_path / "pooling" / "pooling_share_state.lock")

    @classmethod
    @contextmanager
    def _get_raw_content(cls, *, root_path: Path) -> Iterator[list[_PoolConfig]]:
        if not cls.state_path(root_path).parent.exists():
            cls.state_path(root_path).parent.mkdir(exist_ok=True)
        if not cls.state_path(root_path).exists():
            cls.state_path(root_path).touch(exist_ok=True)
        with (
            cls.lock(root_path),
            open(cls.state_path(root_path), "r+") as f,
        ):
            loaded_content = yaml.safe_load(f)
            if loaded_content is None:
                loaded_list = []
            else:
                loaded_list = loaded_content["pooling_information"]
            yield loaded_list
            if loaded_list != []:
                f.seek(0)
                f.truncate()
                yaml.dump({"pooling_information": loaded_list}, f)

    @staticmethod
    def _p2_singleton_puzzle_hashes_from_list(loaded_list: list[_PoolConfig]) -> list[bytes32]:
        return [bytes32.from_hexstr(p["p2_singleton_puzzle_hash"]) for p in loaded_list]

    @classmethod
    def get_all_p2_singleton_puzzle_hashes(cls, *, root_path: Path) -> list[bytes32]:
        with cls._get_raw_content(root_path=root_path) as loaded_list:
            return cls._p2_singleton_puzzle_hashes_from_list(loaded_list)

    def add(self, *, root_path: Path) -> None:
        with self._get_raw_content(root_path=root_path) as loaded_list:
            if self.p2_singleton_puzzle_hash in self._p2_singleton_puzzle_hashes_from_list(loaded_list):
                raise ValueError("Can only call .add() for new singleton entries")
            loaded_list.append(self.to_json_dict())

    @classmethod
    @contextmanager
    def acquire(cls, *, root_path: Path, p2_singleton_puzzle_hash: bytes32) -> Iterator[Self]:
        with cls._get_raw_content(root_path=root_path) as loaded_list:
            if p2_singleton_puzzle_hash not in cls._p2_singleton_puzzle_hashes_from_list(loaded_list):
                raise ValueError(f"Attempting to load non-existent pooling state for {p2_singleton_puzzle_hash.hex()}")
            config = loaded_list[
                next(
                    i
                    for i, c in enumerate(loaded_list)
                    if c["p2_singleton_puzzle_hash"] == p2_singleton_puzzle_hash.hex()
                )
            ]
            self = cls(
                launcher_id=bytes32.from_hexstr(config["launcher_id"]),
                pool_url=config["pool_url"],
                payout_instructions=config["payout_instructions"],
                target_puzzle_hash=bytes32.from_hexstr(config["target_puzzle_hash"]),
                p2_singleton_puzzle_hash=p2_singleton_puzzle_hash,
                owner_public_key=G1Element.from_bytes(bytes.fromhex(config["owner_public_key"])),
            )
            yield self
            for i, conf in enumerate(loaded_list):
                if conf["p2_singleton_puzzle_hash"] == p2_singleton_puzzle_hash.hex():
                    loaded_list[i] = self.to_json_dict()
                    break

    def to_json_dict(self) -> _PoolConfig:
        return {
            "launcher_id": self.launcher_id.hex(),
            "pool_url": self.pool_url,
            "payout_instructions": self.payout_instructions,
            "target_puzzle_hash": self.target_puzzle_hash.hex(),
            "owner_public_key": bytes(self.owner_public_key).hex(),
            "p2_singleton_puzzle_hash": self.p2_singleton_puzzle_hash.hex(),
        }


def perform_migration_from_old_config(root_path: Path) -> None:
    with lock_and_load_config(root_path, "config.yaml") as chia_config:
        if (
            not PoolingShareState.state_path(root_path=root_path).exists()
            and chia_config["pool"].get("pool_list", []) != []
        ):
            pool_list = chia_config["pool"]["pool_list"]
            for pool in pool_list:
                PoolingShareState(
                    launcher_id=bytes32.from_hexstr(pool["launcher_id"]),
                    pool_url=pool["pool_url"],
                    payout_instructions=pool["payout_instructions"],
                    target_puzzle_hash=bytes32.from_hexstr(pool["target_puzzle_hash"]),
                    owner_public_key=G1Element.from_bytes(bytes.fromhex(pool["owner_public_key"])),
                    p2_singleton_puzzle_hash=bytes32.from_hexstr(pool["p2_singleton_puzzle_hash"]),
                ).add(root_path=root_path)
            chia_config["pool"]["pool_list"] = []
            save_config(root_path, "config.yaml", chia_config)
