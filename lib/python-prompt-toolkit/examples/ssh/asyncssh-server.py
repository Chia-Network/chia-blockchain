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
    prompt_session = PromptSession()

    # Alias 'print_formatted_text', so that 'print' calls go to the SSH client.
    print = print_formatted_text

    print('We will be running a few prompt_toolkit applications through this ')
    print('SSH connection.\n')

    # Simple progress bar.
    with ProgressBar() as pb:
        for i in pb(range(50)):
            await asyncio.sleep(.1)

    # Normal prompt.
    text = await prompt_session.prompt_async("(normal prompt) Type something: ")
    print("You typed", text)

    # Prompt with auto completion.
    text = await prompt_session.prompt_async(
        "(autocompletion) Type an animal: ", completer=animal_completer)
    print("You typed", text)

    # prompt with syntax highlighting.
    text = await prompt_session.prompt_async("(HTML syntax highlighting) Type something: ",
                                             lexer=PygmentsLexer(HtmlLexer))
    print("You typed", text)

    # Show yes/no dialog.
    await prompt_session.prompt_async('Showing yes/no dialog... [ENTER]')
    await yes_no_dialog("Yes/no dialog", "Running over asyncssh").run_async()

    # Show input dialog
    await prompt_session.prompt_async('Showing input dialog... [ENTER]')
    await input_dialog("Input dialog", "Running over asyncssh").run_async()


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
            server_host_keys=["/etc/ssh/ssh_host_ecdsa_key"],
        )
    )
    loop.run_forever()


if __name__ == "__main__":
    main()
