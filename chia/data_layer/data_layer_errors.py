from typing import List

from chia.types.blockchain_format.sized_bytes import bytes32


class IntegrityError(Exception):
    pass


def build_message_with_hashes(message: str, bytes_objects: List[bytes]) -> str:
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


class TerminalInvalidKeyOrValueProgramError(IntegrityError):
    def __init__(self, node_hashes: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found terminal nodes with keys or values that are invalid programs:",
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
