#!/usr/bin/env python
"""
Styled just like an apt-get installation.
"""
import time

from prompt_toolkit.shortcuts import ProgressBar
from prompt_toolkit.shortcuts.progress_bar import formatters
from prompt_toolkit.styles import Style

style = Style.from_dict({
    'label': 'bg:#ffff00 #000000',
    'percentage': 'bg:#ffff00 #000000',
    'current': '#448844',
    'bar': '',
})


def main():
    custom_formatters = [
        formatters.Label(),
        formatters.Text(': [', style='class:percentage'),
        formatters.Percentage(),
        formatters.Text(']', style='class:percentage'),
        formatters.Text(' '),
        formatters.Bar(sym_a='#', sym_b='#', sym_c='.'),
        formatters.Text('  '),
    ]

    with ProgressBar(style=style, formatters=custom_formatters) as pb:
        for i in pb(range(1600), label='Installing'):
            time.sleep(.01)


if __name__ == '__main__':
    main()
