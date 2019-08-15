from asyncio import StreamReader, StreamWriter


class Connection:
    def __init__(self, connection_type: str, sr: StreamReader, sw: StreamWriter):
        self.connection_type = connection_type
        self.reader = sr
        self.writer = sw

    def get_peername(self):
        return self.writer.get_extra_info("peername")
