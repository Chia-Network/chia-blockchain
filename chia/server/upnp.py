import logging
import threading
from queue import Queue
from typing import Optional

try:
    import miniupnpc
except ImportError:
    pass


log = logging.getLogger(__name__)


class UPnP:
    thread: Optional[threading.Thread] = None
    queue: Queue = Queue()

    def __init__(self):
        def run():
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
                log.info(
                    "UPnP failed. This is not required to run chia, it allows incoming connections from other peers."
                )
                log.info(e)

        self.thread = threading.Thread(target=run)
        self.thread.start()

    def remap(self, port):
        self.queue.put(("remap", port))

    def release(self, port):
        self.queue.put(("release", port))

    def shutdown(self):
        if not self.thread:
            return
        self.queue.put(("shutdown",))
        log.info("UPnP, shutting down thread")
        self.thread.join()
        self.thread = None

    # this is here just in case the UPnP object is destroyed non-gracefully,
    # e.g. via an exception before the main thread can call shutdown()
    def __del__(self):
        self.shutdown()
