#!/usr/bin/env python
from prompt_toolkit import prompt

if __name__ == '__main__':
    answer = prompt('Give me some input: ', wrap_lines=False, multiline=True)
    print('You said: %s' % answer)
