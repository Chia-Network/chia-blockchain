from __future__ import annotations

import pickle  # ruff: ignore[suspicious-pickle-import]
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from chia_rs.sized_bytes import bytes32

import chia._tests.util.plot_cache as pc
from chia._tests import conftest as test_conftest
from chia._tests.util import blockchain as chain_utils
from chia.plotting.prover import V1Prover
from chia.util import default_root


@pytest.mark.parametrize("exitstatus", list(pytest.ExitCode))
def test_session_finish_publishes_saved_recordings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exitstatus: pytest.ExitCode
) -> None:
    monkeypatch.setattr(default_root, "DEFAULT_ROOT_PATH", tmp_path / "mainnet")
    plot_dir = tmp_path / "test-plots"
    directory = plot_dir / pc.TEST_CACHE_DIRECTORY
    # A failed test retains its previous recording; a passing test replaces its own.
    pc.save_test_cache(directory, "test.py::test_failed", ({(b"retained", b"challenge"): []}, {}, {}))
    pc.save_test_cache(directory, "test.py::test_passed", ({(b"old", b"challenge"): []}, {}, {}))
    destination = plot_dir / pc.CACHE_FILENAME
    pc.merge_test_caches(directory, destination)
    pc.save_test_cache(directory, "test.py::test_passed", ({(b"new", b"challenge"): []}, {}, {}))
    session = cast(pytest.Session, SimpleNamespace(config=SimpleNamespace(option=SimpleNamespace(collectonly=False))))

    test_conftest.pytest_sessionfinish(session, exitstatus)

    assert pc._load_from_disk(destination) == (
        {(b"retained", b"challenge"): [], (b"new", b"challenge"): []},
        {},
        {},
    )


@pytest.mark.parametrize(("worker", "collect_only"), [(True, False), (False, True), (True, True)])
def test_session_finish_does_not_publish_from_worker_or_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker: bool, collect_only: bool
) -> None:
    monkeypatch.setattr(default_root, "DEFAULT_ROOT_PATH", tmp_path / "mainnet")
    plot_dir = tmp_path / "test-plots"
    pc.save_test_cache(
        plot_dir / pc.TEST_CACHE_DIRECTORY, "test.py::test_saved", ({(b"plot", b"challenge"): []}, {}, {})
    )
    config = SimpleNamespace(option=SimpleNamespace(collectonly=collect_only))
    if worker:
        config.workerinput = {}

    test_conftest.pytest_sessionfinish(
        cast(pytest.Session, SimpleNamespace(config=config)), pytest.ExitCode.TESTS_FAILED
    )

    assert not (plot_dir / pc.CACHE_FILENAME).exists()


def test_replacing_test_recording_shrinks_cache_and_retains_unrun_tests(tmp_path: Path) -> None:
    directory = tmp_path / pc.TEST_CACHE_DIRECTORY
    destination = tmp_path / pc.CACHE_FILENAME
    destination.write_bytes(pickle.dumps(({(b"stale", b"challenge"): []}, {}, {})))
    first = "test_file.py::test_proofs[first]"
    second = "test_file.py::test_proofs[second]"
    pc.save_test_cache(directory, first, ({(b"old", b"challenge"): []}, {}, {}))
    pc.save_test_cache(directory, second, ({}, {}, {(b"partial", b"plot"): b"proof"}))
    pc.merge_test_caches(directory, destination)
    pc.save_test_cache(directory, first, ({(b"new", b"challenge"): []}, {}, {}))
    pc.merge_test_caches(directory, destination)
    assert pc._load_from_disk(destination) == ({(b"new", b"challenge"): []}, {}, {(b"partial", b"plot"): b"proof"})
    assert len(list(directory.glob("*.pickle"))) == 2
    # A test that stops using plots must remove its previous entries as well.
    pc.save_test_cache(directory, first, ({}, {}, {}))
    pc.save_test_cache(directory, second, ({}, {}, {}))
    pc.merge_test_caches(directory, destination)
    assert pc._load_from_disk(destination) == ({}, {}, {})


def test_no_recordings_preserves_existing_cache(tmp_path: Path) -> None:
    destination = tmp_path / pc.CACHE_FILENAME
    destination.write_bytes(b"existing")
    pc.merge_test_caches(tmp_path / "missing", destination)
    assert destination.read_bytes() == b"existing"


