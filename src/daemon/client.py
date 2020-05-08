import asyncio
import os
import subprocess


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


def launch_start_daemon(root_path):
    os.environ["CHIA_ROOT"] = str(root_path)
    # TODO: use startupinfo=subprocess.DETACHED_PROCESS on windows
    process = subprocess.Popen("chia daemon".split(), shell=False)
    return process


async def create_start_daemon_connection(root_path):
    connection = await connect_to_daemon_and_validate(root_path)
    if connection is None:
        # launch a daemon
        process = launch_start_daemon(root_path)
        # give the daemon a chance to start up
        # TODO: fix this gross hack
        await asyncio.sleep(5)
        connection = await connect_to_daemon_and_validate(root_path)
    if connection:
        return connection
    raise RuntimeError("can't connect to `chia daemon`, launching it now, try again")
