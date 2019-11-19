#!/usr/bin/env python
"""
Example of a message box window.
"""
from prompt_toolkit.shortcuts import message_dialog


def main():
    message_dialog(
        title='Example dialog window',
        text='Do you want to continue?\nPress ENTER to quit.').run()


if __name__ == '__main__':
    main()
