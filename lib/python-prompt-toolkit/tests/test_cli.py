# encoding: utf-8
"""
These are almost end-to-end tests. They create a Prompt, feed it with some
input and check the result.
"""
from __future__ import unicode_literals

from functools import partial

import pytest

from prompt_toolkit.clipboard import ClipboardData, InMemoryClipboard
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.filters import ViInsertMode
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.input.vt100_parser import ANSI_SEQUENCES
from prompt_toolkit.key_binding.bindings.named_commands import prefix_meta
from prompt_toolkit.key_binding.key_bindings import KeyBindings
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.shortcuts import PromptSession


def _history():
    h = InMemoryHistory()
    h.append_string('line1 first input')
    h.append_string('line2 second input')
    h.append_string('line3 third input')
    return h


def _feed_cli_with_input(
        text, editing_mode=EditingMode.EMACS, clipboard=None, history=None,
        multiline=False, check_line_ending=True, key_bindings=None):
    """
    Create a Prompt, feed it with the given user input and return the CLI
    object.

    This returns a (result, Application) tuple.
    """
    # If the given text doesn't end with a newline, the interface won't finish.
    if check_line_ending:
        assert text.endswith('\r')

    inp = create_pipe_input()

    try:
        inp.send_text(text)
        session = PromptSession(
            input=inp, output=DummyOutput(), editing_mode=editing_mode,
            history=history, multiline=multiline, clipboard=clipboard,
            key_bindings=key_bindings)

        result = session.prompt()
        return session.default_buffer.document, session.app

    finally:
        inp.close()


def test_simple_text_input():
    # Simple text input, followed by enter.
    result, cli = _feed_cli_with_input('hello\r')
    assert result.text == 'hello'
    assert cli.current_buffer.text == 'hello'


def test_emacs_cursor_movements():
    """
    Test cursor movements with Emacs key bindings.
    """
    # ControlA (beginning-of-line)
    result, cli = _feed_cli_with_input('hello\x01X\r')
    assert result.text == 'Xhello'

    # ControlE (end-of-line)
    result, cli = _feed_cli_with_input('hello\x01X\x05Y\r')
    assert result.text == 'XhelloY'

    # ControlH or \b
    result, cli = _feed_cli_with_input('hello\x08X\r')
    assert result.text == 'hellX'

    # Delete.  (Left, left, delete)
    result, cli = _feed_cli_with_input('hello\x1b[D\x1b[D\x1b[3~\r')
    assert result.text == 'helo'

    # Left.
    result, cli = _feed_cli_with_input('hello\x1b[DX\r')
    assert result.text == 'hellXo'

    # ControlA, right
    result, cli = _feed_cli_with_input('hello\x01\x1b[CX\r')
    assert result.text == 'hXello'

    # ControlB (backward-char)
    result, cli = _feed_cli_with_input('hello\x02X\r')
    assert result.text == 'hellXo'

    # ControlF (forward-char)
    result, cli = _feed_cli_with_input('hello\x01\x06X\r')
    assert result.text == 'hXello'

    # ControlD: delete after cursor.
    result, cli = _feed_cli_with_input('hello\x01\x04\r')
    assert result.text == 'ello'

    # ControlD at the end of the input ssshould not do anything.
    result, cli = _feed_cli_with_input('hello\x04\r')
    assert result.text == 'hello'

    # Left, Left, ControlK  (kill-line)
    result, cli = _feed_cli_with_input('hello\x1b[D\x1b[D\x0b\r')
    assert result.text == 'hel'

    # Left, Left Esc- ControlK (kill-line, but negative)
    result, cli = _feed_cli_with_input('hello\x1b[D\x1b[D\x1b-\x0b\r')
    assert result.text == 'lo'

    # ControlL: should not influence the result.
    result, cli = _feed_cli_with_input('hello\x0c\r')
    assert result.text == 'hello'

    # ControlRight (forward-word)
    result, cli = _feed_cli_with_input('hello world\x01X\x1b[1;5CY\r')
    assert result.text == 'XhelloY world'

    # ContrlolLeft (backward-word)
    result, cli = _feed_cli_with_input('hello world\x1b[1;5DY\r')
    assert result.text == 'hello Yworld'

    # <esc>-f with argument. (forward-word)
    result, cli = _feed_cli_with_input('hello world abc def\x01\x1b3\x1bfX\r')
    assert result.text == 'hello world abcX def'

    # <esc>-f with negative argument. (forward-word)
    result, cli = _feed_cli_with_input('hello world abc def\x1b-\x1b3\x1bfX\r')
    assert result.text == 'hello Xworld abc def'

    # <esc>-b with argument. (backward-word)
    result, cli = _feed_cli_with_input('hello world abc def\x1b3\x1bbX\r')
    assert result.text == 'hello Xworld abc def'

    # <esc>-b with negative argument. (backward-word)
    result, cli = _feed_cli_with_input('hello world abc def\x01\x1b-\x1b3\x1bbX\r')
    assert result.text == 'hello world abc Xdef'

    # ControlW (kill-word / unix-word-rubout)
    result, cli = _feed_cli_with_input('hello world\x17\r')
    assert result.text == 'hello '
    assert cli.clipboard.get_data().text == 'world'

    result, cli = _feed_cli_with_input('test hello world\x1b2\x17\r')
    assert result.text == 'test '

    # Escape Backspace (unix-word-rubout)
    result, cli = _feed_cli_with_input('hello world\x1b\x7f\r')
    assert result.text == 'hello '
    assert cli.clipboard.get_data().text == 'world'

    result, cli = _feed_cli_with_input('hello world\x1b\x08\r')
    assert result.text == 'hello '
    assert cli.clipboard.get_data().text == 'world'

    # Backspace (backward-delete-char)
    result, cli = _feed_cli_with_input('hello world\x7f\r')
    assert result.text == 'hello worl'
    assert result.cursor_position == len('hello worl')

    result, cli = _feed_cli_with_input('hello world\x08\r')
    assert result.text == 'hello worl'
    assert result.cursor_position == len('hello worl')

    # Delete (delete-char)
    result, cli = _feed_cli_with_input('hello world\x01\x1b[3~\r')
    assert result.text == 'ello world'
    assert result.cursor_position == 0

    # Escape-\\ (delete-horizontal-space)
    result, cli = _feed_cli_with_input('hello     world\x1b8\x02\x1b\\\r')
    assert result.text == 'helloworld'
    assert result.cursor_position == len('hello')


