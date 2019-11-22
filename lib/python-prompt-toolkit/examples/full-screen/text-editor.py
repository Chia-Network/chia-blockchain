#!/usr/bin/env python
"""
A simple example of a Notepad-like text editor.
"""
import datetime
from asyncio import Future, ensure_future

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Float,
    HSplit,
    VSplit,
    Window,
    WindowAlign,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.lexers import DynamicLexer, PygmentsLexer
from prompt_toolkit.search import start_search
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import (
    Button,
    Dialog,
    Label,
    MenuContainer,
    MenuItem,
    SearchToolbar,
    TextArea,
)


class ApplicationState:
    """
    Application state.

    For the simplicity, we store this as a global, but better would be to
    instantiate this as an object and pass at around.
    """
    show_status_bar = True
    current_path = None


def get_statusbar_text():
    return ' Press Ctrl-C to open menu. '


def get_statusbar_right_text():
    return ' {}:{}  '.format(
        text_field.document.cursor_position_row + 1,
        text_field.document.cursor_position_col + 1)


search_toolbar = SearchToolbar()
text_field = TextArea(
    lexer=DynamicLexer(
        lambda: PygmentsLexer.from_filename(
            ApplicationState.current_path or '.txt',
            sync_from_start=False)),
    scrollbar=True,
    line_numbers=True,
    search_field=search_toolbar,
)


class TextInputDialog:
    def __init__(self, title='', label_text='', completer=None):
        self.future = Future()

        def accept_text(buf):
            get_app().layout.focus(ok_button)
            buf.complete_state = None
            return True

        def accept():
            self.future.set_result(self.text_area.text)

        def cancel():
            self.future.set_result(None)

        self.text_area = TextArea(
            completer=completer,
            multiline=False,
            width=D(preferred=40),
            accept_handler=accept_text)

        ok_button = Button(text='OK', handler=accept)
        cancel_button = Button(text='Cancel', handler=cancel)

        self.dialog = Dialog(
            title=title,
            body=HSplit([
                Label(text=label_text),
                self.text_area
            ]),
            buttons=[ok_button, cancel_button],
            width=D(preferred=80),
            modal=True)

    def __pt_container__(self):
        return self.dialog


class MessageDialog:
    def __init__(self, title, text):
        self.future = Future()

        def set_done():
            self.future.set_result(None)

        ok_button = Button(text='OK', handler=(lambda: set_done()))

        self.dialog = Dialog(
            title=title,
            body=HSplit([
                Label(text=text),
            ]),
            buttons=[ok_button],
            width=D(preferred=80),
            modal=True)

    def __pt_container__(self):
        return self.dialog


body = HSplit([
    text_field,
    search_toolbar,
    ConditionalContainer(
        content=VSplit([
            Window(FormattedTextControl(get_statusbar_text), style='class:status'),
            Window(FormattedTextControl(get_statusbar_right_text),
                   style='class:status.right', width=9, align=WindowAlign.RIGHT),
        ], height=1),
        filter=Condition(lambda: ApplicationState.show_status_bar)),
])


# Global key bindings.
bindings = KeyBindings()


@bindings.add('c-c')
def _(event):
    " Focus menu. "
    event.app.layout.focus(root_container.window)


#
# Handlers for menu items.
#

def do_open_file():
    async def coroutine():
        open_dialog = TextInputDialog(
            title='Open file',
            label_text='Enter the path of a file:',
            completer=PathCompleter())

        path = await show_dialog_as_float(open_dialog)
        ApplicationState.current_path = path

        if path is not None:
            try:
                with open(path, 'rb') as f:
                    text_field.text = f.read().decode('utf-8', errors='ignore')
            except IOError as e:
                show_message('Error', '{}'.format(e))

    ensure_future(coroutine())


def do_about():
    show_message('About', 'Text editor demo.\nCreated by Jonathan Slenders.')


