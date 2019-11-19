#!/usr/bin/env python
"""
Example of a progress bar dialog.
"""
import os
import time

from prompt_toolkit.shortcuts import progress_dialog


def worker(set_percentage, log_text):
    """
    This worker function is called by `progress_dialog`. It will run in a
    background thread.

    The `set_percentage` function can be used to update the progress bar, while
    the `log_text` function can be used to log text in the logging window.
    """
    percentage = 0
    for dirpath, dirnames, filenames in os.walk('../..'):
        for f in filenames:
            log_text('{} / {}\n'.format(dirpath, f))
            set_percentage(percentage + 1)
            percentage += 2
            time.sleep(.1)

            if percentage == 100:
                break
        if percentage == 100:
            break

    # Show 100% for a second, before quitting.
    set_percentage(100)
    time.sleep(1)


def main():
    progress_dialog(
        title='Progress dialog example',
        text='As an examples, we walk through the filesystem and print '
             'all directories',
        run_callback=worker).run()


if __name__ == '__main__':
    main()
