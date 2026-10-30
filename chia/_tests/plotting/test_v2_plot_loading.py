from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
from chia_rs import AugSchemeMPL, PrivateKey, compute_plot_group_id_v2, solve_proof, validate_proof_v2
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16

from chia.plotting import check_plots as check_plots_module
from chia.plotting.cache import Cache, CacheEntry
from chia.plotting.create_plots import PlotKeys, create_v2_plots
from chia.plotting.prover import V1Prover, V2Prover, V2Quality
from chia.plotting.util import stream_plot_info_ph, stream_plot_info_pk
from chia.types.blockchain_format.proof_of_space import (
    generate_plot_public_key,
)
from chia.util.bech32m import encode_puzzle_hash
from chia.util.hash import std_hash
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
    expected_pk = generate_plot_public_key(local.get_g1(), keys.farmer_public_key, is_v2=True)
    # Fixed vector for the pos2 taproot formula, shared by both pool target types.
    assert bytes(expected_pk).hex() == (
        "8144c8ef9f89911efdc979145ef674978e5158d6afa818942aa48b183d9a863a6e7535258b3e95e34087598e3476c798"
    )
    assert entry.plot_public_key == expected_pk
    assert prover.get_id() == compute_plot_group_id_v2(
        uint8(2), expected_pk, keys.pool_public_key, keys.pool_contract_puzzle_hash
    )


def test_v2_proof_uses_plot_size(v2_plot: tuple[Path, PlotKeys, PrivateKey]) -> None:
    path, _, _ = v2_plot
    prover = V2Prover.from_filename(str(path))
    assert prover.get_size() == 18
    for i in range(100):
        challenge = std_hash(i.to_bytes(32, "big"))
        qualities = prover.get_qualities_for_challenge(challenge)
        if qualities:
            break
    else:
        pytest.fail("No V2 qualities found in 100 challenges")
    quality = qualities[0]
    assert isinstance(quality, V2Quality)
    proof = solve_proof(
        quality.get_partial_proof(),
        prover.plot_id_for_index(quality.get_plot_index()),
        prover.get_strength(),
        prover.get_size(),
    )
    assert (
        validate_proof_v2(
            prover.get_id(),
            quality.get_plot_index(),
            prover.get_size(),
            prover.get_strength(),
            prover.get_meta_group(),
            challenge,
            proof,
        )
        == quality.get_string()
    )
    assert (
        validate_proof_v2(
            prover.get_id(),
            quality.get_plot_index(),
            uint8(28),
            prover.get_strength(),
            prover.get_meta_group(),
            challenge,
            proof,
        )
        is None
    )


def test_check_plots_reports_unsupported_network_size(
    v2_plot: tuple[Path, PlotKeys, PrivateKey],
    root_path_populated_with_config: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path, _, _ = v2_plot
    prover = V2Prover.from_filename(str(path))
    monkeypatch.setattr(prover, "get_qualities_for_challenge", Mock(side_effect=AssertionError("proof check was run")))
    manager = MagicMock()
    manager.plots = {path: Mock(prover=prover)}
    manager.__enter__.return_value = manager
    manager.needs_refresh.return_value = False
    manager.plot_count.return_value = 1
    manager.failed_to_open_filenames = {}
    manager.no_key_filenames = []
    monkeypatch.setattr(check_plots_module, "PlotManager", lambda *args, **kwargs: manager)
    keychain = Mock()
    keychain.get_all_private_keys.return_value = []
    monkeypatch.setattr(check_plots_module, "Keychain", lambda: keychain)

    check_plots_module.check_plots(root_path_populated_with_config, 5, None, "", False, False)

    assert "it has k=18, but mainnet requires k=28" in caplog.text
    assert "This plot cannot be farmed on the selected network" in caplog.text
    assert "Quality doesn't match with proof" not in caplog.text


def test_v2_multi_file_group(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    master = AugSchemeMPL.key_gen(b"1" * 32)
    keys = PlotKeys(AugSchemeMPL.key_gen(b"2" * 32).get_g1(), AugSchemeMPL.key_gen(b"3" * 32).get_g1(), None)

    created, existing = asyncio.run(
        create_v2_plots(tmp_path, keys, size=18, plots_per_group=2, test_private_keys=[master])
    )
    assert "Multiple plots per file are not supported yet; creating each plot in an individual file" in caplog.text
    assert len(created) == 1
    assert not existing
    paths = sorted(tmp_path.glob("*.gplot"))
    assert len(paths) == 2
    provers = [V2Prover.from_filename(str(path)) for path in paths]
    assert all(prover.get_id() == next(iter(created)) for prover in provers)
    assert provers[0].plot_id_for_index(uint16(0)) != provers[1].plot_id_for_index(uint16(1))
    assert paths[0].read_bytes() != paths[1].read_bytes()

    created_again, existing_again = asyncio.run(
        create_v2_plots(tmp_path, keys, size=18, plots_per_group=2, test_private_keys=[master])
    )
    assert not created_again
    assert len(existing_again) == 1


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