def test_emacs_kill_multiple_words_and_paste():
    # Using control-w twice should place both words on the clipboard.
    result, cli = _feed_cli_with_input(
        'hello world test'
        '\x17\x17'  # Twice c-w.
        '--\x19\x19\r'  # Twice c-y.
    )
    assert result.text == 'hello --world testworld test'
    assert cli.clipboard.get_data().text == 'world test'

    # Using alt-d twice should place both words on the clipboard.
    result, cli = _feed_cli_with_input(
        'hello world test'
        '\x1bb\x1bb'  # Twice left.
        '\x1bd\x1bd'  # Twice kill-word.
        'abc'
        '\x19'  # Paste.
        '\r'
    )
    assert result.text == 'hello abcworld test'
    assert cli.clipboard.get_data().text == 'world test'


def test_interrupts():
    # ControlC: raise KeyboardInterrupt.
    with pytest.raises(KeyboardInterrupt):
        result, cli = _feed_cli_with_input('hello\x03\r')

    with pytest.raises(KeyboardInterrupt):
        result, cli = _feed_cli_with_input('hello\x03\r')

    # ControlD without any input: raises EOFError.
    with pytest.raises(EOFError):
        result, cli = _feed_cli_with_input('\x04\r')


def test_emacs_yank():
    # ControlY (yank)
    c = InMemoryClipboard(ClipboardData('XYZ'))
    result, cli = _feed_cli_with_input('hello\x02\x19\r', clipboard=c)
    assert result.text == 'hellXYZo'
    assert result.cursor_position == len('hellXYZ')


def test_quoted_insert():
    # ControlQ - ControlB (quoted-insert)
    result, cli = _feed_cli_with_input('hello\x11\x02\r')
    assert result.text == 'hello\x02'


