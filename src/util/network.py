import secrets

from src.types.sized_bytes import bytes32


def create_node_id() -> bytes32:
    """Generates a transient random node_id."""
    return bytes32(secrets.token_bytes(32))
