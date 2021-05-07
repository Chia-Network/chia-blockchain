import logging

try:
    import miniupnpc
except ImportError:
    pass


log = logging.getLogger(__name__)
upnp = miniupnpc.UPnP()
upnp.discoverdelay = 30
upnp.discover()
upnp.selectigd()


def upnp_remap_port(port) -> None:
    log.info(f"Attempting to enable UPnP (open up port {port})")
    try:
        global upnp
        upnp.deleteportmapping(port, "TCP")
        upnp.addportmapping(port, "TCP", upnp.lanaddr, port, "chia", "")
        log.info(f"Port {port} opened with UPnP. lanaddr {upnp.lanaddr} external: {upnp.externalipaddress()}")
    except Exception as e:
        log.info("UPnP failed. This is not required to run chia, but it allows incoming connections from other peers.")
        log.info(e)


def upnp_release_port(port) -> None:
    try:
        global upnp
        upnp.deleteportmapping(port, "TCP")
        log.info(f"Port {port} closed with UPnP")
    except Exception as e:
        log.info("UPnP delete failed")
        log.info(e)