def test_transformations():
    # Meta-c (capitalize-word)
    result, cli = _feed_cli_with_input('hello world\01\x1bc\r')
    assert result.text == 'Hello world'
    assert result.cursor_position == len('Hello')

    # Meta-u (uppercase-word)
    result, cli = _feed_cli_with_input('hello world\01\x1bu\r')
    assert result.text == 'HELLO world'
    assert result.cursor_position == len('Hello')

    # Meta-u (downcase-word)
    result, cli = _feed_cli_with_input('HELLO WORLD\01\x1bl\r')
    assert result.text == 'hello WORLD'
    assert result.cursor_position == len('Hello')

    # ControlT (transpose-chars)
    result, cli = _feed_cli_with_input('hello\x14\r')
    assert result.text == 'helol'
    assert result.cursor_position == len('hello')

    # Left, Left, Control-T (transpose-chars)
    result, cli = _feed_cli_with_input('abcde\x1b[D\x1b[D\x14\r')
    assert result.text == 'abdce'
    assert result.cursor_position == len('abcd')


def test_emacs_other_bindings():
    # Transpose characters.
    result, cli = _feed_cli_with_input('abcde\x14X\r')  # Ctrl-T
    assert result.text == 'abcedX'

    # Left, Left, Transpose. (This is slightly different.)
    result, cli = _feed_cli_with_input('abcde\x1b[D\x1b[D\x14X\r')
    assert result.text == 'abdcXe'

    # Clear before cursor.
    result, cli = _feed_cli_with_input('hello\x1b[D\x1b[D\x15X\r')
    assert result.text == 'Xlo'

    # unix-word-rubout: delete word before the cursor.
    # (ControlW).
    result, cli = _feed_cli_with_input('hello world test\x17X\r')
    assert result.text == 'hello world X'

    result, cli = _feed_cli_with_input('hello world /some/very/long/path\x17X\r')
    assert result.text == 'hello world X'

    # (with argument.)
    result, cli = _feed_cli_with_input('hello world test\x1b2\x17X\r')
    assert result.text == 'hello X'

    result, cli = _feed_cli_with_input('hello world /some/very/long/path\x1b2\x17X\r')
    assert result.text == 'hello X'

    # backward-kill-word: delete word before the cursor.
    # (Esc-ControlH).
    result, cli = _feed_cli_with_input('hello world /some/very/long/path\x1b\x08X\r')
    assert result.text == 'hello world /some/very/long/X'

    # (with arguments.)
    result, cli = _feed_cli_with_input('hello world /some/very/long/path\x1b3\x1b\x08X\r')
    assert result.text == 'hello world /some/very/X'


def test_controlx_controlx():
    # At the end: go to the start of the line.
    result, cli = _feed_cli_with_input('hello world\x18\x18X\r')
    assert result.text == 'Xhello world'
    assert result.cursor_position == 1

    # At the start: go to the end of the line.
    result, cli = _feed_cli_with_input('hello world\x01\x18\x18X\r')
    assert result.text == 'hello worldX'

    # Left, Left Control-X Control-X: go to the end of the line.
    result, cli = _feed_cli_with_input('hello world\x1b[D\x1b[D\x18\x18X\r')
    assert result.text == 'hello worldX'


def test_emacs_history_bindings():
    # Adding a new item to the history.
    history = _history()
    result, cli = _feed_cli_with_input('new input\r', history=history)
    assert result.text == 'new input'
    history.get_strings()[-1] == 'new input'

    # Go up in history, and accept the last item.
    result, cli = _feed_cli_with_input('hello\x1b[A\r', history=history)
    assert result.text == 'new input'

    # Esc< (beginning-of-history)
    result, cli = _feed_cli_with_input('hello\x1b<\r', history=history)
    assert result.text == 'line1 first input'

    # Esc> (end-of-history)
    result, cli = _feed_cli_with_input('another item\x1b[A\x1b[a\x1b>\r', history=history)
    assert result.text == 'another item'

    # ControlUp (previous-history)
    result, cli = _feed_cli_with_input('\x1b[1;5A\r', history=history)
    assert result.text == 'another item'

    # Esc< ControlDown (beginning-of-history, next-history)
    result, cli = _feed_cli_with_input('\x1b<\x1b[1;5B\r', history=history)
    assert result.text == 'line2 second input'


