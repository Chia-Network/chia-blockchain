from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import yaml
from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from typing_extensions import Self

from chia.util.lock import Lockfile


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
    def get_all_p2_singleton_puzzle_hashes(cls, *, root_path: Path) -> list[bytes32]:
        if not cls.state_path(root_path).exists():
            return []
        with open(cls.state_path(root_path)) as f:
            loaded_dict = yaml.safe_load(f)
            return [bytes32.from_hexstr(p) for p in loaded_dict.keys()]

    def add(self, *, root_path: Path) -> None:
        if not self.state_path(root_path).parent.exists():
            self.state_path(root_path).parent.mkdir()
        if not self.state_path(root_path).exists():
            self.state_path(root_path).touch()
        with (
            self.lock(root_path),
            open(self.state_path(root_path), "r+") as f,
        ):
            loaded_dict = yaml.safe_load(f)
            if loaded_dict is None:
                loaded_dict = {}
            if self.p2_singleton_puzzle_hash.hex() in loaded_dict:
                raise ValueError("Can only call .add() for new singleton entries")
            loaded_dict[self.p2_singleton_puzzle_hash.hex()] = {
                "launcher_id": self.launcher_id.hex(),
                "pool_url": self.pool_url,
                "payout_instructions": self.payout_instructions,
                "target_puzzle_hash": self.target_puzzle_hash.hex(),
                "owner_public_key": bytes(self.owner_public_key).hex(),
            }
            yaml.dump(loaded_dict, f)

    @classmethod
    @contextmanager
    def acquire(cls, *, root_path: Path, p2_singleton_puzzle_hash: bytes32) -> Iterator[Self]:
        with (
            cls.lock(root_path),
            open(cls.state_path(root_path), "r+") as f,
        ):
            loaded_dict = yaml.safe_load(f)
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
            yaml.dump(loaded_dict, f)
