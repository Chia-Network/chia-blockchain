#!/usr/bin/env python
"""
A simple Telnet application that asks for input and responds.

The interaction function is a prompt_toolkit coroutine.
Also see the `hello-world-asyncio.py` example which uses an asyncio coroutine.
That is probably the preferred way if you only need Python 3 support.
"""
import logging
from asyncio import get_event_loop

from prompt_toolkit.contrib.telnet.server import TelnetServer
from prompt_toolkit.shortcuts import clear, prompt

# Set up logging
logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)


async def interact(connection):
    clear()
    connection.send('Welcome!\n')

    # Ask for input.
    result = await prompt(message='Say something: ', async_=True)

    # Send output.
    connection.send('You said: {}\n'.format(result))
    connection.send('Bye.\n')


def main():
    server = TelnetServer(interact=interact, port=2323)
    server.start()
    get_event_loop().run_forever()


if __name__ == '__main__':
    main()
