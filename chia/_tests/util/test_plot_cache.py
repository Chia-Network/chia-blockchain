from __future__ import annotations

import pickle  # noqa: S403
from pathlib import Path
from unittest.mock import MagicMock

from chia_rs.sized_bytes import bytes32

import chia._tests.util.plot_cache as pc
from chia.plotting.prover import V1Prover


class TestLoadFromDisk:
    def test_missing_file(self, tmp_path: Path) -> None:
        q, fp, sp = pc._load_from_disk(tmp_path / "nonexistent")
        assert q == {} and fp == {} and sp == {}

    def test_corrupt_file(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.pickle"
        bad.write_bytes(b"not valid pickle")
        q, fp, sp = pc._load_from_disk(bad)
        assert q == {} and fp == {} and sp == {}

    def test_wrong_shape(self, tmp_path: Path) -> None:
        f = tmp_path / "wrong.pickle"
        f.write_bytes(pickle.dumps(("only", "two")))
        q, fp, sp = pc._load_from_disk(f)
        assert q == {} and fp == {} and sp == {}

    def test_valid_roundtrip(self, tmp_path: Path) -> None:
        f = tmp_path / "cache.pickle"
        qualities = {(b"plot1", b"ch1"): [b"q1", b"q2"]}
        full_proofs = {(b"plot1", b"ch1", 0): b"proof1"}
        solve_proofs = {(b"pp1", b"plot1"): b"sp1"}
        f.write_bytes(pickle.dumps((qualities, full_proofs, solve_proofs)))

        q, fp, sp = pc._load_from_disk(f)
        assert q == qualities
        assert fp == full_proofs
        assert sp == solve_proofs


class TestLoad:
    def test_missing_directory(self, tmp_path: Path) -> None:
        old_cache_path = pc._cache_path
        try:
            pc.load(tmp_path / "does_not_exist")
            assert pc._cache_path == old_cache_path
        finally:
            pc._cache_path = old_cache_path

    def test_loads_entries(self, tmp_path: Path) -> None:
        cache_file = tmp_path / pc.CACHE_FILENAME
        qualities = {(b"id1", b"ch1"): [b"q1"]}
        cache_file.write_bytes(pickle.dumps((qualities, {}, {})))

        old_cache_path = pc._cache_path
        old_qualities = dict(pc._qualities)
        try:
            pc.load(tmp_path)
            assert (b"id1", b"ch1") in pc._qualities
        finally:
            pc._cache_path = old_cache_path
            pc._qualities.clear()
            pc._qualities.update(old_qualities)


class TestSave:
    def test_no_misses_skips_write(self, tmp_path: Path) -> None:
        old = pc._misses, pc._cache_path
        try:
            pc._misses = 0
            pc._cache_path = tmp_path / pc.CACHE_FILENAME
            pc._save()
            assert not pc._cache_path.exists()
        finally:
            pc._misses, pc._cache_path = old

    def test_merges_with_existing(self, tmp_path: Path) -> None:
        cache_file = tmp_path / pc.CACHE_FILENAME
        existing = {(b"old_plot", b"old_ch"): [b"old_q"]}
        cache_file.write_bytes(pickle.dumps((existing, {}, {})))

        old = pc._misses, pc._cache_path, dict(pc._qualities)
        try:
            pc._misses = 1
            pc._cache_path = cache_file
            pc._qualities[b"new_plot", b"new_ch"] = [b"new_q"]
            pc._save()

            q, _fp, _sp = pc._load_from_disk(cache_file)
            assert (b"old_plot", b"old_ch") in q
            assert (b"new_plot", b"new_ch") in q
        finally:
            pc._misses, pc._cache_path = old[0], old[1]
            pc._qualities.clear()
            pc._qualities.update(old[2])


class TestInstall:
    def test_cache_is_installed(self) -> None:
        assert pc._installed

    def test_qualities_cache_hit(self) -> None:
        plot_id = bytes32(b"\x01" * 32)
        challenge = bytes32(b"\x02" * 32)
        quality_bytes = bytes32(b"\x03" * 32)
        key = (bytes(plot_id), bytes(challenge))

        old_qualities = dict(pc._qualities)
        old_hits = pc._hits
        try:
            pc._qualities[key] = [bytes(quality_bytes)]
            mock_prover = MagicMock(spec=V1Prover)
            mock_prover.get_id.return_value = plot_id
            result = V1Prover.get_qualities_for_challenge(mock_prover, challenge)
            assert len(result) == 1
            assert result[0].get_string() == quality_bytes
            assert pc._hits == old_hits + 1
        finally:
            pc._qualities.clear()
            pc._qualities.update(old_qualities)

    def test_full_proof_cache_hit(self) -> None:
        plot_id = bytes32(b"\x04" * 32)
        challenge = bytes32(b"\x05" * 32)
        proof = b"\x06" * 64
        key = (bytes(plot_id), bytes(challenge), 0)

        old_proofs = dict(pc._full_proofs)
        old_hits = pc._hits
        try:
            pc._full_proofs[key] = proof
            mock_prover = MagicMock(spec=V1Prover)
            mock_prover.get_id.return_value = plot_id
            result = V1Prover.get_full_proof(mock_prover, challenge, 0)
            assert result == proof
            assert pc._hits == old_hits + 1
        finally:
            pc._full_proofs.clear()
            pc._full_proofs.update(old_proofs)
