#!/usr/bin/env python
"""
An example that demonstrates how `patch_stdout` works.

This makes sure that output from other threads doesn't disturb the rendering of
the prompt, but instead is printed nicely above the prompt.
"""
import threading
import time

from prompt_toolkit import prompt
from prompt_toolkit.patch_stdout import patch_stdout


def main():
    # Print a counter every second in another thread.
    running = True

    def thread():
        i = 0
        while running:
            i += 1
            print('i=%i' % i)
            time.sleep(1)
    t = threading.Thread(target=thread)
    t.daemon = True
    t.start()

    # Now read the input. The print statements of the other thread
    # should not disturb anything.
    with patch_stdout():
        result = prompt('Say something: ')
    print('You said: %s' % result)

    # Stop thread.
    running = False


if __name__ == '__main__':
    main()
