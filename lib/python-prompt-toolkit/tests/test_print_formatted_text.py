"""
Test the `print` function.
"""
from __future__ import print_function, unicode_literals

import pytest

from prompt_toolkit import print_formatted_text as pt_print
from prompt_toolkit.formatted_text import (
    HTML,
    FormattedText,
    to_formatted_text,
)
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import is_windows


class _Capture:
    " Emulate an stdout object. "
    encoding = 'utf-8'

    def __init__(self):
        self._data = []

    def write(self, data):
        self._data.append(data)

    @property
    def data(self):
        return b''.join(self._data)

    def flush(self):
        pass

    def isatty(self):
        return True

    def fileno(self):
        # File descriptor is not used for printing formatted text.
        # (It is only needed for getting the terminal size.)
        return -1


@pytest.mark.skipif(
    is_windows(), reason="Doesn't run on Windows yet.")
def test_print_formatted_text():
    f = _Capture()
    pt_print([('', 'hello'), ('', 'world')], file=f)
    assert b'hello' in f.data
    assert b'world' in f.data

@pytest.mark.skipif(
    is_windows(), reason="Doesn't run on Windows yet.")
def test_print_formatted_text_backslash_r():
    f = _Capture()
    pt_print('hello\r\n', file=f)
    assert b'hello' in f.data

@pytest.mark.skipif(
    is_windows(), reason="Doesn't run on Windows yet.")
def test_with_style():
    f = _Capture()
    style = Style.from_dict({
        'hello': '#ff0066',
        'world': '#44ff44 italic',
    })
    tokens = FormattedText([
        ('class:hello', 'Hello '),
        ('class:world', 'world'),
    ])
    pt_print(tokens, style=style, file=f)
    assert b'\x1b[0;38;5;197mHello' in f.data
    assert b'\x1b[0;38;5;83;3mworld' in f.data


@pytest.mark.skipif(
    is_windows(), reason="Doesn't run on Windows yet.")
def test_with_style():
    """
    Text `print_formatted_text` with `HTML` wrapped in `to_formatted_text`.
    """
    f = _Capture()

    html = HTML('<ansigreen>hello</ansigreen> <b>world</b>')
    formatted_text = to_formatted_text(html, style='class:myhtml')
    pt_print(formatted_text, file=f)

    assert f.data == \
        b'\x1b[0m\x1b[?7h\x1b[0;32mhello\x1b[0m \x1b[0;1mworld\x1b[0m\r\n\x1b[0m'
