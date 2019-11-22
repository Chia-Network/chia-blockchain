#!/usr/bin/env python
"""
Autocompletion example.

Press [Tab] to complete the current word.
- The first Tab press fills in the common part of all completions
    and shows all the completions. (In the menu)
- Any following tab press cycles through all the possible completions.
"""
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter

animal_completer = WordCompleter([
    'alligator', 'ant', 'ape', 'bat', 'bear', 'beaver', 'bee', 'bison',
    'butterfly', 'cat', 'chicken', 'crocodile', 'dinosaur', 'dog', 'dolphin',
    'dove', 'duck', 'eagle', 'elephant', 'fish', 'goat', 'gorilla', 'kangaroo',
    'leopard', 'lion', 'mouse', 'rabbit', 'rat', 'snake', 'spider', 'turkey',
    'turtle',
], ignore_case=True)


def main():
    text = prompt('Give some animals: ', completer=animal_completer,
                  complete_while_typing=False)
    print('You said: %s' % text)


if __name__ == '__main__':
    main()