def test_emacs_reverse_search():
    history = _history()

    # ControlR  (reverse-search-history)
    result, cli = _feed_cli_with_input('\x12input\r\r', history=history)
    assert result.text == 'line3 third input'

    # Hitting ControlR twice.
    result, cli = _feed_cli_with_input('\x12input\x12\r\r', history=history)
    assert result.text == 'line2 second input'


def test_emacs_arguments():
    """
    Test various combinations of arguments in Emacs mode.
    """
    # esc 4
    result, cli = _feed_cli_with_input('\x1b4x\r')
    assert result.text == 'xxxx'

    # esc 4 4
    result, cli = _feed_cli_with_input('\x1b44x\r')
    assert result.text == 'x' * 44

    # esc 4 esc 4
    result, cli = _feed_cli_with_input('\x1b4\x1b4x\r')
    assert result.text == 'x' * 44

    # esc - right (-1 position to the right, equals 1 to the left.)
    result, cli = _feed_cli_with_input('aaaa\x1b-\x1b[Cbbbb\r')
    assert result.text == 'aaabbbba'

    # esc - 3 right
    result, cli = _feed_cli_with_input('aaaa\x1b-3\x1b[Cbbbb\r')
    assert result.text == 'abbbbaaa'

    # esc - - - 3 right
    result, cli = _feed_cli_with_input('aaaa\x1b---3\x1b[Cbbbb\r')
    assert result.text == 'abbbbaaa'


def test_emacs_arguments_for_all_commands():
    """
    Test all Emacs commands with Meta-[0-9] arguments (both positive and
    negative). No one should crash.
    """
    for key in ANSI_SEQUENCES:
        # Ignore BracketedPaste. This would hang forever, because it waits for
        # the end sequence.
        if key != '\x1b[200~':
            try:
                # Note: we add an 'X' after the key, because Ctrl-Q (quoted-insert)
                # expects something to follow. We add an additional \r, because
                # Ctrl-R and Ctrl-S (reverse-search) expect that.
                result, cli = _feed_cli_with_input(
                    'hello\x1b4' + key + 'X\r\r')

                result, cli = _feed_cli_with_input(
                    'hello\x1b-' + key + 'X\r\r')
            except KeyboardInterrupt:
                # This exception should only be raised for Ctrl-C
                assert key == '\x03'


def test_emacs_kill_ring():
    operations = (
        # abc ControlA ControlK
        'abc\x01\x0b'

        # def ControlA ControlK
        'def\x01\x0b'

        # ghi ControlA ControlK
        'ghi\x01\x0b'

        # ControlY (yank)
        '\x19'
    )

    result, cli = _feed_cli_with_input(operations + '\r')
    assert result.text == 'ghi'

    result, cli = _feed_cli_with_input(operations + '\x1by\r')
    assert result.text == 'def'

    result, cli = _feed_cli_with_input(operations + '\x1by\x1by\r')
    assert result.text == 'abc'

    result, cli = _feed_cli_with_input(operations + '\x1by\x1by\x1by\r')
    assert result.text == 'ghi'


def test_emacs_selection():
    # Copy/paste empty selection should not do anything.
    operations = (
        'hello'

        # Twice left.
        '\x1b[D\x1b[D'

        # Control-Space
        '\x00'

        # ControlW (cut)
        '\x17'

        # ControlY twice. (paste twice)
        '\x19\x19\r'
    )

    result, cli = _feed_cli_with_input(operations)
    assert result.text == 'hello'

    # Copy/paste one character.
    operations = (
        'hello'

        # Twice left.
        '\x1b[D\x1b[D'

        # Control-Space
        '\x00'

        # Right.
        '\x1b[C'

        # ControlW (cut)
        '\x17'

        # ControlA (Home).
        '\x01'

        # ControlY (paste)
        '\x19\r'
    )

    result, cli = _feed_cli_with_input(operations)
    assert result.text == 'lhelo'


def test_emacs_insert_comment():
    # Test insert-comment (M-#) binding.
    result, cli = _feed_cli_with_input('hello\x1b#', check_line_ending=False)
    assert result.text == '#hello'

    result, cli = _feed_cli_with_input(
        'hello\rworld\x1b#', check_line_ending=False, multiline=True)
    assert result.text == '#hello\n#world'


