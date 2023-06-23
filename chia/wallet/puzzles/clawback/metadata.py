from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint16, uint64
from chia.util.streamable import Streamable, streamable
from chia.wallet.wallet_puzzle_store import WalletPuzzleStore


@streamable
@dataclass(frozen=True)
class ClawbackMetadata(Streamable):
    time_lock: uint64
    sender_puzzle_hash: bytes32
    recipient_puzzle_hash: bytes32

    async def is_recipient(self, puzzle_store: WalletPuzzleStore) -> bool:
        if await puzzle_store.puzzle_hash_exists(self.sender_puzzle_hash):
            return False
        elif await puzzle_store.puzzle_hash_exists(self.recipient_puzzle_hash):
            return True
        else:
            raise ValueError("Both sender and recipient puzzle hashes not found in puzzle store")


class ClawbackVersion(IntEnum):
    V1 = uint16(1)


@streamable
@dataclass(frozen=True)
class AutoClaimSettings(Streamable):
    enabled: bool = False
    tx_fee: uint64 = uint64(0)
    min_amount: uint64 = uint64(0)
    batch_size: uint16 = uint16(50)
