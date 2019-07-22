import asyncio
from cbor2 import dumps, loads

LENGTH_BYTES: int = 5


def transform_to_streamable(d):
    """
    Drill down through dictionaries and lists and transform objects with "as_bin" to bytes.
    """
    print("?")
    if hasattr(d, "as_bin"):
        return d.as_bin()
    if isinstance(d, (str, bytes, int)):
        return d
    if isinstance(d, dict):
        new_d = {}
        for k, v in d.items():
            new_d[transform_to_streamable(k)] = transform_to_streamable(v)
        return new_d
    return [transform_to_streamable(_) for _ in d]


class ChiaProtocol(asyncio.Protocol):
    def __init__(self, on_con_lost, loop, api):
        self.loop_ = loop
        self.on_con_lost_ = on_con_lost
        self.api_ = api
        self.message_ = b''

    def connection_made(self, transport):
        peername = transport.get_extra_info('peername')
        print(f'Connection from {peername}')
        self.transport_ = transport

    def connection_lost(self, exc):
        peername = self.transport_.get_extra_info('peername')
        if exc is None:
            print(f'Connection lost to {peername}')
        else:
            print(f'Connection lost to {peername} exception {exc}')

    async def send(self, function, data):
        encoded = dumps({"function": function, "data": transform_to_streamable(data)})
        await self.transport_.write(len(encoded).to_bytes(LENGTH_BYTES, "big") + encoded)

    def data_received(self, data):
        peername = self.transport_.get_extra_info('peername')
        if data is not None:
            self.message_ += data
            full_message_length = 0
            if len(self.message_) >= LENGTH_BYTES:
                full_message_length = int.from_bytes(self.message_[:LENGTH_BYTES], "big")
                if len(self.message_) - LENGTH_BYTES < full_message_length:
                    return
            else:
                return

            decoded = loads(data[LENGTH_BYTES:])
            function = decoded["function"]
            function_data = decoded["data"]
            f = getattr(self.api_, function)
            if f is not None:
                print(f'Message of size {full_message_length}: {function}({function_data[:100]}) from {peername}')
                f(function_data)
            else:
                print(f'Invalid message: {function} from {peername}')

    def eof_received(self):
        peername = self.transport_.get_extra_info('peername')
        print(f'EOF received from {peername}')
        return None  # Closes the connection