def test_emacs_record_macro():
    operations = (
        '  '
        '\x18('  # Start recording macro. C-X(
        'hello'
        '\x18)'  # Stop recording macro.
        '  '
        '\x18e'  # Execute macro.
        '\x18e'  # Execute macro.
        '\r'
    )

    result, cli = _feed_cli_with_input(operations)
    assert result.text == '  hello  hellohello'


def test_emacs_nested_macro():
    " Test calling the macro within a macro. "
    # Calling a macro within a macro should take the previous recording (if one
    # exists), not the one that is in progress.
    operations = (
        '\x18('  # Start recording macro. C-X(
        'hello'
        '\x18e'  # Execute macro.
        '\x18)'  # Stop recording macro.
        '\x18e'  # Execute macro.
        '\r'
    )

    result, cli = _feed_cli_with_input(operations)
    assert result.text == 'hellohello'

    operations = (
        '\x18('  # Start recording macro. C-X(
        'hello'
        '\x18)'  # Stop recording macro.
        '\x18('  # Start recording macro. C-X(
        '\x18e'  # Execute macro.
        'world'
        '\x18)'  # Stop recording macro.
        '\x01\x0b'  # Delete all (c-a c-k).
        '\x18e'  # Execute macro.
        '\r'
    )

    result, cli = _feed_cli_with_input(operations)
    assert result.text == 'helloworld'


def test_prefix_meta():
    # Test the prefix-meta command.
    b = KeyBindings()
    b.add('j', 'j', filter=ViInsertMode())(prefix_meta)

    result, cli = _feed_cli_with_input(
        'hellojjIX\r', key_bindings=b, editing_mode=EditingMode.VI)
    assert result.text == 'Xhello'


def test_bracketed_paste():
    result, cli = _feed_cli_with_input('\x1b[200~hello world\x1b[201~\r')
    assert result.text == 'hello world'

    result, cli = _feed_cli_with_input('\x1b[200~hello\rworld\x1b[201~\x1b\r')
    assert result.text == 'hello\nworld'

    # With \r\n endings.
    result, cli = _feed_cli_with_input('\x1b[200~hello\r\nworld\x1b[201~\x1b\r')
    assert result.text == 'hello\nworld'

    # With \n endings.
    result, cli = _feed_cli_with_input('\x1b[200~hello\nworld\x1b[201~\x1b\r')
    assert result.text == 'hello\nworld'


def test_vi_cursor_movements():
    """
    Test cursor movements with Vi key bindings.
    """
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI)

    result, cli = feed('\x1b\r')
    assert result.text == ''
    assert cli.editing_mode == EditingMode.VI

    # Esc h a X
    result, cli = feed('hello\x1bhaX\r')
    assert result.text == 'hellXo'

    # Esc I X
    result, cli = feed('hello\x1bIX\r')
    assert result.text == 'Xhello'

    # Esc I X
    result, cli = feed('hello\x1bIX\r')
    assert result.text == 'Xhello'

    # Esc 2hiX
    result, cli = feed('hello\x1b2hiX\r')
    assert result.text == 'heXllo'

    # Esc 2h2liX
    result, cli = feed('hello\x1b2h2liX\r')
    assert result.text == 'hellXo'

    # Esc \b\b
    result, cli = feed('hello\b\b\r')
    assert result.text == 'hel'

    # Esc \b\b
    result, cli = feed('hello\b\b\r')
    assert result.text == 'hel'

    # Esc 2h D
    result, cli = feed('hello\x1b2hD\r')
    assert result.text == 'he'

    # Esc 2h rX \r
    result, cli = feed('hello\x1b2hrX\r')
    assert result.text == 'heXlo'


def test_vi_operators():
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI)

    # Esc g~0
    result, cli = feed('hello\x1bg~0\r')
    assert result.text == 'HELLo'

    # Esc gU0
    result, cli = feed('hello\x1bgU0\r')
    assert result.text == 'HELLo'

    # Esc d0
    result, cli = feed('hello\x1bd0\r')
    assert result.text == 'o'


