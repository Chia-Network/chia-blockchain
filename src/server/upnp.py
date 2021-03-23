import logging

try:
    import miniupnpc
except ImportError:
    pass


log = logging.getLogger(__name__)


def upnp_remap_port(port):
    log.info(f"Attempting to enable UPnP (open up port {port})")
    try:
        upnp = miniupnpc.UPnP()
        upnp.discoverdelay = 30
        upnp.discover()
        upnp.selectigd()
        upnp.addportmapping(port, "TCP", upnp.lanaddr, port, "chia", "")
        log.info(f"Port {port} opened with UPnP. lanaddr {upnp.lanaddr} external: {upnp.externalipaddress()}")
    except Exception:
        log.info("UPnP failed. This is not required to run chia, but it allows incoming connections from other peers.")
