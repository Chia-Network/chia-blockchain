import asyncio
import cbor2
from src.plotter import Plotter


LENGTH_BYTES: int = 5

class ChiaConnection:
    def __init__(self):
        pass


async def new_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peername = writer.get_extra_info('peername')
    print(f'Connection from {peername}')
    size = await reader.read(LENGTH_BYTES)
    full_message_length = int.from_bytes(size, "big")
    full_message = await reader.read(full_message_length)

    decoded = cbor2.loads(full_message)
    function: str = decoded["function"]
    function_data: bytes = decoded["data"]

    f = getattr(self.api_, function)
    if f is not None:
        print(f'Message of size {full_message_length}: {function}({function_data[:100]}) from {peername}')
        f(function_data)
    else:
        print(f'Invalid message: {function} from {peername}')


async def main(api):

    async def new_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    server = await asyncio.start_server(
        lambda x, y: ChiaConnection(x, y, api), '127.0.0.1', 8888)

    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()

asyncio.run(main(Plotter()))
# # TODO: run other servers (farmer, full node, timelord)