from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chia.plotting.prover import PlotVersion, V1Prover, V2Prover, get_prover_from_bytes, get_prover_from_file


class TestProver:
    def test_v2_prover_init_with_nonexistent_file(self) -> None:
        prover = V2Prover("/nonexistent/path/test.plot2")
        assert prover.get_version() == PlotVersion.V2
        assert prover.get_filename() == "/nonexistent/path/test.plot2"

    def test_v2_prover_get_size_raises_error(self) -> None:
        prover = V2Prover("/nonexistent/path/test.plot2")
        with pytest.raises(NotImplementedError, match="V2 plot format is not yet implemented"):
            prover.get_size()

    def test_v2_prover_get_memo_raises_error(self) -> None:
        prover = V2Prover("/nonexistent/path/test.plot2")
        with pytest.raises(NotImplementedError, match="V2 plot format is not yet implemented"):
            prover.get_memo()

    def test_v2_prover_get_compression_level_raises_error(self) -> None:
        prover = V2Prover("/nonexistent/path/test.plot2")
        with pytest.raises(NotImplementedError, match="V2 plot format is not yet implemented"):
            prover.get_compression_level()

    def test_v2_prover_get_id_raises_error(self) -> None:
        prover = V2Prover("/nonexistent/path/test.plot2")
        with pytest.raises(NotImplementedError, match="V2 plot format is not yet implemented"):
            prover.get_id()

    def test_v2_prover_get_qualities_for_challenge_raises_error(self) -> None:
        prover = V2Prover("/nonexistent/path/test.plot2")
        with pytest.raises(NotImplementedError, match="V2 plot format is not yet implemented"):
            prover.get_qualities_for_challenge(b"challenge")

    def test_v2_prover_get_full_proof_raises_error(self) -> None:
        prover = V2Prover("/nonexistent/path/test.plot2")
        with pytest.raises(NotImplementedError, match="V2 plot format is not yet implemented"):
            prover.get_full_proof(b"challenge", 0)

    def test_v2_prover_bytes_raises_error(self) -> None:
        prover = V2Prover("/nonexistent/path/test.plot2")
        with pytest.raises(NotImplementedError, match="V2 plot format is not yet implemented"):
            bytes(prover)

    def test_v2_prover_from_bytes_raises_error(self) -> None:
        with pytest.raises(NotImplementedError, match="V2 plot format is not yet implemented"):
            V2Prover.from_bytes(b"test_data")

    def test_get_prover_from_file(self) -> None:
        prover = get_prover_from_file("/nonexistent/path/test.plot2")
        assert prover.get_version() == PlotVersion.V2
        with pytest.raises(NotImplementedError, match="V2 plot format is not yet implemented"):
            prover.get_size()

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


class TestV1Prover:
    def test_v1_prover_get_version(self) -> None:
        """Test that V1Prover.get_version() returns PlotVersion.V1"""
        mock_disk_prover = MagicMock()
        prover = V1Prover(mock_disk_prover)
        assert prover.get_version() == PlotVersion.V1


class TestGetProverFromBytes:
    def test_get_prover_from_bytes_v2_plot(self) -> None:
        with patch("chia.plotting.prover.V2Prover.from_bytes") as mock_v2_from_bytes:
            mock_prover = MagicMock()
            mock_v2_from_bytes.return_value = mock_prover
            result = get_prover_from_bytes("test.plot2", b"test_data")
            assert result == mock_prover

    def test_get_prover_from_bytes_v1_plot(self) -> None:
        with patch("chia.plotting.prover.DiskProver") as mock_disk_prover_class:
            mock_disk_prover = MagicMock()
            mock_disk_prover_class.from_bytes.return_value = mock_disk_prover
            result = get_prover_from_bytes("test.plot", b"test_data")
            assert isinstance(result, V1Prover)

    def test_get_prover_from_bytes_unsupported_extension(self) -> None:
        with pytest.raises(ValueError, match="Unsupported plot file"):
            get_prover_from_bytes("test.txt", b"test_data")
