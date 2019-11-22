#!/usr/bin/env python
"""
Example of implementing auto correction while typing.

The word "impotr" will be corrected when the user types a space afterwards.
"""
from prompt_toolkit import prompt
from prompt_toolkit.key_binding import KeyBindings

# Database of words to be replaced by typing.
corrections = {
    'impotr': 'import',
    'wolrd': 'world',
}


def main():
    # We start with a `KeyBindings` for our extra key bindings.
    bindings = KeyBindings()

    # We add a custom key binding to space.
    @bindings.add(' ')
    def _(event):
        """
        When space is pressed, we check the word before the cursor, and
        autocorrect that.
        """
        b = event.app.current_buffer
        w = b.document.get_word_before_cursor()

        if w is not None:
            if w in corrections:
                b.delete_before_cursor(count=len(w))
                b.insert_text(corrections[w])

        b.insert_text(' ')

    # Read input.
    text = prompt('Say something: ', key_bindings=bindings)
    print('You said: %s' % text)


if __name__ == '__main__':
    main()
