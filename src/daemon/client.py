import asyncio

from src.proxy.client import request_response_proxy
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


async def client_rw_for_start_daemon(root_path, use_unix_socket):
    """
    Connect to the unix or TCP socket, and return the reader & writer.
    """
    path = socket_server_path(root_path)
    mkdir(path.parent)
    try:
        if use_unix_socket:
            r, w = await asyncio.open_unix_connection(path)
        else:
            with open(path) as f:
                port = int(f.readline())
            r, w = await asyncio.open_connection("127.0.0.1", port=port)
        return r, w
    except Exception as ex:
        pass

    return None


async def connect_to_daemon(root_path, use_unix_socket):
    """
    Connect to the local daemon.
    """
    reader, writer = await client_rw_for_start_daemon(root_path, use_unix_socket)
    return request_response_proxy(reader, writer)


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