def test_vi_text_objects():
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI)

    # Esc gUgg
    result, cli = feed('hello\x1bgUgg\r')
    assert result.text == 'HELLO'

    # Esc gUU
    result, cli = feed('hello\x1bgUU\r')
    assert result.text == 'HELLO'

    # Esc di(
    result, cli = feed('before(inside)after\x1b8hdi(\r')
    assert result.text == 'before()after'

    # Esc di[
    result, cli = feed('before[inside]after\x1b8hdi[\r')
    assert result.text == 'before[]after'

    # Esc da(
    result, cli = feed('before(inside)after\x1b8hda(\r')
    assert result.text == 'beforeafter'


def test_vi_digraphs():
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI)

    # C-K o/
    result, cli = feed('hello\x0bo/\r')
    assert result.text == 'helloø'

    # C-K /o  (reversed input.)
    result, cli = feed('hello\x0b/o\r')
    assert result.text == 'helloø'

    # C-K e:
    result, cli = feed('hello\x0be:\r')
    assert result.text == 'helloë'

    # C-K xxy (Unknown digraph.)
    result, cli = feed('hello\x0bxxy\r')
    assert result.text == 'helloy'


def test_vi_block_editing():
    " Test Vi Control-V style block insertion. "
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI,
                   multiline=True)

    operations = (
        # Six lines of text.
        '-line1\r-line2\r-line3\r-line4\r-line5\r-line6'
        # Go to the second character of the second line.
        '\x1bkkkkkkkj0l'
        # Enter Visual block mode.
        '\x16'
        # Go down two more lines.
        'jj'
        # Go 3 characters to the right.
        'lll'
        # Go to insert mode.
        'insert'  # (Will be replaced.)
        # Insert stars.
        '***'
        # Escape again.
        '\x1b\r')

    # Control-I
    result, cli = feed(operations.replace('insert', 'I'))

    assert (result.text ==
            '-line1\n-***line2\n-***line3\n-***line4\n-line5\n-line6')

    # Control-A
    result, cli = feed(operations.replace('insert', 'A'))

    assert (result.text ==
            '-line1\n-line***2\n-line***3\n-line***4\n-line5\n-line6')


def test_vi_block_editing_empty_lines():
    " Test block editing on empty lines. "
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI,
                   multiline=True)

    operations = (
        # Six empty lines.
        '\r\r\r\r\r'
        # Go to beginning of the document.
        '\x1bgg'
        # Enter Visual block mode.
        '\x16'
        # Go down two more lines.
        'jj'
        # Go 3 characters to the right.
        'lll'
        # Go to insert mode.
        'insert'  # (Will be replaced.)
        # Insert stars.
        '***'
        # Escape again.
        '\x1b\r')

    # Control-I
    result, cli = feed(operations.replace('insert', 'I'))

    assert result.text == '***\n***\n***\n\n\n'

    # Control-A
    result, cli = feed(operations.replace('insert', 'A'))

    assert result.text == '***\n***\n***\n\n\n'


def test_vi_visual_line_copy():
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI,
                   multiline=True)

    operations = (
        # Three lines of text.
        '-line1\r-line2\r-line3\r-line4\r-line5\r-line6'
        # Go to the second character of the second line.
        '\x1bkkkkkkkj0l'
        # Enter Visual linemode.
        'V'
        # Go down one line.
        'j'
        # Go 3 characters to the right (should not do much).
        'lll'
        # Copy this block.
        'y'
        # Go down one line.
        'j'
        # Insert block twice.
        '2p'
        # Escape again.
        '\x1b\r')

    result, cli = feed(operations)

    assert (result.text ==
            '-line1\n-line2\n-line3\n-line4\n-line2\n-line3\n-line2\n-line3\n-line5\n-line6')


def test_vi_visual_empty_line():
    """
    Test edge case with an empty line in Visual-line mode.
    """
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI,
                   multiline=True)

    # 1. Delete first two lines.
    operations = (
        # Three lines of text. The middle one is empty.
        'hello\r\rworld'
        # Go to the start.
        '\x1bgg'
        # Visual line and move down.
        'Vj'
        # Delete.
        'd\r')
    result, cli = feed(operations)
    assert result.text == 'world'

    # 1. Delete middle line.
    operations = (
        # Three lines of text. The middle one is empty.
        'hello\r\rworld'
        # Go to middle line.
        '\x1bggj'
        # Delete line
        'Vd\r')

    result, cli = feed(operations)
    assert result.text == 'hello\nworld'


