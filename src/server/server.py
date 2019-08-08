from __future__ import annotations
import asyncio
import logging
from src.server.chia_connection import ChiaConnection
from asyncio.events import AbstractServer

log = logging.getLogger(__name__)


async def start_server(api, host: str, port: int, peer_connections, connection_type=""):
    async def callback(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        connection = ChiaConnection(api, peer_connections, connection_type)
        await peer_connections.add(connection)
        await connection.new_connection(reader, writer)

    server: AbstractServer = await asyncio.start_server(
        callback, host, port)

    addr = server.sockets[0].getsockname()
    log.info(f'Serving {type(api).__name__} on {addr}')

    async with server:
        await server.serve_forever()


async def retry_connection(api_impl, target_ip, target_port,
                           target, global_connections, total_seconds=20) -> ChiaConnection:
    client_con = ChiaConnection(api_impl, global_connections)
    total_time: int = 0
    succeeded: bool = False
    while total_time < total_seconds and not succeeded:
        try:
            client_con = ChiaConnection(api_impl, global_connections, target)
            await client_con.open_connection(target_ip, target_port)
            succeeded = True
        except ConnectionRefusedError:
            print(f"Connection to {target_ip}:{target_port} refused.")
            await asyncio.sleep(5)
        total_time += 5
    if not succeeded:
        raise TimeoutError(f"Failed to connect to {target} at {target_ip}:{target_port}")
    return client_con
