from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8
from chiapos import DiskProver

if TYPE_CHECKING:
    from chiapos import DiskProver


class ProverProtocol(ABC):
    """Abstract protocol for all prover implementations (V1 and V2)"""

    @abstractmethod
    def get_filename(self) -> Path:
        """Returns the filename of the plot"""

    @abstractmethod
    def get_filename_str(self) -> str:
        """Returns the filename of the plot"""

    @abstractmethod
    def get_size(self) -> uint8:
        """Returns the k size of the plot"""

    @abstractmethod
    def get_memo(self) -> bytes:
        """Returns the memo containing keys and other metadata"""

    @abstractmethod
    def get_compression_level(self) -> uint8:
        """Returns the compression level (0 for uncompressed)"""

    @abstractmethod
    def get_version(self) -> int:
        """Returns the plot version (1 for V1, 2 for V2)"""

    @abstractmethod
    def __bytes__(self) -> bytes:
        """Returns the prover serialized as bytes for caching"""

    @abstractmethod
    def get_id(self) -> bytes32:
        """Returns the plot ID"""

    @abstractmethod
    def get_qualities_for_challenge(self, challenge: bytes32) -> list[bytes32]:
        """Returns the qualities for a given challenge"""

    @abstractmethod
    def get_full_proof(self, challenge: bytes, index: int, parallel_read: bool = True) -> bytes:
        """Returns the full proof for a given challenge and index"""

    @classmethod
    @abstractmethod
    def from_bytes(cls, data: bytes) -> ProverProtocol:
        """Create a prover from serialized bytes"""


class V2Prover(ProverProtocol):
    """V2 Plot Prover implementation - currently stubbed"""

    def __init__(self, filename: str):
        self._filename = filename
        # TODO: Implement V2 plot file parsing and validation

    def get_filename(self) -> Path:
        return Path(self._filename)

    def get_filename_str(self) -> str:
        return str(self._filename)

    def get_size(self) -> uint8:
        # TODO: Extract k size from V2 plot file
        return uint8(32)  # Stub value

    def get_memo(self) -> bytes:
        # TODO: Extract memo from V2 plot file
        return b""  # Stub value

    def get_compression_level(self) -> uint8:
        # TODO: Extract compression level from V2 plot file
        return uint8(0)  # Stub value

    def get_version(self) -> int:
        return 2

    def __bytes__(self) -> bytes:
        # TODO: Implement proper V2 prover serialization for caching
        # For now, just serialize the filename as a placeholder
        return self._filename.encode("utf-8")

    def get_id(self) -> bytes32:
        # TODO: Extract plot ID from V2 plot file
        return bytes32(b"")  # Stub value

    def get_qualities_for_challenge(self, challenge: bytes) -> list[bytes32]:
        # TODO: Implement V2 plot quality lookup
        return []  # Stub value

    def get_full_proof(self, challenge: bytes, index: int, parallel_read: bool = True) -> bytes:
        # TODO: Implement V2 plot proof generation
        return b""  # Stub value

    @classmethod
    def from_bytes(cls, data: bytes) -> V2Prover:
        # TODO: Implement proper V2 prover deserialization from cache
        # For now, just deserialize the filename
        filename = data.decode("utf-8")
        return cls(filename)


class V1Prover(ProverProtocol):
    """Wrapper for existing DiskProver to implement ProverProtocol"""

    def __init__(self, disk_prover: DiskProver) -> None:
        self._disk_prover = disk_prover

    def get_filename(self) -> Path:
        return Path(self._disk_prover.get_filename())

    def get_filename_str(self) -> str:
        return str(self._disk_prover.get_filename())

    def get_size(self) -> uint8:
        return uint8(self._disk_prover.get_size())

    def get_memo(self) -> bytes:
        return bytes(self._disk_prover.get_memo())

    def get_compression_level(self) -> uint8:
        return uint8(self._disk_prover.get_compression_level())

    def get_version(self) -> int:
        return 1

    def __bytes__(self) -> bytes:
        return bytes(self._disk_prover)

    def get_id(self) -> bytes32:
        return bytes32(self._disk_prover.get_id())

    def get_qualities_for_challenge(self, challenge: bytes32) -> list[bytes32]:
        return [bytes32(quality) for quality in self._disk_prover.get_qualities_for_challenge(challenge)]

    def get_full_proof(self, challenge: bytes, index: int, parallel_read: bool = True) -> bytes:
        return bytes(self._disk_prover.get_full_proof(challenge, index, parallel_read))

    @classmethod
    def from_bytes(cls, data: bytes) -> V1Prover:
        """Create V1ProverWrapper from serialized bytes"""
        from chiapos import DiskProver

        disk_prover = DiskProver.from_bytes(data)
        return cls(disk_prover)

    @property
    def disk_prover(self) -> DiskProver:
        """Access to underlying DiskProver for backwards compatibility"""
        return self._disk_prover


def get_prover_from_bytes(filename: str, prover_data: bytes) -> ProverProtocol:
    """Factory function to create appropriate prover based on plot version"""
    if filename.endswith(".plot_v2"):
        return V2Prover.from_bytes(prover_data)
    elif filename.endswith(".plot"):
        return V1Prover(DiskProver.from_bytes(prover_data))
    else:
        raise ValueError(f"Unsupported plot file: {filename}")


def get_prover_from_file(filename: str) -> ProverProtocol:
    """Factory function to create appropriate prover based on plot version"""
    if filename.endswith(".plot_v2"):
        return V2Prover(filename)
    elif filename.endswith(".plot"):
        return V1Prover(DiskProver(filename))
    else:
        raise ValueError(f"Unsupported plot file: {filename}")