def show_message(title, text):
    async def coroutine():
        dialog = MessageDialog(title, text)
        await show_dialog_as_float(dialog)

    ensure_future(coroutine())


async def show_dialog_as_float(dialog):
    " Coroutine. "
    float_ = Float(content=dialog)
    root_container.floats.insert(0, float_)

    app = get_app()

    focused_before = app.layout.current_window
    app.layout.focus(dialog)
    result = await dialog.future
    app.layout.focus(focused_before)

    if float_ in root_container.floats:
        root_container.floats.remove(float_)

    return result


def do_new_file():
    text_field.text = ''


def do_exit():
    get_app().exit()


def do_time_date():
    text = datetime.datetime.now().isoformat()
    text_field.buffer.insert_text(text)


def do_go_to():
    async def coroutine():
        dialog = TextInputDialog(
            title='Go to line',
            label_text='Line number:')

        line_number = await show_dialog_as_float(dialog)

        try:
            line_number = int(line_number)
        except ValueError:
            show_message('Invalid line number')
        else:
            text_field.buffer.cursor_position = \
                text_field.buffer.document.translate_row_col_to_index(line_number - 1, 0)

    ensure_future(coroutine())


def do_undo():
    text_field.buffer.undo()


def do_cut():
    data = text_field.buffer.cut_selection()
    get_app().clipboard.set_data(data)


def do_copy():
    data = text_field.buffer.copy_selection()
    get_app().clipboard.set_data(data)


def do_delete():
    text_field.buffer.cut_selection()


def do_find():
    start_search(text_field.control)


def do_find_next():
    search_state = get_app().current_search_state

    cursor_position = text_field.buffer.get_search_position(
        search_state, include_current_position=False)
    text_field.buffer.cursor_position = cursor_position


def do_paste():
    text_field.buffer.paste_clipboard_data(get_app().clipboard.get_data())


def do_select_all():
    text_field.buffer.cursor_position = 0
    text_field.buffer.start_selection()
    text_field.buffer.cursor_position = len(text_field.buffer.text)


def do_status_bar():
    ApplicationState.show_status_bar = not ApplicationState.show_status_bar


#
# The menu container.
#


root_container = MenuContainer(body=body, menu_items=[
    MenuItem('File', children=[
        MenuItem('New...', handler=do_new_file),
        MenuItem('Open...', handler=do_open_file),
        MenuItem('Save'),
        MenuItem('Save as...'),
        MenuItem('-', disabled=True),
        MenuItem('Exit', handler=do_exit),
        ]),
    MenuItem('Edit', children=[
        MenuItem('Undo', handler=do_undo),
        MenuItem('Cut', handler=do_cut),
        MenuItem('Copy', handler=do_copy),
        MenuItem('Paste', handler=do_paste),
        MenuItem('Delete', handler=do_delete),
        MenuItem('-', disabled=True),
        MenuItem('Find', handler=do_find),
        MenuItem('Find next', handler=do_find_next),
        MenuItem('Replace'),
        MenuItem('Go To', handler=do_go_to),
        MenuItem('Select All', handler=do_select_all),
        MenuItem('Time/Date', handler=do_time_date),
    ]),
    MenuItem('View', children=[
        MenuItem('Status Bar', handler=do_status_bar),
    ]),
    MenuItem('Info', children=[
        MenuItem('About', handler=do_about),
    ]),
], floats=[
    Float(xcursor=True,
          ycursor=True,
          content=CompletionsMenu(
              max_height=16,
              scroll_offset=1)),
], key_bindings=bindings)


style = Style.from_dict({
    'status': 'reverse',
    'shadow': 'bg:#440044',
})


layout = Layout(
    root_container,
    focused_element=text_field)


application = Application(
    layout=layout,
    enable_page_navigation_bindings=True,
    style=style,
    mouse_support=True,
    full_screen=True)


def run():
    application.run()


if __name__ == '__main__':
    run()
