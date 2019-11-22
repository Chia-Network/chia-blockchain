#!/usr/bin/env python
"""
Example of nested autocompletion.
"""
from prompt_toolkit import prompt
from prompt_toolkit.completion import NestedCompleter


completer = NestedCompleter.from_nested_dict({
    'show': {
        'version': None,
        'clock': None,
        'ip': {
            'interface': {
                'brief': None
            }
        }
    },
    'exit': None,
})


def main():
    text = prompt('Type a command: ', completer=completer)
    print('You said: %s' % text)


if __name__ == '__main__':
    main()
