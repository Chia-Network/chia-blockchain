#!/usr/bin/env python
"""
More complex demonstration of what's possible with the progress bar.
"""
import random
import threading
import time

from prompt_toolkit import HTML
from prompt_toolkit.shortcuts import ProgressBar


def main():
    with ProgressBar(
            title=HTML('<b>Example of many parallel tasks.</b>'),
            bottom_toolbar=HTML('<b>[Control-L]</b> clear  <b>[Control-C]</b> abort')) as pb:

        def run_task(label, total, sleep_time):
            for i in pb(range(total), label=label):
                time.sleep(sleep_time)

        threads = []

        for i in range(160):
            label = 'Task %i' % i
            total = random.randrange(50, 200)
            sleep_time = random.randrange(5, 20) / 100.

            threads.append(threading.Thread(target=run_task, args=(label, total, sleep_time)))

        for t in threads:
            t.daemon = True
            t.start()

        # Wait for the threads to finish. We use a timeout for the join() call,
        # because on Windows, join cannot be interrupted by Control-C or any other
        # signal.
        for t in threads:
            while t.is_alive():
                t.join(timeout=.5)


if __name__ == '__main__':
    main()
