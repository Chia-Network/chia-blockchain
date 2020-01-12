import blspy

from src.types.sized_bytes import bytes32

Hash = bytes32


def std_hash(b) -> Hash:
    """
    The standard hash used in many places.
    """
    return Hash(blspy.Util.hash256(bytes(b)))
