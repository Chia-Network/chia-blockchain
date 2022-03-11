from dataclasses import dataclass
from typing import Dict, List, Optional, TypedDict

from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint64


class TxAdditionRequest(TypedDict):
    puzzle_hash: str
    amount: int
    memos: Optional[List[str]]


@dataclass(frozen=True)
class TxAddition:
    puzzle_hash: bytes32
    amount: uint64
    memos: Optional[List[bytes]] = None

    @classmethod
    def from_json(cls, data: TxAdditionRequest):
        return cls(
            puzzle_hash=bytes32(hexstr_to_bytes(data["puzzle_hash"])),
            amount=uint64(data["amount"]),
            memos=[m.encode("utf8") for m in data["memos"]] if data["memos"] else None,
        )

    def to_json(self) -> TxAdditionRequest:
        return {
            "puzzle_hash": self.puzzle_hash.hex(),
            "amount": self.amount,
            "memos": [m.decode("utf8") for m in self.memos] if self.memos else None,
        }


class CatSpendMultiRequest(TypedDict):
    wallet_id: int
    additions: List[TxAdditionRequest]
    coins: Optional[List[Dict]]
    fee: Optional[uint64]
