#!/usr/bin/env python
"""
Simple example of a syntax-highlighted HTML input line.
(This requires Pygments to be installed.)
"""
from pygments.lexers.html import HtmlLexer

from prompt_toolkit import prompt
from prompt_toolkit.lexers import PygmentsLexer


def main():
    text = prompt('Enter HTML: ', lexer=PygmentsLexer(HtmlLexer))
    print('You said: %s' % text)


if __name__ == '__main__':
    main()
