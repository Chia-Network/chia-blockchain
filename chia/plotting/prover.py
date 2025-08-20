from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from chia_rs import PlotSize
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8
from chiapos import DiskProver

if TYPE_CHECKING:
    from chiapos import DiskProver


class PlotVersion(IntEnum):
    """Enum for plot format versions"""

    V1 = 1
    V2 = 2


class ProverProtocol(Protocol):
    def get_filename(self) -> str: ...
    def get_size(self) -> PlotSize: ...
    def get_memo(self) -> bytes: ...
    def get_compression_level(self) -> uint8: ...
    def get_version(self) -> PlotVersion: ...
    def __bytes__(self) -> bytes: ...
    def get_id(self) -> bytes32: ...
    def get_qualities_for_challenge(self, challenge: bytes32) -> list[bytes32]: ...
    def get_full_proof(self, challenge: bytes, index: int, parallel_read: bool = True) -> bytes: ...

    @classmethod
    def from_bytes(cls, data: bytes) -> ProverProtocol: ...


class V2Prover:
    """Placeholder for future V2 plot format support"""

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ProverProtocol] = cast("V2Prover", None)

    def __init__(self, filename: str):
        self._filename = filename

    def get_filename(self) -> str:
        return str(self._filename)

    def get_size(self) -> PlotSize:
        # TODO: todo_v2_plots get k size from plot
        raise NotImplementedError("V2 plot format is not yet implemented")

    def get_memo(self) -> bytes:
        # TODO: todo_v2_plots
        raise NotImplementedError("V2 plot format is not yet implemented")

    def get_compression_level(self) -> uint8:
        # TODO: todo_v2_plots implement compression level retrieval
        raise NotImplementedError("V2 plot format is not yet implemented")

    def get_version(self) -> PlotVersion:
        return PlotVersion.V2

    def __bytes__(self) -> bytes:
        # TODO: todo_v2_plots Implement prover serialization for caching
        raise NotImplementedError("V2 plot format is not yet implemented")

    def get_id(self) -> bytes32:
        # TODO: Extract plot ID from V2 plot file
        raise NotImplementedError("V2 plot format is not yet implemented")

    def get_qualities_for_challenge(self, challenge: bytes) -> list[bytes32]:
        # TODO: todo_v2_plots Implement plot quality lookup
        raise NotImplementedError("V2 plot format is not yet implemented")

    def get_full_proof(self, challenge: bytes, index: int, parallel_read: bool = True) -> bytes:
        # TODO: todo_v2_plots Implement plot proof generation
        raise NotImplementedError("V2 plot format is not yet implemented")

    @classmethod
    def from_bytes(cls, data: bytes) -> V2Prover:
        # TODO: todo_v2_plots Implement prover deserialization from cache
        raise NotImplementedError("V2 plot format is not yet implemented")


class V1Prover:
    """Wrapper for existing DiskProver to implement ProverProtocol"""

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ProverProtocol] = cast("V1Prover", None)

    def __init__(self, disk_prover: DiskProver) -> None:
        self._disk_prover = disk_prover

    def get_filename(self) -> str:
        return str(self._disk_prover.get_filename())

    def get_size(self) -> PlotSize:
        return PlotSize.make_v1(uint8(self._disk_prover.get_size()))

    def get_memo(self) -> bytes:
        return bytes(self._disk_prover.get_memo())

    def get_compression_level(self) -> uint8:
        return uint8(self._disk_prover.get_compression_level())

    def get_version(self) -> PlotVersion:
        return PlotVersion.V1

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
        return cls(DiskProver.from_bytes(data))


def get_prover_from_bytes(filename: str, prover_data: bytes) -> ProverProtocol:
    if filename.endswith(".plot2"):
        return V2Prover.from_bytes(prover_data)
    elif filename.endswith(".plot"):
        return V1Prover(DiskProver.from_bytes(prover_data))
    else:
        raise ValueError(f"Unsupported plot file: {filename}")


def get_prover_from_file(filename: str) -> ProverProtocol:
    if filename.endswith(".plot2"):
        return V2Prover(filename)
    elif filename.endswith(".plot"):
        return V1Prover(DiskProver(filename))
    else:
        raise ValueError(f"Unsupported plot file: {filename}")
