from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from queue import Queue
from typing import Optional, Tuple, Union

from typing_extensions import Literal

log = logging.getLogger(__name__)

try:
    import miniupnpc
except ImportError:
    log.info(
        "importing miniupnpc failed."
        " This is not required to run chia, it allows incoming connections from other peers."
    )
    miniupnpc = None


@dataclass
class UPnP:
    _thread: Optional[threading.Thread] = None
    _queue: Queue[Union[Tuple[Literal["remap", "release"], int], Tuple[Literal["shutdown"]]]] = field(
        default_factory=Queue,
    )
    _upnp: Optional[miniupnpc.UPnP] = None

    def setup(self) -> None:
        if miniupnpc is None:
            return

        if self._thread is not None:
            raise Exception(f"already started, {type(self).__name__} instances are not reusable")

        self._thread = threading.Thread(target=self._run)
        self._thread.start()

    def _is_alive(self) -> bool:
        if self._thread is None:
            return False

        return self._thread.is_alive()

    def _run(self) -> None:
        try:
            self._upnp = miniupnpc.UPnP()
            self._upnp.discoverdelay = 30
            self._upnp.discover()
            self._upnp.selectigd()
            keep_going = True
            while keep_going:
                msg = self._queue.get()
                if msg[0] == "remap":
                    port = msg[1]
                    log.info(f"Attempting to enable UPnP (open up port {port})")
                    try:
                        self._upnp.deleteportmapping(port, "TCP")
                    except Exception as e:
                        log.info(f"Removal of previous portmapping failed. This does not indicate an error: {e}")
                    self._upnp.addportmapping(port, "TCP", self._upnp.lanaddr, port, "chia", "")
                    log.info(
                        f"Port {port} opened with UPnP. lanaddr {self._upnp.lanaddr} "
                        f"external: {self._upnp.externalipaddress()}"
                    )
                elif msg[0] == "release":
                    port = msg[1]
                    log.info(f"UPnP, releasing port {port}")
                    self._upnp.deleteportmapping(port, "TCP")
                    log.info(f"UPnP, Port {port} closed")
                elif msg[0] == "shutdown":
                    keep_going = False
        except Exception as e:
            log.info("UPnP failed. This is not required to run chia, it allows incoming connections from other peers.")
            log.info(e)

    def remap(self, port: int) -> None:
        if not self._is_alive():
            return

        self._queue.put(("remap", port))

    def release(self, port: int) -> None:
        if not self._is_alive():
            return

        self._queue.put(("release", port))

    def shutdown(self) -> None:
        if self._thread is None:
            return

        if self._is_alive():
            self._queue.put(("shutdown",))
            log.info("UPnP, shutting down thread")

        self._thread.join(5)

    # this is here just in case the UPnP object is destroyed non-gracefully,
    # e.g. via an exception before the main thread can call shutdown()
    def __del__(self) -> None:
        self.shutdown()
