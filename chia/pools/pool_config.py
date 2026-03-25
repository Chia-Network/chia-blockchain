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

from chia.util.lock import Lockfile


class _PoolConfig(TypedDict):
    launcher_id: str
    pool_url: str
    payout_instructions: str
    target_puzzle_hash: str
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
    def _get_raw_content(cls, *, root_path: Path) -> Iterator[dict[str, _PoolConfig]]:
        if not cls.state_path(root_path).parent.exists():
            cls.state_path(root_path).parent.mkdir()
        if not cls.state_path(root_path).exists():
            cls.state_path(root_path).touch()
        with (
            cls.lock(root_path),
            open(cls.state_path(root_path), "r+") as f,
        ):
            loaded_dict = yaml.safe_load(f)
            if loaded_dict is None:
                loaded_dict = {}
            yield loaded_dict
            yaml.dump(loaded_dict, f)

    @classmethod
    def get_all_p2_singleton_puzzle_hashes(cls, *, root_path: Path) -> list[bytes32]:
        with cls._get_raw_content(root_path=root_path) as loaded_dict:
            return [bytes32.from_hexstr(p) for p in loaded_dict.keys()]

    def add(self, *, root_path: Path) -> None:
        with self._get_raw_content(root_path=root_path) as loaded_dict:
            if self.p2_singleton_puzzle_hash.hex() in loaded_dict:
                raise ValueError("Can only call .add() for new singleton entries")
            loaded_dict[self.p2_singleton_puzzle_hash.hex()] = {
                "launcher_id": self.launcher_id.hex(),
                "pool_url": self.pool_url,
                "payout_instructions": self.payout_instructions,
                "target_puzzle_hash": self.target_puzzle_hash.hex(),
                "owner_public_key": bytes(self.owner_public_key).hex(),
            }

    @classmethod
    @contextmanager
    def acquire(cls, *, root_path: Path, p2_singleton_puzzle_hash: bytes32) -> Iterator[Self]:
        with cls._get_raw_content(root_path=root_path) as loaded_dict:
            if p2_singleton_puzzle_hash.hex() not in loaded_dict:
                raise ValueError(f"Attempting to load non-existent pooling state for {p2_singleton_puzzle_hash.hex()}")
            config = loaded_dict[p2_singleton_puzzle_hash.hex()]
            self = cls(
                launcher_id=bytes32.from_hexstr(config["launcher_id"]),
                pool_url=config["pool_url"],
                payout_instructions=config["payout_instructions"],
                target_puzzle_hash=bytes32.from_hexstr(config["target_puzzle_hash"]),
                p2_singleton_puzzle_hash=p2_singleton_puzzle_hash,
                owner_public_key=G1Element.from_bytes(bytes.fromhex(config["owner_public_key"])),
            )
            yield self
            loaded_dict[p2_singleton_puzzle_hash.hex()] = {
                "launcher_id": self.launcher_id.hex(),
                "pool_url": self.pool_url,
                "payout_instructions": self.payout_instructions,
                "target_puzzle_hash": self.target_puzzle_hash.hex(),
                "owner_public_key": bytes(self.owner_public_key).hex(),
            }
