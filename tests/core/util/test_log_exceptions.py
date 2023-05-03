from __future__ import annotations

import contextlib
import dataclasses
import logging
import re
from typing import Tuple, Type, Union

import pytest

from chia.util.log_exceptions import log_exceptions

log_message = "Some message that probably, hopefully, won't accidentally come from somewhere else"
exception_message = "A message tied to the exception"


@pytest.fixture(name="logger")
def logger_fixture() -> logging.Logger:
    return logging.getLogger(__name__)


@dataclasses.dataclass
class ErrorCase:
    type_to_raise: Type[BaseException]
    type_to_catch: Union[Type[BaseException], Tuple[Type[BaseException], ...]]
    should_match: bool


all_level_values = [
    logging.CRITICAL,
    logging.ERROR,
    logging.WARNING,
    logging.INFO,
    logging.DEBUG,
]
all_levels = {logging.getLevelName(value): value for value in all_level_values}


def test_consumes_exception(
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with log_exceptions(log=logger, consume=True):
        raise Exception()


def test_propagates_exception(
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(Exception, match=re.escape(exception_message)):
        with log_exceptions(log=logger, consume=False):
            raise Exception(exception_message)


def test_propagates_exception_by_default(
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(Exception, match=re.escape(exception_message)):
        with log_exceptions(log=logger):
            raise Exception(exception_message)


def test_passed_message_is_used(
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with log_exceptions(log=logger, consume=True, message=log_message):
        raise Exception()

    assert len(caplog.records) == 1, caplog.records

    [record] = caplog.records
    assert record.msg.startswith(f"{log_message}: ")


@pytest.mark.parametrize(
    argnames="level",
    argvalues=all_levels.values(),
    ids=all_levels.keys(),
)
def test_specified_level_is_used(
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
    level: int,
) -> None:
    caplog.set_level(min(all_levels.values()))
    with log_exceptions(level=level, log=logger, consume=True):
        raise Exception()

    assert len(caplog.records) == 1, caplog.records

    [record] = caplog.records
    assert record.levelno == level


def test_traceback_is_logged(
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with log_exceptions(log=logger, consume=True, show_traceback=True):
        raise Exception()

    assert len(caplog.records) == 1, caplog.records

    [record] = caplog.records
    assert "\nTraceback " in record.msg


def test_traceback_is_not_logged(
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with log_exceptions(log=logger, consume=True, show_traceback=False):
        raise Exception()

    assert len(caplog.records) == 1, caplog.records

    [record] = caplog.records
    assert "\nTraceback " not in record.msg


@pytest.mark.parametrize(
    argnames="case",
    argvalues=[
        # default exceptions to catch matching
        ErrorCase(type_to_raise=Exception, type_to_catch=Exception, should_match=True),
        ErrorCase(type_to_raise=OSError, type_to_catch=Exception, should_match=True),
        # default exceptions to catch not matching
        ErrorCase(type_to_raise=BaseException, type_to_catch=Exception, should_match=False),
        # raised type the same as specified to catch
        ErrorCase(type_to_raise=Exception, type_to_catch=Exception, should_match=True),
        ErrorCase(type_to_raise=BaseException, type_to_catch=BaseException, should_match=True),
        ErrorCase(type_to_raise=OSError, type_to_catch=OSError, should_match=True),
        # raised type is subclass of to catch
        ErrorCase(type_to_raise=AttributeError, type_to_catch=Exception, should_match=True),
        ErrorCase(type_to_raise=KeyboardInterrupt, type_to_catch=BaseException, should_match=True),
        ErrorCase(type_to_raise=FileExistsError, type_to_catch=OSError, should_match=True),
        # multiple to catch matching
        ErrorCase(type_to_raise=OSError, type_to_catch=(KeyboardInterrupt, Exception), should_match=True),
        ErrorCase(type_to_raise=SystemExit, type_to_catch=(SystemExit, OSError), should_match=True),
        # multiple to catch not matching
        ErrorCase(type_to_raise=AttributeError, type_to_catch=(KeyError, TimeoutError), should_match=False),
        ErrorCase(type_to_raise=KeyboardInterrupt, type_to_catch=(KeyError, TimeoutError), should_match=False),
    ],
)
@pytest.mark.parametrize(argnames="consume", argvalues=[False, True], ids=["propagates", "consumes"])
@pytest.mark.parametrize(argnames="show_traceback", argvalues=[False, True], ids=["no traceback", "with traceback"])
def test_well_everything(
    logger: logging.Logger,
    caplog: pytest.LogCaptureFixture,
    consume: bool,
    case: ErrorCase,
    show_traceback: bool,
) -> None:
    with contextlib.ExitStack() as exit_stack:
        if not consume or not case.should_match:
            # verify that the exception propagates either when it should not match or should not be consumed
            exit_stack.enter_context(pytest.raises(case.type_to_raise, match=re.escape(exception_message)))

        with log_exceptions(
            message=log_message,
            log=logger,
            consume=consume,
            show_traceback=show_traceback,
            exceptions_to_process=case.type_to_catch,
        ):
            to_raise = case.type_to_raise(exception_message)
            raise to_raise

    if not case.should_match:
        assert len(caplog.records) == 0, caplog.records
    else:
        # verify there is only a single log record
        assert len(caplog.records) == 1, caplog.records

        [record] = caplog.records
        expected = f"{log_message}: {case.type_to_raise.__name__}: {exception_message}"

        if show_traceback:
            expected += "\nTraceback "
            # verify the beginning of the log message, the traceback is not fully verified
            assert record.msg.startswith(expected)
        else:
            # verify the complete log message
            assert record.msg == expected
