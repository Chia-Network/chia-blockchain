#!/usr/bin/env python
"""
Example of an input box dialog.
"""
from prompt_toolkit.shortcuts import input_dialog


def main():
    result = input_dialog(
        title='Input dialog example',
        text='Please type your name:').run()

    print('Result = {}'.format(result))


if __name__ == '__main__':
    main()
