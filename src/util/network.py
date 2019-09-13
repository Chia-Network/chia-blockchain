import sys
from hashlib import sha256
from typing import Tuple
from src.types.sized_bytes import bytes32
from src.server.connection import Connection


def parse_host_port(api) -> Tuple[str, int]:
    host: str = sys.argv[1] if len(sys.argv) >= 3 else api.host
    port: int = int(sys.argv[2]) if len(sys.argv) >= 3 else api.port
    return (host, port)


def create_node_id(connection: Connection) -> bytes32:
    return bytes32(sha256((connection.connection_type + ":" + connection.local_host + ":" +
                          str(connection.local_port)).encode()).digest())
