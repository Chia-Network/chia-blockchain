import asyncio

from src.proxy.client import request_response_proxy
from src.util.path import mkdir


def should_use_unix_socket():
    import socket
    return hasattr(socket, "AF_UNIX")


def socket_server_path(root_path):
    return root_path / "run" / "start-daemon.socket"


async def client_rw_for_start_daemon(root_path, use_unix_socket):
    path = socket_server_path(root_path)
    mkdir(path.parent)
    try:
        if use_unix_socket:
            if path.is_socket():
                r, w = await asyncio.open_unix_connection(path)
            return None
        else:
            with open(path) as f:
                port = int(f.readline())
            r, w = await asyncio.open_connection("127.0.0.1", port=port)
        return r, w
    except Exception as ex:
        pass

    return None


async def connect_to_daemon(root_path, use_unix_socket):
    reader, writer = await client_rw_for_start_daemon(root_path, use_unix_socket)
    return request_response_proxy(reader, writer)


async def connect_to_daemon_and_validate(root_path):
    use_unix_socket = should_use_unix_socket()
    try:
        connection = await connect_to_daemon(root_path, use_unix_socket)
        r = await connection.ping()
        if r == "pong":
            return connection
    except Exception as ex:
        pass
    return None
