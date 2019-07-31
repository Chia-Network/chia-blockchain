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
        self.api_ = api
        self.open_ = False
        self.open_lock_ = asyncio.Lock()
        self.write_lock_ = asyncio.Lock()
        self.client_opened_ = False
        self.peer_connections_ = peer_connections
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

                decoded = cbor.loads(full_message)
                function: str = decoded["function"]
                function_data: bytes = decoded["data"]
                f = getattr(self.api_, function)
                if f is not None:
                    await f(function_data, self, self.peer_connections_)
                else:
                    log.error(f'Invalid message: {function} from {self.peername_}')
        except IncompleteReadError:
            log.warn(f"Received EOF from {self.peername_}, closing connection")
        finally:
            await self.peer_connections_.remove(self)
            writer.close()

    # Opens up a connection with a server
    async def open_connection(self, url: str, port: int):
        self.client_opened_ = True
        async with self.open_lock_:
            if self.open_:
                raise RuntimeError("Already open")
            self.open_ = True
        reader, writer = await asyncio.open_connection(url, port)
        await self.peer_connections_.add(self)
        self.open_ = True
        self.reader_ = reader
        self.writer_ = writer
        self.peername_ = writer.get_extra_info('peername')
        return asyncio.create_task(self.new_connection(reader, writer))

    async def send(self, function_name: str, data: bytes):
        log.info(f"Sending {function_name} to peer {self.peername_}")
        async with self.write_lock_:
            encoded = cbor.dumps({"function": function_name, "data": data})
            self.writer_.write(len(encoded).to_bytes(LENGTH_BYTES, "big") + encoded)
            await self.writer_.drain()
