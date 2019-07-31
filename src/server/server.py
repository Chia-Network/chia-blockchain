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