def test_pruning_preserves_uncollected_tests(tmp_path: Path) -> None:
    for name in ("test_first.py", "test_second.py"):
        (tmp_path / name).touch()
    directory = tmp_path / pc.TEST_CACHE_DIRECTORY
    keep = "test_first.py::test_proofs[keep]"
    removed = "test_first.py::test_proofs[removed]"
    uncollected = "test_second.py::test_other"
    deleted = "test_deleted.py::test_other"
    for nodeid in (keep, removed, uncollected, deleted):
        pc.save_test_cache(directory, nodeid, ({(nodeid.encode(), b"challenge"): []}, {}, {}))
    pc.prune_test_caches(directory, {keep}, tmp_path, files={"test_first.py"})
    assert pc.test_cache_path(directory, keep).exists()
    assert pc.test_cache_path(directory, uncollected).exists()
    assert not pc.test_cache_path(directory, removed).exists()
    assert not pc.test_cache_path(directory, deleted).exists()


@pytest.mark.parametrize("contents", [b"corrupt", b"", pickle.dumps(("test.py::test_bad", ({}, {})))])
def test_invalid_recording_does_not_fail_merge(tmp_path: Path, contents: bytes) -> None:
    directory = tmp_path / pc.TEST_CACHE_DIRECTORY
    pc.save_test_cache(directory, "test.py::test_good", ({(b"plot", b"challenge"): []}, {}, {}))
    pc.test_cache_path(directory, "test.py::test_bad").write_bytes(contents)
    # Leftover temporary files from interrupted writers are not inputs.
    (directory / "interrupted.pickle.tmp").write_bytes(b"incomplete")
    destination = tmp_path / pc.CACHE_FILENAME
    pc.merge_test_caches(directory, destination)
    assert pc._load_from_disk(destination) == ({(b"plot", b"challenge"): []}, {}, {})


def test_recording_captures_hits_misses_and_empty_qualities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pc, "_qualities", {})
    monkeypatch.setattr(pc, "_full_proofs", {})
    monkeypatch.setattr(pc, "_solve_proofs", {})
    inner = MagicMock()
    plot_id, challenge = bytes32(b"p" * 32), bytes32(b"c" * 32)
    inner.get_id.return_value = plot_id
    inner.get_qualities_for_challenge.return_value = []
    inner.get_full_proof.return_value = b"proof"
    prover = V1Prover(inner)
    partial = MagicMock()
    partial.to_bytes.return_value = b"partial"
    solve = MagicMock(return_value=b"solved")
    monkeypatch.setattr(pc, "_orig_solve_proof", solve)
    for _ in range(2):
        # The second test gets only hits and must still record all three tables.
        with pc.record_test() as recorded:
            assert prover.get_qualities_for_challenge(challenge) == []
            assert prover.get_full_proof(challenge, 0) == b"proof"
            assert pc.cached_solve_proof(partial, plot_id, 1, 20, True) == b"solved"
        assert recorded == (
            {(plot_id, challenge): []},
            {(plot_id, challenge, 0): b"proof"},
            {(b"partial", plot_id): b"solved"},
        )
    inner.get_qualities_for_challenge.assert_called_once()
    inner.get_full_proof.assert_called_once()
    solve.assert_called_once()


def test_persistent_chain_generation_is_not_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(chain_utils, "DEFAULT_ROOT_PATH", tmp_path / "mainnet")
    bt = MagicMock()

    def generate(*args: Any, **kwargs: Any) -> list[bytes]:
        pc._record_lookup(0, (b"generation-only", b"challenge"), [])
        return [b"block"]

    bt.get_consecutive_blocks.side_effect = generate
    with pc.record_test() as recorded:
        chain_utils.persistent_blocks(1, "chain.db", bt)
        pc._record_lookup(0, (b"dynamic", b"challenge"), [])
    assert recorded == ({(b"dynamic", b"challenge"): []}, {}, {})
    assert (tmp_path / "blocks" / "chain.db").exists()
    assert not list((tmp_path / "blocks").glob("*.plot-cache.pickle"))


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
    def test_missing_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pc, "_qualities", {})
        monkeypatch.setattr(pc, "_full_proofs", {})
        monkeypatch.setattr(pc, "_solve_proofs", {})
        pc.load(tmp_path / "does_not_exist")
        assert (pc._qualities, pc._full_proofs, pc._solve_proofs) == ({}, {}, {})

    def test_loads_entries(self, tmp_path: Path) -> None:
        cache_file = tmp_path / pc.CACHE_FILENAME
        qualities = {(b"id1", b"ch1"): [b"q1"]}
        cache_file.write_bytes(pickle.dumps((qualities, {}, {})))

        old_qualities = dict(pc._qualities)
        try:
            pc.load(tmp_path)
            assert (b"id1", b"ch1") in pc._qualities
        finally:
            pc._qualities.clear()
            pc._qualities.update(old_qualities)


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
