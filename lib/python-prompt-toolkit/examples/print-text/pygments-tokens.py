#!/usr/bin/env python
"""
Printing a list of Pygments (Token, text) tuples,
or an output of a Pygments lexer.
"""
import pygments
from pygments.lexers.python import PythonLexer
from pygments.token import Token

from prompt_toolkit import print_formatted_text
from prompt_toolkit.formatted_text import PygmentsTokens
from prompt_toolkit.styles import Style


def main():
    # Printing a manually constructed list of (Token, text) tuples.
    text = [
        (Token.Keyword, 'print'),
        (Token.Punctuation, '('),
        (Token.Literal.String.Double, '"'),
        (Token.Literal.String.Double, 'hello'),
        (Token.Literal.String.Double, '"'),
        (Token.Punctuation, ')'),
        (Token.Text, '\n'),
    ]

    print_formatted_text(PygmentsTokens(text))

    # Printing the output of a pygments lexer.
    tokens = list(pygments.lex('print("Hello")', lexer=PythonLexer()))
    print_formatted_text(PygmentsTokens(tokens))

    # With a custom style.
    style = Style.from_dict({
        'pygments.keyword': 'underline',
        'pygments.literal.string': 'bg:#00ff00 #ffffff',
    })
    print_formatted_text(PygmentsTokens(tokens), style=style)


if __name__ == '__main__':
    main()
