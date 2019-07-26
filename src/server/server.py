from __future__ import annotations

import asyncio
import cbor2
import logging
from asyncio import IncompleteReadError, Lock
from src.util.streamable import transform_to_streamable
from typing import List
from asyncio.events import AbstractServer


log = logging.getLogger(__name__)

LENGTH_BYTES: int = 5


class PeerConnections():
    def __init__(self, all_connections: List[ChiaConnection] = []):
        self.connections_lock_ = Lock()
        self.all_connections_ = all_connections

    async def add(self, connection: ChiaConnection):
        async with self.connections_lock_:
            self.all_connections_.append(connection)

    async def remove(self, connection: ChiaConnection):
        async with self.connections_lock_:
            self.all_connections_.remove(connection)

    async def get_lock(self):
        return self.connections_lock_

    async def get_connections(self):
        return self.all_connections_


peer_connections = PeerConnections()


# A new ChiaConnection object is created every time a connection is opened
class ChiaConnection:
    def __init__(self, api, connection_type=""):
        self.api_ = api
        self.open_ = False
        self.open_lock_ = asyncio.Lock()
        self.write_lock_ = asyncio.Lock()
        self.client_opened_ = False
        self.connection_type_ = connection_type

    def get_connection_type(self):
        return self.connection_type_

    # Handles an open connection, infinite loop, until EOF
    async def new_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        async with self.write_lock_:
            self.reader_ = reader
            self.writer_ = writer
        if not self.client_opened_:
            # Prevents up from opening two connections on the same object
            async with self.open_lock_:
                if self.open_:
                    writer.close()
                    raise RuntimeError("This object already has open")
                self.open_ = True

        self.peername_ = writer.get_extra_info('peername')

        try:
            while not reader.at_eof():
                size = await reader.readexactly(LENGTH_BYTES)
                full_message_length = int.from_bytes(size, "big")
                full_message = await reader.readexactly(full_message_length)

                decoded = cbor2.loads(full_message)
                function: str = decoded["function"]
                function_data: bytes = decoded["data"]
                f = getattr(self.api_, function)
                if f is not None:
                    await f(function_data, self, peer_connections)
                else:
                    log.error(f'Invalid message: {function} from {self.peername_}')
        except IncompleteReadError:
            log.warn(f"Received EOF from {self.peername_}, closing connection")
        finally:
            await peer_connections.remove(self)
            writer.close()

    # Opens up a connection with a server
    async def open_connection(self, url: str, port: int):
        self.client_opened_ = True
        async with self.open_lock_:
            if self.open_:
                raise RuntimeError("Already open")
            self.open_ = True
        reader, writer = await asyncio.open_connection(url, port)
        await peer_connections.add(self)
        self.open_ = True
        self.reader_ = reader
        self.writer_ = writer
        self.peername_ = writer.get_extra_info('peername')
        return asyncio.create_task(self.new_connection(reader, writer))

    async def send(self, function_name: str, data: bytes):
        log.info(f"Sending {function_name} to peer {self.peername_}")
        async with self.write_lock_:
            transformed = transform_to_streamable(data)
            encoded = cbor2.dumps({"function": function_name, "data": transformed})
            self.writer_.write(len(encoded).to_bytes(LENGTH_BYTES, "big") + encoded)
            await self.writer_.drain()


async def start_server(api, host: str, port: int, connection_type=""):
    async def callback(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        connection = ChiaConnection(api, connection_type)
        await peer_connections.add(connection)
        await connection.new_connection(reader, writer)

    server: AbstractServer = await asyncio.start_server(
        callback, host, port)

    addr = server.sockets[0].getsockname()
    log.info(f'Serving {type(api).__name__} on {addr}')

    async with server:
        await server.serve_forever()
