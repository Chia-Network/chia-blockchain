#!/usr/bin/env python
"""
A very simple progress bar which keep track of the progress as we consume an
iterator.
"""
import time

from prompt_toolkit.shortcuts import ProgressBar


def main():
    with ProgressBar() as pb:
        for i in pb(range(800)):
            time.sleep(.01)


if __name__ == '__main__':
    main()
