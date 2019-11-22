#!/usr/bin/env python
"""
Example of a telnet application that displays a dialog window.
"""
import logging
from asyncio import get_event_loop

from prompt_toolkit.contrib.telnet.server import TelnetServer
from prompt_toolkit.shortcuts.dialogs import yes_no_dialog

# Set up logging
logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)


async def interact(connection):
    result = await yes_no_dialog(
        title='Yes/no dialog demo', text='Press yes or no').run_async()

    connection.send('You said: {}\n'.format(result))
    connection.send('Bye.\n')


def main():
    server = TelnetServer(interact=interact, port=2323)
    server.start()
    get_event_loop().run_forever()


if __name__ == '__main__':
    main()
