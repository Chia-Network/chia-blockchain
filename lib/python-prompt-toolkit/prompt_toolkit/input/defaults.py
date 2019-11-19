import sys
from typing import Optional, TextIO

from prompt_toolkit.utils import is_windows

from .base import Input

__all__ = [
    'create_input',
    'create_pipe_input',
]


def create_input(stdin: Optional[TextIO] = None) -> Input:
    stdin = stdin or sys.stdin

    if is_windows():
        from .win32 import Win32Input
        return Win32Input(stdin)
    else:
        from .vt100 import Vt100Input
        return Vt100Input(stdin)


def create_pipe_input() -> Input:
    """
    Create an input pipe.
    This is mostly useful for unit testing.
    """
    if is_windows():
        from .win32_pipe import Win32PipeInput
        return Win32PipeInput()
    else:
        from .posix_pipe import PosixPipeInput
        return PosixPipeInput()
