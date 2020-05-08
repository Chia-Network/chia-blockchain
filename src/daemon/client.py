import asyncio


from src.proxy.client import request_response_proxy

from .server import socket_server_path, socket_server_info_path


async def client_rw_for_start_daemon(root_path):
    try:
        socket_path = socket_server_path(root_path)
        if socket_path.is_socket():
            r, w = await asyncio.open_unix_connection(socket_path)
            return r, w
    except Exception as ex:
        pass

    try:
        path = socket_server_info_path(root_path)
        with open(path) as f:
            port = int(f.readline())
        r, w = await asyncio.open_connection("127.0.0.1", port=port)
        return r, w
    except Exception as ex:
        pass
    return None


async def connect_to_daemon(root_path):
    reader, writer = await client_rw_for_start_daemon(root_path)
    return request_response_proxy(reader, writer)


async def connect_to_daemon_and_validate(root_path):
    try:
        connection = await connect_to_daemon(root_path)
        r = await connection.ping()
        if r == "pong":
            return connection
    except Exception as ex:
        pass
    return None
