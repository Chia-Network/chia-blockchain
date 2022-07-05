from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from queue import Queue
from typing import Optional, Tuple, Union

from typing_extensions import Literal

try:
    import miniupnpc
except ImportError:
    pass


log = logging.getLogger(__name__)


@dataclass
class UPnP:
    thread: Optional[threading.Thread] = None
    queue: Queue[Union[Tuple[Literal["remap", "release"], int], Tuple[Literal["shutdown"]]]] = field(
        default_factory=Queue,
    )
    upnp: Optional[miniupnpc.UPnP] = None

    def __post_init__(self) -> None:
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

    def run(self) -> None:
        try:
            self.upnp = miniupnpc.UPnP()
            self.upnp.discoverdelay = 30
            self.upnp.discover()
            self.upnp.selectigd()
            keep_going = True
            while keep_going:
                msg = self.queue.get()
                if msg[0] == "remap":
                    port = msg[1]
                    log.info(f"Attempting to enable UPnP (open up port {port})")
                    try:
                        self.upnp.deleteportmapping(port, "TCP")
                    except Exception as e:
                        log.info(f"Removal of previous portmapping failed. This does not indicate an error: {e}")
                    self.upnp.addportmapping(port, "TCP", self.upnp.lanaddr, port, "chia", "")
                    log.info(
                        f"Port {port} opened with UPnP. lanaddr {self.upnp.lanaddr} "
                        f"external: {self.upnp.externalipaddress()}"
                    )
                elif msg[0] == "release":
                    port = msg[1]
                    log.info(f"UPnP, releasing port {port}")
                    self.upnp.deleteportmapping(port, "TCP")
                    log.info(f"UPnP, Port {port} closed")
                elif msg[0] == "shutdown":
                    keep_going = False
        except Exception as e:
            log.info("UPnP failed. This is not required to run chia, it allows incoming connections from other peers.")
            log.info(e)

    def remap(self, port: int) -> None:
        self.queue.put(("remap", port))

    def release(self, port: int) -> None:
        self.queue.put(("release", port))

    def shutdown(self) -> None:
        if self.thread is None:
            return
        self.queue.put(("shutdown",))
        log.info("UPnP, shutting down thread")
        self.thread.join(5)
        self.thread = None

    # this is here just in case the UPnP object is destroyed non-gracefully,
    # e.g. via an exception before the main thread can call shutdown()
    def __del__(self) -> None:
        self.shutdown()
