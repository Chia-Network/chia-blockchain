from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest
from chia_rs import AugSchemeMPL, PrivateKey, compute_plot_group_id_v2
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8

from chia.plotting.cache import Cache, CacheEntry
from chia.plotting.create_plots import PlotKeys, create_v2_plots
from chia.plotting.prover import V1Prover, V2Prover
from chia.plotting.util import stream_plot_info_ph, stream_plot_info_pk
from chia.types.blockchain_format.proof_of_space import (
    generate_plot_public_key,
    generate_plot_public_key_v2,
)
from chia.util.bech32m import encode_puzzle_hash
from chia.wallet.derive_keys import master_sk_to_local_sk


@pytest.fixture(scope="module", params=[False, True], ids=["pool-key", "pool-contract"])
def v2_plot(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, PlotKeys, PrivateKey]:
    master = AugSchemeMPL.key_gen(b"1" * 32)
    farmer = AugSchemeMPL.key_gen(b"2" * 32).get_g1()
    pool = AugSchemeMPL.key_gen(b"3" * 32).get_g1()
    keys = PlotKeys(
        farmer,
        None if request.param else pool,
        encode_puzzle_hash(bytes32(b"4" * 32), "xch") if request.param else None,
    )
    created, existing = asyncio.run(
        create_v2_plots(tmp_path_factory.mktemp("v2-plots"), keys, size=18, test_private_keys=[master])
    )
    assert not existing
    assert len(created) == 1
    return next(iter(created.values())), keys, master


def test_v2_creation_and_keys(v2_plot: tuple[Path, PlotKeys, PrivateKey]) -> None:
    path, keys, master = v2_plot
    prover = V2Prover.from_filename(str(path))
    entry = CacheEntry.from_prover(prover)
    local = master_sk_to_local_sk(master)
    expected_pk = generate_plot_public_key_v2(local.get_g1(), keys.farmer_public_key)
    # Fixed vector for the pos2 taproot formula, shared by both pool target types.
    assert bytes(expected_pk).hex() == (
        "8144c8ef9f89911efdc979145ef674978e5158d6afa818942aa48b183d9a863a6e7535258b3e95e34087598e3476c798"
    )
    assert entry.plot_public_key == expected_pk
    assert prover.get_id() == compute_plot_group_id_v2(
        uint8(2), expected_pk, keys.pool_public_key, keys.pool_contract_puzzle_hash
    )


@pytest.mark.parametrize("portable", [False, True])
def test_v1_cache_keys_unchanged(portable: bool) -> None:
    master = AugSchemeMPL.key_gen(b"1" * 32)
    farmer = AugSchemeMPL.key_gen(b"2" * 32).get_g1()
    pool = AugSchemeMPL.key_gen(b"3" * 32).get_g1()
    disk = Mock()
    disk.get_memo.return_value = (
        stream_plot_info_ph(bytes32.zeros, farmer, master) if portable else stream_plot_info_pk(pool, farmer, master)
    )
    entry = CacheEntry.from_prover(V1Prover(disk))
    local = master_sk_to_local_sk(master).get_g1()
    assert entry.plot_public_key == generate_plot_public_key(local, farmer, portable)
    if portable:
        assert bytes(entry.plot_public_key).hex() == (
            "8a4bd31b887522fa93a6fc826dd8d0d3fe0310620240499ce84aa22eb2da7088b26edf01e28e4964c8979671d811b1d5"
        )
    else:
        assert entry.plot_public_key == local + farmer


def test_v2_cache_reload(v2_plot: tuple[Path, PlotKeys, PrivateKey], tmp_path: Path) -> None:
    path, _, _ = v2_plot
    entry = CacheEntry.from_prover(V2Prover.from_filename(str(path)))
    cache = Cache(tmp_path / "cache.dat")
    cache.update(path, entry)
    cache.save()
    restored = Cache(cache.path())
    restored.load()
    assert len(restored) == 1
    loaded = restored.get(path)
    assert loaded is not None
    assert loaded.plot_public_key == entry.plot_public_key
