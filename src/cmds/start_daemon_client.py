import asyncio

from src.proxy.client import request_response_proxy

from .start_daemon import socket_server_path, socket_server_info_path


async def client_rw_for_start_daemon(root_path):
    try:
        socket_path = socket_server_path(root_path)
        if socket_path.is_socket():
            r, w = await asyncio.open_unix_connection(socket_path)
            return r, w
    except Exception as ex:
        pass

    try:
        # TODO: make this configurable
        socket_server_port = 62191
        r, w = await asyncio.open_connection("127.0.0.1", port=socket_server_port)
        return r, w
    except Exception as ex:
        pass
    return None


async def connect_to_daemon(root_path=None):
    from src.util.default_root import DEFAULT_ROOT_PATH
    root_path = root_path or DEFAULT_ROOT_PATH
    reader, writer = await client_rw_for_start_daemon(DEFAULT_ROOT_PATH)
    return request_response_proxy(reader, writer)
