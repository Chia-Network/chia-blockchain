from __future__ import annotations

import asyncio
import logging
from src.util import cbor
from asyncio import IncompleteReadError

log = logging.getLogger(__name__)

LENGTH_BYTES: int = 5


# A new ChiaConnection object is created every time a connection is opened
class ChiaConnection:
    def __init__(self, api, peer_connections, connection_type=""):
        self._api = api
        self._open = False
        self._open_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._client_opened = False
        self._peer_connections = peer_connections
        self._connection_type = connection_type

    def get_connection_type(self):
        return self._connection_type

    # Handles an open connection, infinite loop, until EOF
    async def new_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        async with self._write_lock:
            self._reader = reader
            self._writer = writer
        if not self._client_opened:
            # Prevents up from opening two connections on the same object
            async with self._open_lock:
                if self._open:
                    writer.close()
                    raise RuntimeError("This object already has open")
                self._open = True

        self._peername = writer.get_extra_info('peername')

        try:
            while not reader.at_eof():
                size = await reader.readexactly(LENGTH_BYTES)
                full_message_length = int.from_bytes(size, "big")
                full_message = await reader.readexactly(full_message_length)

                decoded = cbor.loads(full_message)
                function: str = decoded["function"]
                function_data: bytes = decoded["data"]
                f = getattr(self._api, function)
                if f is not None:
                    await f(function_data, self, self._peer_connections)
                else:
                    log.error(f'Invalid message: {function} from {self._peername}')
        except IncompleteReadError:
            log.warn(f"Received EOF from {self._peername}, closing connection")
        finally:
            await self._peer_connections.remove(self)
            writer.close()

    # Opens up a connection with a server
    async def open_connection(self, url: str, port: int):
        self._client_opened = True
        async with self._open_lock:
            if self._open:
                raise RuntimeError("Already open")
            self._open = True
        reader, writer = await asyncio.open_connection(url, port)
        await self._peer_connections.add(self)
        self._open = True
        self._reader = reader
        self._writer = writer
        self._peername = writer.get_extra_info('peername')
        return asyncio.create_task(self.new_connection(reader, writer))

    async def send(self, function_name: str, data: bytes):
        log.info(f"Sending {function_name} to peer {self._peername}")
        async with self._write_lock:
            encoded: bytes = cbor.dumps({"function": function_name, "data": data})
            assert(len(encoded) < (2**(LENGTH_BYTES*8)))
            self._writer.write(len(encoded).to_bytes(LENGTH_BYTES, "big") + encoded)
            await self._writer.drain()
