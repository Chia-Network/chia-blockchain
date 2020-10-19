from blspy import G2Element
from src.types.classgroup import ClassgroupElement
from src.types.sized_bytes import bytes32
from src.util.hash import std_hash


def infuse_signature(output: ClassgroupElement, signature: G2Element) -> bytes32:
    return std_hash(bytes(output) + bytes(signature))
