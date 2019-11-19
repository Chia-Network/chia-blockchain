#!/usr/bin/env python
"""
A simple chat application over telnet.
Everyone that connects is asked for his name, and then people can chat with
each other.
"""
import logging
import random
from asyncio import get_event_loop

from prompt_toolkit.contrib.telnet.server import TelnetServer
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import clear, prompt, PromptSession

# Set up logging
logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

# List of connections.
_connections = []
_connection_to_color = {}


COLORS = [
    'ansired', 'ansigreen', 'ansiyellow', 'ansiblue', 'ansifuchsia',
    'ansiturquoise', 'ansilightgray', 'ansidarkgray', 'ansidarkred',
    'ansidarkgreen', 'ansibrown', 'ansidarkblue', 'ansipurple', 'ansiteal']


async def interact(connection):
    write = connection.send
    prompt_session = PromptSession()

    # When a client is connected, erase the screen from the client and say
    # Hello.
    clear()
    write('Welcome to our chat application!\n')
    write('All connected clients will receive what you say.\n')

    name = await prompt_session.prompt_async(message='Type your name: ')

    # Random color.
    color = random.choice(COLORS)
    _connection_to_color[connection] = color

    # Send 'connected' message.
    _send_to_everyone(connection, name, '(connected)', color)

    # Prompt.
    prompt_msg = HTML('<reverse fg="{}">[{}]</reverse> &gt; ').format(color, name)

    _connections.append(connection)
    try:
        # Set Application.
        while True:
            try:
                result = await prompt_session.prompt_async(message=prompt_msg)
                _send_to_everyone(connection, name, result, color)
            except KeyboardInterrupt:
                pass
    except EOFError:
        _send_to_everyone(connection, name, '(leaving)', color)
    finally:
        _connections.remove(connection)


def _send_to_everyone(sender_connection, name, message, color):
    """
    Send a message to all the clients.
    """
    for c in _connections:
        if c != sender_connection:
            c.send_above_prompt([
                ('fg:' + color, '[%s]' % name),
                ('', ' '),
                ('fg:' + color, '%s\n' % message),
            ])


def main():
    server = TelnetServer(interact=interact, port=2323)
    server.start()
    get_event_loop().run_forever()


if __name__ == '__main__':
    main()
