#!/usr/bin/env python
"""
Example of adding a custom key binding to a prompt.
"""
from prompt_toolkit import prompt
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.key_binding import KeyBindings


def main():
    # We start with a `KeyBindings` of default key bindings.
    bindings = KeyBindings()

    # Add our own key binding.
    @bindings.add('f4')
    def _(event):
        """
        When F4 has been pressed. Insert "hello world" as text.
        """
        event.app.current_buffer.insert_text('hello world')

    @bindings.add('x', 'y')
    def _(event):
        """
        (Useless, but for demoing.)
        Typing 'xy' will insert 'z'.

        Note that when you type for instance 'xa', the insertion of 'x' is
        postponed until the 'a' is typed. because we don't know earlier whether
        or not a 'y' will follow. However, prompt-toolkit should already give
        some visual feedback of the typed character.
        """
        event.app.current_buffer.insert_text('z')

    @bindings.add('a', 'b', 'c')
    def _(event):
        " Typing 'abc' should insert 'd'. "
        event.app.current_buffer.insert_text('d')

    @bindings.add('c-t')
    def _(event):
        """
        Print 'hello world' in the terminal when ControlT is pressed.

        We use ``run_in_terminal``, because that ensures that the prompt is
        hidden right before ``print_hello`` gets executed and it's drawn again
        after it. (Otherwise this would destroy the output.)
        """
        def print_hello():
            print('hello world')
        run_in_terminal(print_hello)

    # Read input.
    print('Press F4 to insert "hello world", type "xy" to insert "z":')
    text = prompt('> ', key_bindings=bindings)
    print('You said: %s' % text)


if __name__ == '__main__':
    main()
