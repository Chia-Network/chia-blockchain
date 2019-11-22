#!/usr/bin/env python
"""
Demonstration of how to print using ANSI escape sequences.

The advantage here is that this is cross platform. The escape sequences will be
parsed and turned into appropriate Win32 API calls on Windows.
"""
from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import ANSI, HTML

print = print_formatted_text


def title(text):
    print(HTML('\n<u><b>{}</b></u>').format(text))


def main():
    title('Special formatting')
    print(ANSI('    \x1b[1mBold'))
    print(ANSI('    \x1b[6mBlink'))
    print(ANSI('    \x1b[3mItalic'))
    print(ANSI('    \x1b[7mReverse'))
    print(ANSI('    \x1b[4mUnderline'))
    print(ANSI('    \x1b[8mHidden\x1b[0m (Hidden)'))

    # Ansi colors.
    title('ANSI colors')

    print(ANSI('    \x1b[91mANSI Red'))
    print(ANSI('    \x1b[94mANSI Blue'))

    # Other named colors.
    title('Named colors')

    print(ANSI('    \x1b[38;5;214morange'))
    print(ANSI('    \x1b[38;5;90mpurple'))

    # Background colors.
    title('Background colors')

    print(ANSI('    \x1b[97;101mANSI Red'))
    print(ANSI('    \x1b[97;104mANSI Blue'))

    print()


if __name__ == '__main__':
    main()
