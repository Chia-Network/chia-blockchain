#!/usr/bin/env python
"""
A very simple progress bar which keep track of the progress as we consume an
iterator.
"""
import time

from prompt_toolkit.shortcuts import ProgressBar
from prompt_toolkit.styles import Style

style = Style.from_dict({
    'title': '#4444ff underline',
    'label': '#ff4400 bold',
    'percentage': '#00ff00',
    'bar-a': 'bg:#00ff00 #004400',
    'bar-b': 'bg:#00ff00 #000000',
    'bar-c': '#000000 underline',
    'current': '#448844',
    'total': '#448844',
    'time-elapsed': '#444488',
    'time-left': 'bg:#88ff88 #000000',
})


def main():
    with ProgressBar(style=style, title='Progress bar example with custom styling.') as pb:
        for i in pb(range(1600), label='Downloading...'):
            time.sleep(.01)


if __name__ == '__main__':
    main()