def test_vi_character_delete_after_cursor():
    " Test 'x' keypress. "
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI,
                   multiline=True)

    # Delete one character.
    result, cli = feed('abcd\x1bHx\r')
    assert result.text == 'bcd'

    # Delete multiple character.s
    result, cli = feed('abcd\x1bH3x\r')
    assert result.text == 'd'

    # Delete on empty line.
    result, cli = feed('\x1bo\x1bo\x1bggx\r')
    assert result.text == '\n\n'

    # Delete multiple on empty line.
    result, cli = feed('\x1bo\x1bo\x1bgg10x\r')
    assert result.text == '\n\n'

    # Delete multiple on empty line.
    result, cli = feed('hello\x1bo\x1bo\x1bgg3x\r')
    assert result.text == 'lo\n\n'


def test_vi_character_delete_before_cursor():
    " Test 'X' keypress. "
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI,
                   multiline=True)

    # Delete one character.
    result, cli = feed('abcd\x1bX\r')
    assert result.text == 'abd'

    # Delete multiple character.
    result, cli = feed('hello world\x1b3X\r')
    assert result.text == 'hello wd'

    # Delete multiple character on multiple lines.
    result, cli = feed('hello\x1boworld\x1bgg$3X\r')
    assert result.text == 'ho\nworld'

    result, cli = feed('hello\x1boworld\x1b100X\r')
    assert result.text == 'hello\nd'

    # Delete on empty line.
    result, cli = feed('\x1bo\x1bo\x1b10X\r')
    assert result.text == '\n\n'


def test_vi_character_paste():
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI)

    # Test 'p' character paste.
    result, cli = feed('abcde\x1bhhxp\r')
    assert result.text == 'abdce'
    assert result.cursor_position == 3

    # Test 'P' character paste.
    result, cli = feed('abcde\x1bhhxP\r')
    assert result.text == 'abcde'
    assert result.cursor_position == 2


def test_vi_temp_navigation_mode():
    """
    Test c-o binding: go for one action into navigation mode.
    """
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI)

    result, cli = feed(
        'abcde'
        '\x0f'  # c-o
        '3h'  # 3 times to the left.
        'x\r')
    assert result.text == 'axbcde'
    assert result.cursor_position == 2

    result, cli = feed(
        'abcde'
        '\x0f'  # c-o
        'b'  # One word backwards.
        'x\r')
    assert result.text == 'xabcde'
    assert result.cursor_position == 1

    # In replace mode
    result, cli = feed(
        'abcdef'
        '\x1b'  # Navigation mode.
        '0l'  # Start of line, one character to the right.
        'R'  # Replace mode
        '78'
        '\x0f'  # c-o
        'l'  # One character forwards.
        '9\r')
    assert result.text == 'a78d9f'
    assert result.cursor_position == 5


def test_vi_macros():
    feed = partial(_feed_cli_with_input, editing_mode=EditingMode.VI)

    # Record and execute macro.
    result, cli = feed('\x1bqcahello\x1bq@c\r')
    assert result.text == 'hellohello'
    assert result.cursor_position == 9

    # Running unknown macro.
    result, cli = feed('\x1b@d\r')
    assert result.text == ''
    assert result.cursor_position == 0

    # When a macro is called within a macro.
    # It shouldn't result in eternal recursion.
    result, cli = feed('\x1bqxahello\x1b@xq@x\r')
    assert result.text == 'hellohello'
    assert result.cursor_position == 9

    # Nested macros.
    result, cli = feed(
        # Define macro 'x'.
        '\x1bqxahello\x1bq'

        # Define macro 'y' which calls 'x'.
        'qya\x1b@xaworld\x1bq'

        # Delete line.
        '2dd'

        # Execute 'y'
        '@y\r')

    assert result.text == 'helloworld'


def test_accept_default():
    """
    Test `prompt(accept_default=True)`.
    """
    inp = create_pipe_input()

    session = PromptSession(input=inp, output=DummyOutput())
    result = session.prompt(default='hello', accept_default=True)
    assert result == 'hello'

    # Test calling prompt() for a second time. (We had an issue where the
    # prompt reset between calls happened at the wrong time, breaking this.)
    result = session.prompt(default='world', accept_default=True)
    assert result == 'world'

    inp.close()
