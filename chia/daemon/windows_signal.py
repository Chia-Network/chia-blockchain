"""
Code taken from Stack Overflow Eryk Sun.
https://stackoverflow.com/questions/35772001/how-to-handle-the-signal-in-python-on-windows-machine
"""

from __future__ import annotations

import os
import signal
import sys
from types import FrameType
from typing import Any, Callable, Optional, Union

# https://github.com/python/typeshed/blob/fbddd2c4e2b746f1880399ed0cb31a44d6ede6ff/stdlib/signal.pyi
_HANDLER = Union[Callable[[int, Optional[FrameType]], Any], int, signal.Handlers, None]

if sys.platform != "win32" and sys.platform != "cygwin":
    kill = os.kill
else:
    # adapt the conflated API on Windows.
    import threading

    sigmap = {
        signal.SIGINT: signal.CTRL_C_EVENT,  # pylint: disable=E1101
        signal.SIGBREAK: signal.CTRL_BREAK_EVENT,  # pylint: disable=E1101
    }

    def kill(pid: int, signum: signal.Signals) -> None:
        if signum in sigmap and pid == os.getpid():
            # we don't know if the current process is a
            # process group leader, so just broadcast
            # to all processes attached to this console.
            pid = 0
        thread = threading.current_thread()
        handler = signal.getsignal(signum)
        # work around the synchronization problem when calling
        # kill from the main thread.
        if signum in sigmap and thread.name == "MainThread" and callable(handler) and pid == 0:
            event = threading.Event()
            callable_handler = handler

            def handler_set_event(signum: int, frame: Optional[FrameType]) -> Any:
                event.set()
                return callable_handler(signum, frame)

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
