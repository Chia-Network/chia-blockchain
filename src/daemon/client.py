import aiohttp

from src.util.path import mkdir


def should_use_unix_socket():
    """
    Use unix sockets unless they are not supported. Check `socket` to see.
    """
    import socket
    return hasattr(socket, "AF_UNIX")


def socket_server_path(root_path):
    """
    This is the file that's either the unix socket or a text file containing
    the TCP socket information (ie. the port).
    """
    return root_path / "run" / "start-daemon.socket"


def uri_info_for_start_daemon(root_path, use_unix_socket):
    """
    Return the URI prefix and the path to the socket file.
    """
    path = socket_server_path(root_path)
    mkdir(path.parent)
    try:
        if use_unix_socket:
            return f"http://unix", str(path)
        with open(path) as f:
            port = int(f.readline())
        return f"http://127.0.0.1:{port}", None
    except Exception as ex:
        pass

    return None


class DaemonProxy:
    def __init__(self, prefix, unix_socket_path):
        self._prefix = prefix
        self._unix_socket_path = unix_socket_path

    async def _get(self, uri):
        url = f"{self._prefix}{uri}"
        kwargs = {}
        if self._unix_socket_path:
            kwargs = dict(connector=aiohttp.UnixConnector(self._unix_socket_path), connector_owner=True)
        async with aiohttp.ClientSession(**kwargs) as session:
            async with session.get(url) as response:
                r = await response.text()
        return r

    async def start_service(self, service_name):
        uri = f"/daemon/service/start/?service={service_name}"
        return await self._get(uri)

    async def stop_service(self, service_name, delay_before_kill=15):
        uri = f"/daemon/service/stop/?service={service_name}"
        return await self._get(uri)

    async def is_running(self, service_name):
        uri = f"/daemon/service/is_running/?service={service_name}"
        return (await self._get(uri)) == "True"

    async def ping(self):
        uri = f"/daemon/ping/"
        return await self._get(uri)

    async def exit(self):
        uri = f"/daemon/exit/"
        return await self._get(uri)


async def connect_to_daemon(root_path, use_unix_socket):
    """
    Connect to the local daemon.
    """
    prefix, unix_socket_path = uri_info_for_start_daemon(root_path, should_use_unix_socket())
    return DaemonProxy(prefix, unix_socket_path)


async def connect_to_daemon_and_validate(root_path):
    """
    Connect to the local daemon and do a ping to ensure that something is really
    there and running.
    """
    use_unix_socket = should_use_unix_socket()
    try:
        connection = await connect_to_daemon(root_path, use_unix_socket)
        r = await connection.ping()
        if r == "pong":
            return connection
    except Exception as ex:
        pass
    return None
