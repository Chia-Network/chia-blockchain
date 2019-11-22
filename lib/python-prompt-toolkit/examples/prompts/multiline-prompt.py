#!/usr/bin/env python
"""
Demonstration of how the input can be indented.
"""
from prompt_toolkit import prompt

if __name__ == '__main__':
    answer = prompt('Give me some input: (ESCAPE followed by ENTER to accept)\n > ', multiline=True)
    print('You said: %s' % answer)
