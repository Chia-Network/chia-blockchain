from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from chia_rs import PartialProof
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint16, uint64

from chia.plotting.prover import PlotVersion, V1Prover, V2Prover, V2Quality, get_prover_from_bytes, get_prover_from_file
from chia.simulator.block_tools import get_plot_dir


class TestProver:
    def test_get_prover_from_file_with_plot1_still_works(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".plot", delete=False) as f:
            temp_path = f.name
        try:
            with pytest.raises(Exception) as exc_info:
                get_prover_from_file(temp_path)
            assert not isinstance(exc_info.value, NotImplementedError)
        finally:
            Path(temp_path).unlink()

    def test_unsupported_file_extension_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported plot file"):
            get_prover_from_file("/nonexistent/path/test.txt")


@pytest.fixture(scope="module")
def v2_plot_path() -> Path:
    plots = sorted(get_plot_dir().glob("*.gplot"))
    assert plots, "No V2 plots found in the test plot cache"
    return plots[0]


class TestV2Prover:
    def test_v2_prover_metadata(self, v2_plot_path: Path) -> None:
        prover = V2Prover.from_filename(str(v2_plot_path))
        assert prover.get_version() == PlotVersion.V2
        assert prover.get_filename() == str(v2_plot_path)
        assert isinstance(prover.get_id(), bytes32)
        assert prover.get_memo()
        assert prover.get_compression_level() == uint8(0)
        assert prover.get_group_size() > 0
        with pytest.raises(AssertionError, match="V2 plot groups do not have a single-plot PlotParam"):
            prover.get_param()
        param = prover.get_param_for_index(uint16(0))
        assert param.plot_index == 0
        assert param.meta_group == prover.get_meta_group()
        assert param.strength_v2 == prover.get_strength()

    def test_v2_prover_get_qualities_for_challenge(self, v2_plot_path: Path) -> None:
        prover = V2Prover.from_filename(str(v2_plot_path))
        for i in range(100):
            qualities = prover.get_qualities_for_challenge(bytes32(i.to_bytes(32, "big")))
            if qualities:
                break
        else:
            pytest.fail("No V2 qualities found in 100 challenges")
        for quality in qualities:
            assert isinstance(quality, V2Quality)
            assert isinstance(quality.get_string(), bytes32)
            assert quality.get_plot_index() < prover.get_group_size()

    def test_v2_prover_bytes_round_trip(self, v2_plot_path: Path) -> None:
        prover = V2Prover.from_filename(str(v2_plot_path))
        restored = V2Prover.from_bytes(bytes(prover))
        assert restored.get_id() == prover.get_id()
        assert restored.get_memo() == prover.get_memo()
        assert restored.get_size() == prover.get_size()
        dispatched = get_prover_from_bytes(str(v2_plot_path), bytes(prover))
        assert isinstance(dispatched, V2Prover)
        assert dispatched.get_id() == prover.get_id()

    def test_get_prover_from_file(self, v2_plot_path: Path) -> None:
        prover = get_prover_from_file(str(v2_plot_path))
        assert isinstance(prover, V2Prover)
        assert prover.get_version() == PlotVersion.V2
        assert prover.get_filename() == str(v2_plot_path)


class TestV1Prover:
    def test_v1_prover_get_version(self) -> None:
        """Test that V1Prover.get_version() returns PlotVersion.V1"""
        mock_disk_prover = MagicMock()
        prover = V1Prover(mock_disk_prover)
        assert prover.get_version() == PlotVersion.V1


class TestActiveV2Prover:
    def test_get_qualities_deduplicates_repeated_partial_proofs(self) -> None:
        duplicate = PartialProof([uint64(1)] * 16)
        distinct = PartialProof([uint64(2)] * 16)
        inner_prover = MagicMock()
        inner_prover.plot_group_id.return_value = bytes32(b"4" * 32)
        inner_prover.get_strength.return_value = 2
        duplicate_quality = SimpleNamespace(chain=duplicate, plot_index=uint16(0))
        inner_prover.get_qualities_for_challenge.return_value = [
            duplicate_quality,
            duplicate_quality,
            SimpleNamespace(chain=distinct, plot_index=uint16(0)),
            duplicate_quality,
            SimpleNamespace(chain=duplicate, plot_index=uint16(1)),
        ]
        prover = V2Prover(inner_prover)

        with patch.dict("chia._tests.util.plot_cache._qualities", {}, clear=True):
            qualities = prover.get_qualities_for_challenge(bytes32(b"4" * 32))

        assert qualities == [
            V2Quality(duplicate, uint16(0), uint8(2)),
            V2Quality(distinct, uint16(0), uint8(2)),
            V2Quality(duplicate, uint16(1), uint8(2)),
        ]


class TestGetProverFromBytes:
    def test_get_prover_from_bytes_v1_plot(self) -> None:
        with patch("chia.plotting.prover.DiskProver") as mock_disk_prover_class:
            mock_disk_prover = MagicMock()
            mock_disk_prover_class.from_bytes.return_value = mock_disk_prover
            result = get_prover_from_bytes("test.plot", b"test_data")
            assert isinstance(result, V1Prover)

    def test_get_prover_from_bytes_unsupported_extension(self) -> None:
        with pytest.raises((RuntimeError, ValueError)):
            get_prover_from_bytes("test.txt", b"test_data")
