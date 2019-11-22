#!/usr/bin/env python
"""
Horizontal align demo with HSplit.
"""
from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (
    HorizontalAlign,
    HSplit,
    VerticalAlign,
    VSplit,
    Window,
    WindowAlign,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import Frame

TITLE = HTML(""" <u>HSplit HorizontalAlign</u> example.
 Press <b>'q'</b> to quit.""")

LIPSUM = """\
Lorem ipsum dolor
sit amet, consectetur
adipiscing elit.
Maecenas quis
interdum enim."""


# 1. The layout
body = HSplit([
    Frame(
        Window(FormattedTextControl(TITLE), height=2), style='bg:#88ff88 #000000'),
    HSplit([
        # Left alignment.
        VSplit([
            Window(FormattedTextControl(HTML('<u>LEFT</u>')), width=10,
                   ignore_content_width=True, style='bg:#ff3333 ansiblack', align=WindowAlign.CENTER),
            VSplit([
                Window(FormattedTextControl(LIPSUM), height=4, style='bg:#444488'),
                Window(FormattedTextControl(LIPSUM), height=4, style='bg:#444488'),
                Window(FormattedTextControl(LIPSUM), height=4, style='bg:#444488'),
            ], padding=1, padding_style='bg:#888888', align=HorizontalAlign.LEFT, height=5, padding_char='|'),
        ]),
        # Center alignment.
        VSplit([
            Window(FormattedTextControl(HTML('<u>CENTER</u>')), width=10,
                   ignore_content_width=True, style='bg:#ff3333 ansiblack', align=WindowAlign.CENTER),
            VSplit([
                Window(FormattedTextControl(LIPSUM), height=4, style='bg:#444488'),
                Window(FormattedTextControl(LIPSUM), height=4, style='bg:#444488'),
                Window(FormattedTextControl(LIPSUM), height=4, style='bg:#444488'),
            ], padding=1, padding_style='bg:#888888', align=HorizontalAlign.CENTER, height=5, padding_char='|'),
        ]),
        # Right alignment.
        VSplit([
            Window(FormattedTextControl(HTML('<u>RIGHT</u>')), width=10,
                   ignore_content_width=True, style='bg:#ff3333 ansiblack', align=WindowAlign.CENTER),
            VSplit([
                Window(FormattedTextControl(LIPSUM), height=4, style='bg:#444488'),
                Window(FormattedTextControl(LIPSUM), height=4, style='bg:#444488'),
                Window(FormattedTextControl(LIPSUM), height=4, style='bg:#444488'),
            ], padding=1, padding_style='bg:#888888', align=HorizontalAlign.RIGHT, height=5, padding_char='|'),
        ]),
        # Justify
        VSplit([
            Window(FormattedTextControl(HTML('<u>JUSTIFY</u>')), width=10,
                   ignore_content_width=True, style='bg:#ff3333 ansiblack', align=WindowAlign.CENTER),
            VSplit([
                Window(FormattedTextControl(LIPSUM), style='bg:#444488'),
                Window(FormattedTextControl(LIPSUM), style='bg:#444488'),
                Window(FormattedTextControl(LIPSUM), style='bg:#444488'),
            ], padding=1, padding_style='bg:#888888', align=HorizontalAlign.JUSTIFY, height=5, padding_char='|'),
        ]),
    ], padding=1, padding_style="bg:#ff3333 #ffffff", padding_char='.', align=VerticalAlign.TOP)
])


# 2. Key bindings
kb = KeyBindings()


@kb.add('q')
def _(event):
    " Quit application. "
    event.app.exit()


# 3. The `Application`
application = Application(
    layout=Layout(body),
    key_bindings=kb,
    full_screen=True)


def run():
    application.run()


if __name__ == '__main__':
    run()
