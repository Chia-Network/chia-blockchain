#!/usr/bin/env python
"""
Example of running a prompt_toolkit application in an asyncssh server.
"""
import asyncio
import logging

import asyncssh

from prompt_toolkit.shortcuts.dialogs import yes_no_dialog, input_dialog
from prompt_toolkit.shortcuts.prompt import PromptSession
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.shortcuts import ProgressBar
from prompt_toolkit.contrib.ssh import PromptToolkitSSHServer

from pygments.lexers.html import HtmlLexer

from prompt_toolkit.lexers import PygmentsLexer

from prompt_toolkit.completion import WordCompleter
from prompt_toolkit import Application
from prompt_toolkit.layout.containers import VSplit, HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.widgets import (
    Frame,
    Label,
    TextArea,
    Button
)
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.key_binding.bindings.focus import (
    focus_next,
    focus_previous,
)


animal_completer = WordCompleter([
    'alligator', 'ant', 'ape', 'bat', 'bear', 'beaver', 'bee', 'bison',
    'butterfly', 'cat', 'chicken', 'crocodile', 'dinosaur', 'dog', 'dolphin',
    'dove', 'duck', 'eagle', 'elephant', 'fish', 'goat', 'gorilla', 'kangaroo',
    'leopard', 'lion', 'mouse', 'rabbit', 'rat', 'snake', 'spider', 'turkey',
    'turtle',
], ignore_case=True)


async def interact() -> None:
    """
    The application interaction.
    This will run automatically in a prompt_toolkit AppSession, which means
    that any prompt_toolkit application (dialogs, prompts, etc...) will use the
    SSH channel for input and output.
    """
    kb = KeyBindings()
    kb.add('tab')(focus_next)
    kb.add('s-tab')(focus_previous)

    @kb.add('c-c')
    def exit_(event):
        print("CLOSING")
        """
        Pressing Ctrl-Q will exit the user interface.

        Setting a return value means: quit the event loop that drives the user
        interface and return this value from the `Application.run()` call.
        """
        event.app.exit()

    label1 = Label(text="label1")
    label2 = Label(text="label2")
    body = HSplit([label1, label2], height=D(), width=D())
    content = Frame(title="Chia Full Node", body=body)
    layout = Layout(VSplit([content], height=D(), width=D()))
    app = Application(layout=layout, full_screen=True, key_bindings=kb, mouse_support=True).run_async()
    await app


def main(port=8222):
    # Set up logging.
    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        asyncssh.create_server(
            lambda: PromptToolkitSSHServer(interact),
            "",
            port,
            server_host_keys=["/Users/mariano/.ssh/id_rsa"],
        )
    )
    loop.run_forever()


if __name__ == "__main__":
    main()