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


class TestV2Prover:
    def test_v2_prover_delegates_plot_metadata(self) -> None:
        inner_prover = MagicMock()
        inner_prover.get_filename.return_value = "test.gplot"
        inner_prover.get_strength.return_value = 3
        inner_prover.size.return_value = 18
        inner_prover.get_meta_group.return_value = 4
        inner_prover.get_group_size.return_value = 2
        inner_prover.plot_group_id.return_value = bytes32(b"1" * 32)
        inner_prover.get_memo.return_value = b"memo"
        inner_prover.plot_id_for_index.return_value = bytes32(b"2" * 32)
        inner_prover.to_bytes.return_value = b"serialized prover"
        prover = V2Prover(inner_prover)

        assert prover.get_filename() == "test.gplot"
        assert prover.get_version() == PlotVersion.V2
        assert prover.get_strength() == uint8(3)
        assert prover.get_size() == uint8(18)
        assert prover.get_meta_group() == uint8(4)
        assert prover.get_group_size() == uint16(2)
        assert prover.get_id() == bytes32(b"1" * 32)
        assert prover.get_memo() == b"memo"
        assert prover.get_compression_level() == uint8(0)
        assert bytes(prover) == inner_prover.to_bytes.return_value
        assert prover.plot_id_for_index(uint16(7)) == bytes32(b"2" * 32)
        inner_prover.plot_id_for_index.assert_called_once_with(uint16(7))

        with pytest.raises(AssertionError, match="do not have a single-plot PlotParam"):
            prover.get_param()
        param = prover.get_param_for_index(uint16(7))
        assert param.size_v1 is None
        assert param.plot_index == 7
        assert param.meta_group == 4
        assert param.strength_v2 == 3

    def test_v2_prover_from_bytes(self) -> None:
        with patch("chia.plotting.prover.Prover") as prover_class:
            inner_prover = MagicMock()
            inner_prover.to_bytes.return_value = b"serialized prover"
            prover_class.from_bytes.return_value = inner_prover

            prover = V2Prover.from_bytes(b"serialized prover")

        prover_class.from_bytes.assert_called_once_with(b"serialized prover")
        assert prover.get_version() == PlotVersion.V2
        assert bytes(prover) == inner_prover.to_bytes.return_value

    def test_get_prover_from_file_dispatches_gplot(self) -> None:
        with patch("chia.plotting.prover.Prover") as prover_class:
            inner_prover = MagicMock()
            prover_class.return_value = inner_prover

            prover = get_prover_from_file("test.gplot")

        prover_class.assert_called_once_with("test.gplot")
        assert isinstance(prover, V2Prover)
        assert prover.get_version() == PlotVersion.V2


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
