from __future__ import annotations

import pickle  # ruff: ignore[suspicious-pickle-import]
import time
from pathlib import Path

import pytest
from chia_rs import AugSchemeMPL, PrivateKey
from chia_rs.sized_ints import uint32

import chia._tests.util.derivation_cache as dc
from chia.wallet.derive_keys import master_sk_to_local_sk, master_sk_to_wallet_sk


def _seed_key() -> PrivateKey:
    return AugSchemeMPL.key_gen(b"seed" * 8)


class TestLoadFromDisk:
    def test_missing_file(self, tmp_path: Path) -> None:
        assert dc._load_from_disk(tmp_path / "nonexistent") == {}

    def test_corrupt_file(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.pickle"
        bad.write_bytes(b"not valid pickle")
        assert dc._load_from_disk(bad) == {}

    def test_wrong_version(self, tmp_path: Path) -> None:
        f = tmp_path / "wrong.pickle"
        f.write_bytes(pickle.dumps((dc.CACHE_VERSION + 1, {})))
        assert dc._load_from_disk(f) == {}

    def test_valid_roundtrip(self, tmp_path: Path) -> None:
        f = tmp_path / "cache.pickle"
        payload = {(b"sk", b"parent", 0): b"child-key-bytes"}
        f.write_bytes(pickle.dumps((dc.CACHE_VERSION, payload)))
        assert dc._load_from_disk(f) == payload


class TestLoad:
    def test_creates_directory(self, tmp_path: Path) -> None:
        dest = tmp_path / "missing" / "dir"
        old_path = dc._cache_path
        old_enabled = dc._enabled
        try:
            dc._enabled = True
            dc.load(dest)
            assert dest.is_dir()
            assert dc._cache_path == dest / dc.CACHE_FILENAME
        finally:
            dc._cache_path = old_path
            dc._enabled = old_enabled

    def test_loads_entries(self, tmp_path: Path) -> None:
        payload = {(b"sk", b"p", 1): b"c"}
        cache_file = tmp_path / dc.CACHE_FILENAME
        cache_file.write_bytes(pickle.dumps((dc.CACHE_VERSION, payload)))
        old_path = dc._cache_path
        old_cache = dict(dc._cache)
        old_enabled = dc._enabled
        try:
            dc._enabled = True
            dc._cache.clear()
            dc.load(tmp_path)
            assert (b"sk", b"p", 1) in dc._cache
        finally:
            dc._cache_path = old_path
            dc._cache.clear()
            dc._cache.update(old_cache)
            dc._enabled = old_enabled


class TestSave:
    def test_no_misses_skips_write(self, tmp_path: Path) -> None:
        cache_file = tmp_path / dc.CACHE_FILENAME
        old = dc._misses, dc._cache_path, dc._enabled
        try:
            dc._misses = 0
            dc._enabled = True
            dc._cache_path = cache_file
            dc._save()
            assert not cache_file.exists()
        finally:
            dc._misses, dc._cache_path, dc._enabled = old

    def test_merges_with_existing(self, tmp_path: Path) -> None:
        cache_file = tmp_path / dc.CACHE_FILENAME
        existing = {(b"sk", b"old", 0): b"oldv"}
        cache_file.write_bytes(pickle.dumps((dc.CACHE_VERSION, existing)))
        old_misses = dc._misses
        old_path = dc._cache_path
        old_enabled = dc._enabled
        old_cache = dict(dc._cache)
        try:
            dc._misses = 1
            dc._enabled = True
            dc._cache_path = cache_file
            dc._cache.clear()
            dc._cache[b"sk", b"new", 1] = b"newv"
            dc._save()
            loaded = dc._load_from_disk(cache_file)
            assert (b"sk", b"old", 0) in loaded
            assert (b"sk", b"new", 1) in loaded
        finally:
            dc._misses = old_misses
            dc._cache_path = old_path
            dc._enabled = old_enabled
            dc._cache.clear()
            dc._cache.update(old_cache)


class TestInstallAndCorrectness:
    @pytest.mark.skipif(not dc._installed, reason="derivation cache fixture disabled for CI A/B (B = no cache)")
    def test_cache_is_installed(self) -> None:
        assert dc._installed
        sk = _seed_key()
        assert AugSchemeMPL.derive_child_sk(sk, 1) == dc._orig_derive_child_sk(sk, 1)

    def test_cached_matches_original(self) -> None:
        sk = _seed_key()
        uncached = dc._orig_derive_child_sk(sk, 12381)
        cached = AugSchemeMPL.derive_child_sk(sk, 12381)
        cached_again = AugSchemeMPL.derive_child_sk(sk, 12381)
        assert cached == uncached
        assert cached_again == uncached

    def test_wallet_and_local_paths_match_originals(self) -> None:
        sk = _seed_key()
        wallet = master_sk_to_wallet_sk(sk, uint32(0))
        local = master_sk_to_local_sk(sk)
        orig_wallet = sk
        orig_local = sk
        for index in (12381, 8444, 2, 0):
            orig_wallet = dc._orig_derive_child_sk(orig_wallet, index)
        for index in (12381, 8444, 3, 0):
            orig_local = dc._orig_derive_child_sk(orig_local, index)
        assert wallet == orig_wallet
        assert local == orig_local

    @pytest.mark.skipif(not dc._installed, reason="derivation cache fixture disabled for CI A/B (B = no cache)")
    def test_hit_increments(self) -> None:
        sk = _seed_key()
        old_hits = dc._hits
        AugSchemeMPL.derive_child_sk(sk, 8444)
        AugSchemeMPL.derive_child_sk(sk, 8444)
        assert dc._hits >= old_hits + 1


class TestDisabled:
    def test_env_parser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(dc.ENV_VAR, "0")
        assert dc._env_enabled() is False
        monkeypatch.setenv(dc.ENV_VAR, "1")
        assert dc._env_enabled() is True

    def test_disabled_still_computes(self) -> None:
        sk = _seed_key()
        expected = dc._orig_derive_child_sk(sk, 7)
        old_enabled = dc._enabled
        try:
            dc._enabled = False
            assert AugSchemeMPL.derive_child_sk(sk, 7) == expected
        finally:
            dc._enabled = old_enabled


class TestMicrobench:
    def test_repeated_derivation_cost(self) -> None:
        """Print uncached vs cached cost for a wallet-like derivation window.

        This is the number that transfers to slow CI better than suite wall clock.
        """
        sk = _seed_key()
        n = 2000
        t0 = time.perf_counter()
        last = None
        for i in range(n):
            last = dc._orig_derive_child_sk(sk, i % 16)
        uncached_s = time.perf_counter() - t0

        t0 = time.perf_counter()
        last_cached = None
        for i in range(n):
            last_cached = AugSchemeMPL.derive_child_sk(sk, i % 16)
        cached_s = time.perf_counter() - t0
        assert last is not None and last_cached is not None
        print(
            f"\nderivation microbench n={n}: uncached={uncached_s:.4f}s "
            f"cached_path={cached_s:.4f}s per_uncached_us={uncached_s * 1e6 / n:.1f}"
        )
