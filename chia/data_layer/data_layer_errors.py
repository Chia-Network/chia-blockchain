from typing import List

from chia.types.blockchain_format.sized_bytes import bytes32


class IntegrityError(Exception):
    pass


def build_message_with_hashes(message: str, node_hashes: List[bytes32]) -> str:
    return "\n".join([message, *[f"    {hash.hex()}" for hash in node_hashes]])


class InternalKeyValueError(IntegrityError):
    def __init__(self, node_hashes: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found internal nodes with key or value specified:",
                node_hashes=node_hashes,
            )
        )


class InternalLeftRightNotBytes32Error(IntegrityError):
    def __init__(self, node_hashes: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found internal nodes with left or right that are not bytes32:",
                node_hashes=node_hashes,
            )
        )


class TerminalLeftRightError(IntegrityError):
    def __init__(self, node_hashes: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found terminal nodes with left or right specified:",
                node_hashes=node_hashes,
            )
        )


class TerminalInvalidKeyOrValueProgramError(IntegrityError):
    def __init__(self, node_hashes: List[bytes32]) -> None:
        super().__init__(
            build_message_with_hashes(
                message="Found terminal nodes with keys or values that are invalid programs:",
                node_hashes=node_hashes,
            )
        )
