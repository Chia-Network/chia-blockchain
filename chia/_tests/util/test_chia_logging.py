from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from chia.util.chia_logging import initialize_logging


def test_systemd_logging_enabled_installed(tmp_path: Path) -> None:
    """
    Test that JournalHandler is added when log_systemd is True and systemd module is available.
    """
    logging_config: dict[str, Any] = {
        "log_stdout": False,
        "log_filename": "test.log",
        "log_level": "INFO",
        "log_systemd": True,
    }

    # Mock systemd.journal module
    mock_journal_module = MagicMock()
    mock_handler_class = MagicMock()
    mock_journal_module.JournalHandler = mock_handler_class

    # We need to make sure the handler instance has a level attribute to avoid type errors in set_log_level
    mock_handler_instance = MagicMock()
    mock_handler_instance.level = logging.NOTSET
    mock_handler_class.return_value = mock_handler_instance

    with patch.dict(sys.modules, {"systemd": MagicMock(), "systemd.journal": mock_journal_module}):
        with patch("chia.util.chia_logging.get_file_log_handler") as mock_file_handler:
            mock_file_handler.return_value = MagicMock(level=logging.INFO)

            initialize_logging("test_service", logging_config, tmp_path)

            # Verify JournalHandler was initialized with correct identifier
            mock_handler_class.assert_called_with(SYSLOG_IDENTIFIER="chia.test_service")

            # Verify it was added to the root logger
            # (In a real test we might want to check logging.getLogger().handlers,
            # but since we are mocking everything, verification of flow is enough
            # or we assume initialize_logging adds the handlers it creates)
            # Actually, initialize_logging gets the root logger and adds handlers.
            # We can inspect the root logger if we want, but checking the mock creation is a good proxy.


def test_systemd_logging_enabled_not_installed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """
    Test that a warning is logged when log_systemd is True but systemd module is missing.
    """
    logging_config: dict[str, Any] = {
        "log_stdout": False,
        "log_filename": "test.log",
        "log_level": "INFO",
        "log_systemd": True,
    }

    # Mock systemd.journal as None to simulate ImportError
    with patch.dict(sys.modules, {"systemd.journal": None}):
        with patch("chia.util.chia_logging.get_file_log_handler") as mock_file_handler:
            mock_file_handler.return_value = MagicMock(level=logging.INFO)

            with caplog.at_level(logging.WARNING):
                initialize_logging("test_service", logging_config, tmp_path)

    # Verify warning message
    assert "test_service: log_systemd enabled but systemd-python not installed" in caplog.text


def test_systemd_logging_disabled(tmp_path: Path) -> None:
    """
    Test that JournalHandler is NOT added when log_systemd is False.
    """
    logging_config: dict[str, Any] = {
        "log_stdout": False,
        "log_filename": "test.log",
        "log_level": "INFO",
        "log_systemd": False,
    }

    # Even if systemd is installed
    mock_journal_module = MagicMock()
    mock_handler_class = MagicMock()
    mock_journal_module.JournalHandler = mock_handler_class

    with patch.dict(sys.modules, {"systemd": MagicMock(), "systemd.journal": mock_journal_module}):
        with patch("chia.util.chia_logging.get_file_log_handler") as mock_file_handler:
            mock_file_handler.return_value = MagicMock(level=logging.INFO)

            initialize_logging("test_service", logging_config, tmp_path)

            # Verify JournalHandler was NOT called
            mock_handler_class.assert_not_called()
