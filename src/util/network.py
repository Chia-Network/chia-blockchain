import secrets
import sys

from src.types.sized_bytes import bytes32
from src.util.ints import uint16


def parse_port(api) -> uint16:
    port: uint16 = uint16(int(sys.argv[1]) if len(sys.argv) >= 2 else api.config["port"])
    return port


def create_node_id() -> bytes32:
    """Generates a transient random node_id."""
    return bytes32(secrets.token_bytes(32))
