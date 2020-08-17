"""
Code taken from Stack Overflow Eryk Sun.
https://stackoverflow.com/questions/35772001/how-to-handle-the-signal-in-python-on-windows-machine
"""

import os
import sys
import time
import signal

if sys.platform != "win32" and sys.platform != "cygwin":
    kill = os.kill
    sleep = time.sleep
else:
    # adapt the conflated API on Windows.
    import threading

    sigmap = {
        signal.SIGINT: signal.CTRL_C_EVENT,
        signal.SIGBREAK: signal.CTRL_BREAK_EVENT,
    }

    def kill(pid, signum):
        if signum in sigmap and pid == os.getpid():
            # we don't know if the current process is a
            # process group leader, so just broadcast
            # to all processes attached to this console.
            pid = 0
        thread = threading.current_thread()
        handler = signal.getsignal(signum)
        # work around the synchronization problem when calling
        # kill from the main thread.
        if (
            signum in sigmap
            and thread.name == "MainThread"
            and callable(handler)
            and pid == 0
        ):
            event = threading.Event()

            def handler_set_event(signum, frame):
                event.set()
                return handler(signum, frame)

            signal.signal(signum, handler_set_event)
            try:
                os.kill(pid, sigmap[signum])
                # busy wait because we can't block in the main
                # thread, else the signal handler can't execute.
                while not event.is_set():
                    pass
            finally:
                signal.signal(signum, handler)
        else:
            os.kill(pid, sigmap.get(signum, signum))

    if sys.version_info[0] > 2:
        sleep = time.sleep
    else:
        import errno

        # If the signal handler doesn't raise an exception,
        # time.sleep in Python 2 raises an EINTR IOError, but
        # Python 3 just resumes the sleep.

        def sleep(interval):
            """sleep that ignores EINTR in 2.x on Windows"""
            while True:
                try:
                    t = time.time()
                    time.sleep(interval)
                except IOError as e:
                    if e.errno != errno.EINTR:
                        raise
                interval -= time.time() - t
                if interval <= 0:
                    break
