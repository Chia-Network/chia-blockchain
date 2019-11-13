import sys
import secrets
from typing import Tuple
from src.types.sized_bytes import bytes32


def parse_host_port(api) -> Tuple[str, int]:
    host: str = sys.argv[1] if len(sys.argv) >= 3 else api.config['host']
    port: int = int(sys.argv[2]) if len(sys.argv) >= 3 else api.config['port']
    return (host, port)


def create_node_id() -> bytes32:
    """Generates a transient random node_id."""
    return bytes32(secrets.token_bytes(32))
