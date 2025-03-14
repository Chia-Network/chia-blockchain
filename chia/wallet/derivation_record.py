from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from chia_rs import G1Element
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint32

from chia.util.streamable import Streamable, streamable
from chia.wallet.util.wallet_types import WalletType


@dataclass(frozen=True)
class DerivationRecord:
    """
    These are records representing a puzzle hash, which is generated from a
    public key, derivation index, and wallet type. Stored in the puzzle_store.
    """

    index: uint32
    puzzle_hash: bytes32
    _pubkey: Union[G1Element, bytes]
    wallet_type: WalletType
    wallet_id: uint32
    hardened: bool

    @property
    def pubkey(self) -> G1Element:
        assert isinstance(self._pubkey, G1Element)
        return self._pubkey


@streamable
@dataclass(frozen=True)
class StreamableDerivationRecord(Streamable):
    index: uint32
    puzzle_hash: bytes32
    pubkey: bytes
    wallet_type: uint32
    wallet_id: uint32
    hardened: bool

    @classmethod
    def from_standard(cls, record: DerivationRecord) -> StreamableDerivationRecord:
        return cls(
            record.index,
            record.puzzle_hash,
            bytes(record._pubkey),
            uint32(record.wallet_type.value),
            record.wallet_id,
            record.hardened,
        )

    def to_standard(self) -> DerivationRecord:
        return DerivationRecord(
            self.index,
            self.puzzle_hash,
            G1Element.from_bytes(self.pubkey),
            WalletType(self.wallet_type),
            self.wallet_id,
            self.hardened,
        )
