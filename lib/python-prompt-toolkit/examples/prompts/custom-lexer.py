#!/usr/bin/env python
"""
An example of a custom lexer that prints the input text in random colors.
"""
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.shortcuts import prompt
from prompt_toolkit.styles.named_colors import NAMED_COLORS


class RainbowLexer(Lexer):
    def lex_document(self, document):
        colors = list(sorted(NAMED_COLORS, key=NAMED_COLORS.get))

        def get_line(lineno):
            return [(colors[i % len(colors)], c) for i, c in enumerate(document.lines[lineno])]

        return get_line


def main():
    answer = prompt('Give me some input: ', lexer=RainbowLexer())
    print('You said: %s' % answer)


if __name__ == '__main__':
    main()
