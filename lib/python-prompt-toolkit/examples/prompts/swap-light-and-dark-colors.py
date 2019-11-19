#!/usr/bin/env python
"""
Demonstration of swapping light/dark colors in prompt_toolkit using the
`swap_light_and_dark_colors` parameter.

Notice that this doesn't swap foreground and background like "reverse" does. It
turns light green into dark green and the other way around. Foreground and
background are independent of each other.
"""
from pygments.lexers.html import HtmlLexer

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer

html_completer = WordCompleter([
    '<body>', '<div>', '<head>', '<html>', '<img>', '<li>', '<link>', '<ol>',
    '<p>', '<span>', '<table>', '<td>', '<th>', '<tr>', '<ul>',
], ignore_case=True)


def main():
    swapped = [False]  # Nonlocal
    bindings = KeyBindings()

    @bindings.add('c-t')
    def _(event):
        ' When ControlT has been pressed, toggle light/dark colors. '
        swapped[0] = not swapped[0]

    def bottom_toolbar():
        if swapped[0]:
            on = 'on=true'
        else:
            on = 'on=false'

        return HTML('Press <style bg="#222222" fg="#ff8888">[control-t]</style> '
                    'to swap between dark/light colors. '
                    '<style bg="ansiblack" fg="ansiwhite">[%s]</style>') % on

    text = prompt(HTML('<style fg="#aaaaaa">Give some animals</style>: '),
                  completer=html_completer,
                  complete_while_typing=True,
                  bottom_toolbar=bottom_toolbar,
                  key_bindings=bindings,
                  lexer=PygmentsLexer(HtmlLexer),
                  swap_light_and_dark_colors=Condition(lambda: swapped[0]))
    print('You said: %s' % text)


if __name__ == '__main__':
    main()
