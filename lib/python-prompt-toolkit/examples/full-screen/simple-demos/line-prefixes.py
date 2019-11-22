#!/usr/bin/env python
"""
An example of a BufferControl in a full screen layout that offers auto
completion.

Important is to make sure that there is a `CompletionsMenu` in the layout,
otherwise the completions won't be visible.
"""
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (
    Float,
    FloatContainer,
    HSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.menus import CompletionsMenu

LIPSUM = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit.  Maecenas
quis interdum enim. Nam viverra, mauris et blandit malesuada, ante est bibendum
mauris, ac dignissim dui tellus quis ligula. Aenean condimentum leo at
dignissim placerat. In vel dictum ex, vulputate accumsan mi. Donec ut quam
placerat massa tempor elementum. Sed tristique mauris ac suscipit euismod. Ut
tempus vehicula augue non venenatis. Mauris aliquam velit turpis, nec congue
risus aliquam sit amet. Pellentesque blandit scelerisque felis, faucibus
consequat ante. Curabitur tempor tortor a imperdiet tincidunt. Nam sed justo
sit amet odio bibendum congue. Quisque varius ligula nec ligula gravida, sed
convallis augue faucibus. Nunc ornare pharetra bibendum. Praesent blandit ex
quis sodales maximus."""


def get_line_prefix(lineno, wrap_count):
    if wrap_count == 0:
        return HTML('[%s] <style bg="orange" fg="black">--&gt;</style> ') % lineno

    text = str(lineno) + '-' + '*' * (lineno // 2) + ': '
    return HTML('[%s.%s] <style bg="ansigreen" fg="ansiblack">%s</style>') % (
        lineno, wrap_count, text)


# Global wrap lines flag.
wrap_lines = True


# The layout
buff = Buffer(complete_while_typing=True)
buff.text = LIPSUM


body = FloatContainer(
    content=HSplit([
        Window(FormattedTextControl(
                   'Press "q" to quit. Press "w" to enable/disable wrapping.'),
               height=1, style='reverse'),
        Window(BufferControl(buffer=buff), get_line_prefix=get_line_prefix,
               wrap_lines=Condition(lambda: wrap_lines)),
    ]),
    floats=[
        Float(xcursor=True,
              ycursor=True,
              content=CompletionsMenu(max_height=16, scroll_offset=1))
    ]
)


# Key bindings
kb = KeyBindings()


@kb.add('q')
@kb.add('c-c')
def _(event):
    " Quit application. "
    event.app.exit()

@kb.add('w')
def _(event):
    " Disable/enable wrapping. "
    global wrap_lines
    wrap_lines = not wrap_lines


# The `Application`
application = Application(
    layout=Layout(body),
    key_bindings=kb,
    full_screen=True,
    mouse_support=True)


def run():
    application.run()


if __name__ == '__main__':
    run()
