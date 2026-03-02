from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from chia.util.chia_logging import JournalSocketHandler, initialize_logging


@pytest.fixture(autouse=True)
def cleanup_root_logger() -> Any:
    root_logger = logging.getLogger()
    existing_handlers = list(root_logger.handlers)
    try:
        yield
    finally:
        for handler in list(root_logger.handlers):
            if handler not in existing_handlers:
                root_logger.removeHandler(handler)
                with contextlib.suppress(Exception):
                    handler.close()


def test_systemd_logging_enabled_installed(tmp_path: Path) -> None:
    """
    Test that JournalSocketHandler is added when log_systemd is True and journald is available.
    """
    logging_config: dict[str, Any] = {
        "log_stdout": False,
        "log_filename": "test.log",
        "log_level": "INFO",
        "log_systemd": True,
    }

    mock_handler_instance = MagicMock()
    mock_handler_instance.level = logging.NOTSET

    with patch("chia.util.chia_logging.JournalSocketHandler", return_value=mock_handler_instance) as mock_handler_class:
        with patch("chia.util.chia_logging.get_file_log_handler", return_value=MagicMock(level=logging.INFO)):
            initialize_logging("test_service", logging_config, tmp_path)

    mock_handler_class.assert_called_once_with(identifier="chia.test_service")


def test_systemd_logging_enabled_not_installed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """
    Test that a warning is logged when log_systemd is True but journald is unavailable.
    """
    logging_config: dict[str, Any] = {
        "log_stdout": False,
        "log_filename": "test.log",
        "log_level": "INFO",
        "log_systemd": True,
    }

    with patch("chia.util.chia_logging.JournalSocketHandler", side_effect=OSError("missing socket")):
        with patch("chia.util.chia_logging.get_file_log_handler", return_value=MagicMock(level=logging.INFO)):
            with caplog.at_level(logging.WARNING):
                initialize_logging("test_service", logging_config, tmp_path)

    assert "test_service: log_systemd enabled but /run/systemd/journal/socket is unavailable" in caplog.text


def test_systemd_logging_disabled(tmp_path: Path) -> None:
    """
    Test that JournalSocketHandler is NOT added when log_systemd is False.
    """
    logging_config: dict[str, Any] = {
        "log_stdout": False,
        "log_filename": "test.log",
        "log_level": "INFO",
        "log_systemd": False,
    }

    with patch("chia.util.chia_logging.JournalSocketHandler") as mock_handler_class:
        with patch("chia.util.chia_logging.get_file_log_handler", return_value=MagicMock(level=logging.INFO)):
            initialize_logging("test_service", logging_config, tmp_path)

    mock_handler_class.assert_not_called()


def test_journal_socket_handler_emits_native_entry() -> None:
    mock_socket = MagicMock()

    with patch("chia.util.chia_logging.socket.socket", return_value=mock_socket):
        handler = JournalSocketHandler(identifier="chia.test_service")

    handler.setFormatter(logging.Formatter("%(message)s"))
    record = logging.LogRecord(
        name="test.logger",
        level=logging.ERROR,
        pathname="/fake/path/test.py",
        lineno=123,
        msg="systemd works",
        args=(),
        exc_info=None,
        func="test_emit",
    )
    record.threadName = "MainThread"

    handler.emit(record)

    payload = mock_socket.send.call_args.args[0]
    assert b"MESSAGE=systemd works\n" in payload
    assert b"PRIORITY=3\n" in payload
    assert b"SYSLOG_IDENTIFIER=chia.test_service\n" in payload
    assert b"LOGGER=test.logger\n" in payload
    assert b"CODE_FILE=/fake/path/test.py\n" in payload
    assert b"CODE_LINE=123\n" in payload
    assert b"CODE_FUNC=test_emit\n" in payload

    handler.close()
