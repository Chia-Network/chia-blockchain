from typing import List, Iterable

from chia.types.blockchain_format.sized_bytes import bytes32


class IntegrityError(Exception):
    pass


def build_message_with_hashes(message: str, bytes_objects: Iterable[bytes]) -> str:
    return "\n".join([message, *[f"    {b.hex()}" for b in bytes_objects]])


class InternalKeyValueError(IntegrityError):
    def __init__(self, node_hashes: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found internal nodes with key or value specified:",
                bytes_objects=node_hashes,
            )
        )


class InternalLeftRightNotBytes32Error(IntegrityError):
    def __init__(self, node_hashes: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found internal nodes with left or right that are not bytes32:",
                bytes_objects=node_hashes,
            )
        )


class TerminalLeftRightError(IntegrityError):
    def __init__(self, node_hashes: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found terminal nodes with left or right specified:",
                bytes_objects=node_hashes,
            )
        )


class TreeGenerationIncrementingError(IntegrityError):
    def __init__(self, tree_ids: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found trees with generations not properly incrementing:",
                bytes_objects=tree_ids,
            )
        )


class NodeHashError(IntegrityError):
    def __init__(self, node_hashes: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found nodes with incorrect hashes:",
                bytes_objects=node_hashes,
            )
        )


class AncestorTableError(IntegrityError):
    def __init__(self, node_hashes: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found nodes with wrong ancestor:",
                bytes_objects=node_hashes,
            )
        )
