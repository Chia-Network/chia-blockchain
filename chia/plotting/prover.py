from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from chia_rs import PlotSize, Prover, QualityProof
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint64
from chiapos import DiskProver

if TYPE_CHECKING:
    from chiapos import DiskProver


class PlotVersion(IntEnum):
    """Enum for plot format versions"""

    V1 = 1
    V2 = 2


class QualityProtocol(Protocol):
    def get_string(self) -> bytes32: ...


class ProverProtocol(Protocol):
    def get_filename(self) -> str: ...
    def get_size(self) -> PlotSize: ...
    def get_strength(self) -> uint8: ...
    def get_memo(self) -> bytes: ...
    def get_compression_level(self) -> uint8: ...
    def get_version(self) -> PlotVersion: ...
    def __bytes__(self) -> bytes: ...
    def get_id(self) -> bytes32: ...
    def get_qualities_for_challenge(
        self, challenge: bytes32, proof_fragment_filter: uint8
    ) -> list[QualityProtocol]: ...

    @classmethod
    def from_bytes(cls, data: bytes) -> ProverProtocol: ...


@dataclass(frozen=True)
class V2Quality(QualityProtocol):
    _quality_proof: QualityProof

    def get_string(self) -> bytes32:
        return self._quality_proof.serialize()


class V2Prover:
    """Placeholder for future V2 plot format support"""

    _prover: Prover

    if TYPE_CHECKING:
        _protocol_check: ClassVar[ProverProtocol] = cast("V2Prover", None)

    @classmethod
    def from_filename(cls, path: str) -> V2Prover:
        return V2Prover(Prover(path))

    @classmethod
    def from_bytes(cls, data: bytes) -> V2Prover:
        return V2Prover(Prover.from_bytes(data))

    def __init__(self, prover: Prover):
        self._prover = prover

    def get_filename(self) -> str:
        return self._prover.get_filename()

    def get_size(self) -> PlotSize:
        return PlotSize.make_v2(self._prover.size())

    def get_strength(self) -> uint8:
        return uint8(self._prover.get_strength())

    def get_memo(self) -> bytes:
        return self._prover.get_memo()

    def get_compression_level(self) -> uint8:
        # v2 plots are never compressed
        return uint8(0)

    def get_version(self) -> PlotVersion:
        return PlotVersion.V2

    def __bytes__(self) -> bytes:
        return self._prover.to_bytes()

    def get_id(self) -> bytes32:
        return self._prover.plot_id()

    def get_qualities_for_challenge(self, challenge: bytes32, proof_fragment_filter: uint8) -> list[QualityProtocol]:
        return [V2Quality(q) for q in self._prover.get_qualities_for_challenge(challenge, proof_fragment_filter)]

    def get_partial_proof(self, quality: V2Quality) -> list[uint64]:
        return self._prover.get_partial_proof(quality._quality_proof)[0]


@dataclass(frozen=True)
class V1Quality(QualityProtocol):
    _quality: bytes32

    def get_string(self) -> bytes32:
        return self._quality


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

    def get_strength(self) -> uint8:
        raise AssertionError("V1 plot format doesn't use strength")

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

    def get_qualities_for_challenge(self, challenge: bytes32, proof_fragment_filter: uint8) -> list[QualityProtocol]:
        return [V1Quality(bytes32(quality)) for quality in self._disk_prover.get_qualities_for_challenge(challenge)]

    def get_full_proof(self, challenge: bytes32, index: int, parallel_read: bool = True) -> bytes:
        return bytes(self._disk_prover.get_full_proof(challenge, index, parallel_read))

    @classmethod
    def from_bytes(cls, data: bytes) -> V1Prover:
        return cls(DiskProver.from_bytes(data))


def get_prover_from_bytes(filename: str, prover_data: bytes) -> ProverProtocol:
    if filename.endswith(".plot2"):
        return V2Prover(Prover.from_bytes(prover_data))
    elif filename.endswith(".plot"):
        return V1Prover(DiskProver.from_bytes(prover_data))
    else:
        raise ValueError(f"Unsupported plot file: {filename}")


def get_prover_from_file(filename: str) -> ProverProtocol:
    if filename.endswith(".plot2"):
        return V2Prover(Prover(filename))
    elif filename.endswith(".plot"):
        return V1Prover(DiskProver(filename))
    else:
        raise ValueError(f"Unsupported plot file: {filename}")
