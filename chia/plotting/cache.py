from __future__ import annotations

import logging
import time
import traceback
from collections.abc import ItemsView, KeysView, ValuesView
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from chia.plotting.prover import ProverProtocol

from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint16, uint64

from chia.plotting.prover import get_prover_from_bytes
from chia.plotting.util import parse_plot_info
from chia.types.blockchain_format.proof_of_space import generate_plot_public_key
from chia.util.streamable import Streamable, VersionedBlob, streamable
from chia.wallet.derive_keys import master_sk_to_local_sk

log = logging.getLogger(__name__)

CURRENT_VERSION: int = 2


@streamable
@dataclass(frozen=True)
class DiskCacheEntry(Streamable):
    prover_data: bytes
    farmer_public_key: G1Element
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    last_use: uint64


@streamable
@dataclass(frozen=True)
class CacheDataV1(Streamable):
    entries: list[tuple[str, DiskCacheEntry]]


@dataclass
class CacheEntry:
    prover: ProverProtocol
    farmer_public_key: G1Element
    pool_public_key: Optional[G1Element]
    pool_contract_puzzle_hash: Optional[bytes32]
    plot_public_key: G1Element
    last_use: float

    @classmethod
    def from_prover(cls, prover: ProverProtocol) -> CacheEntry:
        (
            pool_public_key_or_puzzle_hash,
            farmer_public_key,
            local_master_sk,
        ) = parse_plot_info(prover.get_memo())

        pool_public_key: Optional[G1Element] = None
        pool_contract_puzzle_hash: Optional[bytes32] = None
        if isinstance(pool_public_key_or_puzzle_hash, G1Element):
            pool_public_key = pool_public_key_or_puzzle_hash
        else:
            assert isinstance(pool_public_key_or_puzzle_hash, bytes32)
            pool_contract_puzzle_hash = pool_public_key_or_puzzle_hash

        local_sk = master_sk_to_local_sk(local_master_sk)

        plot_public_key: G1Element = generate_plot_public_key(
            local_sk.get_g1(), farmer_public_key, pool_contract_puzzle_hash is not None
        )

        return cls(prover, farmer_public_key, pool_public_key, pool_contract_puzzle_hash, plot_public_key, time.time())

    def bump_last_use(self) -> None:
        self.last_use = time.time()

    def expired(self, expiry_seconds: int) -> bool:
        return time.time() - self.last_use > expiry_seconds


@dataclass
class Cache:
    _path: Path
    _changed: bool = False
    _data: dict[Path, CacheEntry] = field(default_factory=dict)
    expiry_seconds: int = 7 * 24 * 60 * 60  # Keep the cache entries alive for 7 days after its last access

    def __post_init__(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def __len__(self) -> int:
        return len(self._data)

    def update(self, path: Path, entry: CacheEntry) -> None:
        self._data[path] = entry
        self._changed = True

    def remove(self, cache_keys: list[Path]) -> None:
        for key in cache_keys:
            if key in self._data:
                del self._data[key]
                self._changed = True

    def save(self) -> None:
        try:
            disk_cache_entries: dict[str, DiskCacheEntry] = {
                str(path): DiskCacheEntry(
                    bytes(cache_entry.prover),
                    cache_entry.farmer_public_key,
                    cache_entry.pool_public_key,
                    cache_entry.pool_contract_puzzle_hash,
                    cache_entry.plot_public_key,
                    uint64(cache_entry.last_use),
                )
                for path, cache_entry in self.items()
            }
            cache_data: CacheDataV1 = CacheDataV1(
                [(plot_id, cache_entry) for plot_id, cache_entry in disk_cache_entries.items()]
            )
            disk_cache: VersionedBlob = VersionedBlob(uint16(CURRENT_VERSION), bytes(cache_data))
            serialized: bytes = bytes(disk_cache)
            self._path.write_bytes(serialized)
            self._changed = False
            log.info(f"Saved {len(serialized)} bytes of cached data")
        except Exception as e:
            log.error(f"Failed to save cache: {e}, {traceback.format_exc()}")

    def load(self) -> None:
        try:
            serialized = self._path.read_bytes()
            log.info(f"Loaded {len(serialized)} bytes of cached data")
            stored_cache: VersionedBlob = VersionedBlob.from_bytes(serialized)
            if stored_cache.version == CURRENT_VERSION:
                start = time.time()
                cache_data: CacheDataV1 = CacheDataV1.from_bytes(stored_cache.blob)
                self._data = {}
                estimated_c2_sizes: dict[int, int] = {}
                measured_sizes: dict[int, int] = {
                    32: 738,
                    33: 1083,
                    34: 1771,
                    35: 3147,
                    36: 5899,
                    37: 11395,
                    38: 22395,
                    39: 44367,
                }
                for path, cache_entry in cache_data.entries:
                    prover: ProverProtocol = get_prover_from_bytes(path, cache_entry.prover_data)
                    new_entry = CacheEntry(
                        prover,
                        cache_entry.farmer_public_key,
                        cache_entry.pool_public_key,
                        cache_entry.pool_contract_puzzle_hash,
                        cache_entry.plot_public_key,
                        float(cache_entry.last_use),
                    )
                    # TODO, drop the below entry dropping after few versions or whenever we force a cache recreation.
                    #       it's here to filter invalid cache entries coming from bladebit RAM plotting.
                    #       Related: - https://github.com/Chia-Network/chia-blockchain/issues/13084
                    #                - https://github.com/Chia-Network/chiapos/pull/337
                    k = new_entry.prover.get_size()
                    if k not in estimated_c2_sizes:
                        estimated_c2_sizes[k] = ceil(2**k / 100_000_000) * ceil(k / 8)
                    memo_size = len(new_entry.prover.get_memo())
                    prover_size = len(cache_entry.prover_data)
                    # Estimated C2 size + memo size + 2000 (static data + path)
                    # static data: version(2) + table pointers (<=96) + id(32) + k(1) => ~130
                    # path: up to ~1870, all above will lead to false positive.
                    # See https://github.com/Chia-Network/chiapos/blob/3ee062b86315823dd775453ad320b8be892c7df3/src/prover_disk.hpp#L282-L287  # noqa: E501

                    # Use experimental measurements if more than estimates
                    # https://github.com/Chia-Network/chia-blockchain/issues/16063
                    check_size = estimated_c2_sizes[k] + memo_size + 2000
                    if k in measured_sizes:
                        check_size = max(check_size, measured_sizes[k])

                    if prover_size > check_size:
                        log.warning(
                            "Suspicious cache entry dropped. Recommended: stop the harvester, remove "
                            f"{self._path}, restart. Entry: size {prover_size}, path {path}"
                        )
                    else:
                        self._data[Path(path)] = new_entry

                log.info(f"Parsed {len(self._data)} cache entries in {time.time() - start:.2f}s")

            else:
                raise ValueError(f"Invalid cache version {stored_cache.version}. Expected version {CURRENT_VERSION}.")
        except FileNotFoundError:
            log.debug(f"Cache {self._path} not found")
        except Exception as e:
            log.error(f"Failed to load cache: {e}, {traceback.format_exc()}")

    def keys(self) -> KeysView[Path]:
        return self._data.keys()

    def values(self) -> ValuesView[CacheEntry]:
        return self._data.values()

    def items(self) -> ItemsView[Path, CacheEntry]:
        return self._data.items()

    def get(self, path: Path) -> Optional[CacheEntry]:
        return self._data.get(path)

    def changed(self) -> bool:
        return self._changed

    def path(self) -> Path:
        return self._path
